"""DATA-005 fplcache historical snapshot tests; MockTransport and deterministic index."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import lzma
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from fpl_engine.data.http_cache import CacheRequest, CacheState, HttpCache, HttpCacheWriteError
from fpl_engine.data.providers.fplcache import (
    DEFAULT_BASE_URL, FPLCacheAdapter, FPLCacheNoSnapshotError, FPLCacheParseError,
    FPLCacheRequestError, FPLCacheResponseError, FPLCacheSnapshotReference,
    FPLCacheStorageError, FPLCacheValidationError,
)
from fpl_engine.data.raw_store import RawStore, RawStoreWriteError


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
REF = "0123456789abcdef0123456789abcdef01234567"
FIXTURE = Path(__file__).parent / "fixtures" / "fplcache" / "bootstrap.json"
PATHS = (
    "cache/2024/8/16/1700.json.xz",
    "cache/2024/8/16/1730.json.xz",
    "cache/2024/8/16/1800.json.xz",
    "cache/2024/8/16/1830.json.xz",
)


@pytest.fixture
def env(tmp_path):
    state = SimpleNamespace(
        now=NOW, calls=[], status=200, error=None,
        body=lzma.compress(FIXTURE.read_bytes(), format=lzma.FORMAT_XZ),
        headers={"Content-Type": "application/x-xz", "ETag": '"v1"',
                 "Set-Cookie": "private-cookie"},
    )
    def handle(request):
        state.calls.append(request)
        if state.error is not None:
            raise state.error
        return httpx.Response(state.status, content=state.body, headers=state.headers)
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        state.cache = HttpCache(tmp_path / "cache", clock=lambda: state.now)
        state.raw = RawStore(tmp_path / "raw")
        state.options = dict(client=client, cache=state.cache, raw_store=state.raw,
                             repository_ref=REF, snapshot_index=PATHS,
                             ttl=timedelta(seconds=10), clock=lambda: state.now)
        state.adapter = FPLCacheAdapter(**state.options)
        yield state


def raw_metadata(env):
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in env.raw.root.rglob("snapshot.metadata.json")]


def source_url(path):
    return f"{DEFAULT_BASE_URL}/{REF}/{path}"


def cache_request(path):
    return CacheRequest("fplcache", "GET", source_url(path))


def test_selects_latest_snapshot_strictly_before_cutoff(env):
    selected = env.adapter.select_snapshot(datetime(2024, 8, 16, 18, 0, tzinfo=timezone.utc))
    assert selected.path == PATHS[1]
    assert selected.snapshot_timestamp == datetime(2024, 8, 16, 17, 30, tzinfo=timezone.utc)
    # A closer future snapshot must never win point-in-time selection.
    result = env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, 0, tzinfo=timezone.utc))
    assert result.snapshot_path == PATHS[1]
    assert result.snapshot_timestamp < result.prediction_timestamp
    assert str(env.calls[0].url) == source_url(PATHS[1])


@pytest.mark.parametrize("cutoff,expected", [
    (datetime(2024, 8, 16, 17, 0, tzinfo=timezone.utc), None),
    (datetime(2024, 8, 16, 17, 30, tzinfo=timezone.utc), PATHS[0]),
    (datetime(2024, 8, 16, 17, 30, 1, tzinfo=timezone.utc), PATHS[1]),
    (datetime(2024, 8, 16, 18, 30, tzinfo=timezone.utc), PATHS[2]),
    (datetime(2024, 8, 16, 18, 30, 1, tzinfo=timezone.utc), PATHS[3]),
])
def test_exact_boundary_is_never_selected(env, cutoff, expected):
    if expected is None:
        with pytest.raises(FPLCacheNoSnapshotError, match="strictly before"):
            env.adapter.select_snapshot(cutoff)
    else:
        assert env.adapter.select_snapshot(cutoff).path == expected


def test_snapshot_timezone_normalization_and_sorted_index(env):
    cutoff = datetime(2024, 8, 16, 20, tzinfo=timezone(timedelta(hours=2)))
    assert env.adapter.select_snapshot(cutoff).path == PATHS[1]
    assert [reference.path for reference in env.adapter.snapshot_index] == list(PATHS)
    with pytest.raises(AttributeError):
        env.adapter.snapshot_index += ()


def test_end_to_end_exact_xz_raw_cache_and_preserved_fields(env, monkeypatch):
    store = Mock(wraps=env.raw.store_bytes)
    monkeypatch.setattr(env.raw, "store_bytes", store)
    cutoff = datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    first = env.adapter.get_snapshot_before(cutoff)
    second = env.adapter.get_snapshot_before(cutoff)
    assert len(env.calls) == store.call_count == len(raw_metadata(env)) == 1
    assert not first.from_cache and second.from_cache
    assert first.raw_snapshot is not None and second.raw_snapshot is None
    assert first.data == second.data == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert first.data["extra_provider_field"] == {"preserved": True}
    element = first.data["elements"][0]
    assert element["now_cost"] == 75
    assert element["selected_by_percent"] == "12.3"
    assert element["transfers_in_event"] == 100
    assert element["status"] == "d" and element["news"] == "Knock"
    assert element["chance_of_playing_next_round"] == 50
    assert first.response.body == env.body
    assert env.raw.read_bytes(first.raw_snapshot) == env.body
    assert first.response.checksum == hashlib.sha256(env.body).hexdigest()
    assert "set-cookie" not in first.response.headers
    metadata = raw_metadata(env)[0]
    assert metadata["source_provider"] == "fplcache"
    assert metadata["entity"] == "bootstrap_snapshot"
    assert metadata["source_url"] == source_url(PATHS[1])
    assert metadata["source_record_id"] == f"{REF}:{PATHS[1]}"
    assert metadata["retrieved_at"] == "2026-09-07T12:00:00Z"
    assert first.snapshot_timestamp == datetime(2024, 8, 16, 17, 30, tzinfo=timezone.utc)
    assert first.prediction_timestamp == cutoff
    assert first.retrieved_at == NOW and first.retrieved_at.tzinfo is timezone.utc
    assert second.retrieved_at == first.response.stored_at
    assert not env.options["client"].is_closed


def test_different_snapshot_paths_have_distinct_cache_and_raw_identity(env):
    first = env.adapter.get_snapshot_before(datetime(2024, 8, 16, 17, 30, 1, tzinfo=timezone.utc))
    env.now += timedelta(seconds=1)
    second = env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, 0, tzinfo=timezone.utc))
    assert first.snapshot_path == PATHS[1] and second.snapshot_path == PATHS[1]
    assert second.from_cache  # Same chosen archive remains a cache hit.
    third = env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, 30, 1, tzinfo=timezone.utc))
    assert third.snapshot_path == PATHS[3]
    assert first.response.cache_key != third.response.cache_key
    assert first.raw_snapshot.snapshot_id != third.raw_snapshot.snapshot_id
    assert len(env.calls) == len(raw_metadata(env)) == 2


def test_stale_refresh_creates_new_raw_snapshot(env):
    cutoff = datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    first = env.adapter.get_snapshot_before(cutoff)
    env.now += timedelta(seconds=10)
    second = env.adapter.get_snapshot_before(cutoff)
    assert not second.from_cache
    assert second.raw_snapshot.snapshot_id != first.raw_snapshot.snapshot_id
    assert len(env.calls) == len(raw_metadata(env)) == 2
    assert env.raw.read_bytes(first.raw_snapshot) == env.raw.read_bytes(second.raw_snapshot) == env.body


def test_immutable_ref_policy_avoids_refresh(env):
    adapter = FPLCacheAdapter(**{**env.options, "ttl": None})
    cutoff = datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    first = adapter.get_snapshot_before(cutoff)
    env.now += timedelta(days=365)
    second = adapter.get_snapshot_before(cutoff)
    assert first.response.expires_at is None and second.from_cache
    assert len(env.calls) == len(raw_metadata(env)) == 1


@pytest.mark.parametrize("body", [b"", b"not xz", lzma.compress(b"{broken", format=lzma.FORMAT_XZ),
                                  lzma.compress(b"[]", format=lzma.FORMAT_XZ),
                                  lzma.compress(b'{"value": NaN}', format=lzma.FORMAT_XZ)])
def test_bad_xz_or_json_is_raw_preserved_but_never_returned(env, body):
    env.body = body
    cutoff = datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    with pytest.raises((FPLCacheParseError, FPLCacheResponseError)):
        env.adapter.get_snapshot_before(cutoff)
    assert len(env.calls) == len(raw_metadata(env)) == 1
    assert env.cache.get(cache_request(PATHS[1])).response.body == body
    with pytest.raises((FPLCacheParseError, FPLCacheResponseError)):
        env.adapter.get_snapshot_before(cutoff)
    assert len(env.calls) == len(raw_metadata(env)) == 1


def test_decompression_limit_and_trailing_stream_are_rejected(env):
    adapter = FPLCacheAdapter(**{**env.options, "max_decompressed_bytes": 8})
    with pytest.raises(FPLCacheParseError):
        adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert len(raw_metadata(env)) == 1

    env2_body = lzma.compress(b"{}", format=lzma.FORMAT_XZ) + lzma.compress(b"{}", format=lzma.FORMAT_XZ)
    env.body = env2_body
    env.cache.invalidate(cache_request(PATHS[1]))
    env.now += timedelta(seconds=1)
    with pytest.raises(FPLCacheParseError):
        env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))


@pytest.mark.parametrize("status", [100, 301, 304, 400, 404, 429, 500, 503])
def test_non_success_has_context_and_never_creates_raw_cache(env, caplog, status):
    env.status, env.body = status, b"private response body"
    with pytest.raises(FPLCacheResponseError) as caught:
        env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert str(status) in str(caught.value) and PATHS[1] in str(caught.value)
    assert "private response body" not in str(caught.value) + caplog.text
    assert not raw_metadata(env)
    assert env.cache.get(cache_request(PATHS[1])).state is CacheState.MISS


@pytest.mark.parametrize("error,match", [
    (httpx.ConnectError("private transport detail"), "transport failed"),
    (httpx.ReadTimeout("private timeout detail"), "timed out"),
])
def test_transport_errors_are_chained_and_not_stored(env, error, match):
    env.error = error
    with pytest.raises(FPLCacheRequestError, match=match) as caught:
        env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert caught.value.__cause__ is error
    assert "private transport detail" not in str(caught.value)
    assert not raw_metadata(env) and env.cache.get(cache_request(PATHS[1])).state is CacheState.MISS


@pytest.mark.parametrize("path,timestamp", [
    ("cache/2024/8/16/0930.json.xz", datetime(2024, 8, 16, 9, 30, tzinfo=timezone.utc)),
    ("cache/2024/08/06/0000.json.xz", datetime(2024, 8, 6, tzinfo=timezone.utc)),
])
def test_snapshot_path_parsing(path, timestamp):
    reference = FPLCacheSnapshotReference.from_path(path)
    assert reference.path == path and reference.snapshot_timestamp == timestamp


@pytest.mark.parametrize("path", ["", "cache/2024/8/16/930.json.xz", "cache/2024/8/16/2400.json.xz",
    "cache/2024/13/16/0900.json.xz", "cache/2024/2/30/0900.json.xz", "../cache/2024/8/16/0900.json.xz",
    "cache/2024/8/16/0900.json", "cache/2024/8/16/0900.json.xz/extra", None])
def test_invalid_snapshot_paths_rejected(path):
    with pytest.raises(FPLCacheValidationError):
        FPLCacheSnapshotReference.from_path(path)


@pytest.mark.parametrize("index", ["cache/2024/8/16/0900.json.xz", [PATHS[0], PATHS[0]],
    ["bad"], None])
def test_invalid_or_ambiguous_index_rejected(env, index):
    with pytest.raises(FPLCacheValidationError):
        FPLCacheAdapter(**{**env.options, "snapshot_index": index})


def test_supplied_reference_is_reparsed_from_its_path(env):
    forged = FPLCacheSnapshotReference(datetime(2024, 8, 16, 17, tzinfo=timezone.utc), PATHS[1])
    adapter = FPLCacheAdapter(**{**env.options, "snapshot_index": [forged]})
    assert adapter.snapshot_index[0] == FPLCacheSnapshotReference.from_path(PATHS[1])


@pytest.mark.parametrize("timestamp", [datetime(2024, 8, 16, 18), "2024-08-16T18:00:00Z", None])
def test_invalid_prediction_timestamp_rejected_before_http(env, timestamp):
    with pytest.raises(FPLCacheValidationError):
        env.adapter.get_snapshot_before(timestamp)
    assert not env.calls and not raw_metadata(env)


@pytest.mark.parametrize("ref", ["main", "v1.2.3", REF, "archive/2024"])
def test_supported_ref_is_retained_and_changes_url(env, ref):
    adapter = FPLCacheAdapter(**{**env.options, "repository_ref": ref})
    result = adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert result.repository_ref == ref
    assert str(env.calls[0].url) == f"{DEFAULT_BASE_URL}/{ref}/{PATHS[1]}"


@pytest.mark.parametrize("ref", ["", ".", "..", "../main", "refs/../main", "/main", "main/", "main//x", "main\\x", "main x", "main?x", "main#x", "CON", 1, None])
def test_unsafe_ref_rejected_before_http(env, ref):
    with pytest.raises(FPLCacheValidationError, match="ref"):
        FPLCacheAdapter(**{**env.options, "repository_ref": ref})
    assert not env.calls


def test_injected_clock_and_storage_error_ordering(env, monkeypatch):
    clock = Mock(return_value=NOW.astimezone(timezone(timedelta(hours=3))))
    env.now += timedelta(seconds=2)
    result = FPLCacheAdapter(**{**env.options, "clock": clock}).get_snapshot_before(
        datetime(2024, 8, 16, 18, tzinfo=timezone.utc)
    )
    assert result.retrieved_at == NOW and result.response.stored_at == env.now
    clock.assert_called_once_with()

    env.cache.invalidate(cache_request(PATHS[1]))
    raw_failure = RawStoreWriteError("disk failure")
    monkeypatch.setattr(env.raw, "store_bytes", Mock(side_effect=raw_failure))
    with pytest.raises(FPLCacheStorageError) as caught:
        env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert caught.value.__cause__ is raw_failure
    assert env.cache.get(cache_request(PATHS[1])).state is CacheState.MISS


def test_cache_write_failure_leaves_raw_evidence(env, monkeypatch):
    failure = HttpCacheWriteError("disk failure")
    monkeypatch.setattr(env.cache, "put", Mock(side_effect=failure))
    with pytest.raises(FPLCacheStorageError) as caught:
        env.adapter.get_snapshot_before(datetime(2024, 8, 16, 18, tzinfo=timezone.utc))
    assert caught.value.__cause__ is failure
    assert len(raw_metadata(env)) == 1
    assert env.cache.get(cache_request(PATHS[1])).state is CacheState.MISS


@pytest.mark.parametrize("options", [
    {"client": None}, {"cache": None}, {"raw_store": None}, {"ttl": -1},
    {"ttl": "10"}, {"ttl": timedelta(seconds=-1)}, {"timeout": None}, {"timeout": 0},
    {"timeout": -1}, {"timeout": True}, {"timeout": float("inf")},
    {"max_decompressed_bytes": 0}, {"max_decompressed_bytes": True},
    {"base_url": None}, {"base_url": ""}, {"base_url": "https://x.test/?key=secret"},
    {"base_url": "https://x.test/#fragment"}, {"base_url": "file:///tmp"}, {"clock": 1},
])
def test_invalid_constructor_options(env, options):
    with pytest.raises(FPLCacheValidationError):
        FPLCacheAdapter(**{**env.options, **options})
