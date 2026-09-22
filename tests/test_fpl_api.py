"""Official FPL contracts; real cache/raw stores, MockTransport, no live network."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from fpl_engine.data.http_cache import CacheRequest, CacheState, HttpCache, HttpCacheWriteError
from fpl_engine.data.providers.fpl_api import (
    DEFAULT_BASE_URL, FPLApiParseError, FPLApiRequestError, FPLApiResponseError,
    FPLApiStorageError, FPLApiValidationError, OfficialFPLAdapter,
)
from fpl_engine.data.raw_store import RawSnapshotExistsError, RawStore, RawStoreWriteError


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "fpl_api"
ENDPOINTS = [
    ("get_bootstrap_static", (), "bootstrap-static/", "bootstrap_static", None),
    ("get_fixtures", (), "fixtures/", "fixtures", None),
    ("get_fixtures", (5,), "fixtures/?event=5", "fixtures", "5"),
    ("get_element_summary", (123,), "element-summary/123/", "element_summary", "123"),
    ("get_event_live", (5,), "event/5/live/", "event_live", "5"),
]


@pytest.fixture
def env(tmp_path):
    state = SimpleNamespace(
        now=NOW, calls=[], status=200, error=None,
        body=(FIXTURES / "bootstrap_static.json").read_bytes(),
        headers={"Content-Type": "application/json", "ETag": '"v1"',
                 "Set-Cookie": "secret-cookie-value"},
    )
    def handle(request):
        state.calls.append(request)
        if state.error is not None:
            raise state.error
        return httpx.Response(state.status, content=state.body, headers=state.headers)
    # Even a client's redirect default is overridden by the public adapter.
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        state.cache = HttpCache(tmp_path / "cache", clock=lambda: state.now)
        state.raw = RawStore(tmp_path / "raw")
        state.options = dict(client=client, cache=state.cache, raw_store=state.raw,
                             ttl=timedelta(seconds=10), clock=lambda: state.now)
        state.adapter = OfficialFPLAdapter(**state.options)
        yield state


def raw_metadata(env):
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in env.raw.root.rglob("snapshot.metadata.json")]


def cache_request(endpoint="bootstrap-static/", params=None):
    return CacheRequest("official_fpl_api", "GET", DEFAULT_BASE_URL + endpoint, params=params)


@pytest.mark.parametrize("method,args,endpoint,entity,record_id", ENDPOINTS)
def test_endpoint_fetch_then_cached_read(env, monkeypatch, method, args, endpoint, entity, record_id):
    env.body = (FIXTURES / f"{entity}.json").read_bytes()
    store = Mock(wraps=env.raw.store_bytes)
    monkeypatch.setattr(env.raw, "store_bytes", store)
    first = getattr(env.adapter, method)(*args)
    second = getattr(env.adapter, method)(*args)
    assert first.payload == second.payload == json.loads(env.body)
    assert not first.from_cache and second.from_cache
    assert first.raw_snapshot is not None and second.raw_snapshot is None
    assert len(env.calls) == store.call_count == len(raw_metadata(env)) == 1
    assert str(env.calls[0].url) == DEFAULT_BASE_URL + endpoint
    assert env.calls[0].method == "GET"
    assert env.calls[0].extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 10.0)
    assert first.response.body == second.response.body == env.body
    assert first.response.checksum == hashlib.sha256(env.body).hexdigest()
    assert env.raw.read_bytes(first.raw_snapshot) == env.body
    metadata = raw_metadata(env)[0]
    assert metadata["source_provider"] == "official_fpl_api"
    assert metadata["source_url"] == DEFAULT_BASE_URL + endpoint
    assert metadata["source_record_id"] == record_id
    assert metadata["entity"] == entity
    assert datetime.fromisoformat(metadata["retrieved_at"]) == NOW
    assert first.raw_snapshot.retrieved_at.tzinfo is timezone.utc
    assert first.response.namespace == "official_fpl_api"
    assert "set-cookie" not in first.response.headers
    # The caller's client remains open; no adapter-owned lifecycle/authentication.
    assert not env.options["client"].is_closed
    assert "authorization" not in env.calls[0].headers


def test_extra_provider_fields_and_independent_payloads(env):
    first = env.adapter.get_bootstrap_static()
    assert first.payload["future_field"] == {"preserved": True}
    assert first.payload["elements"][0]["unknown_stat"] is None
    first.payload["elements"].clear()
    second = env.adapter.get_bootstrap_static()
    assert second.payload["elements"][0]["id"] == 123
    assert second.response.body == env.body
    assert len(env.calls) == 1


def test_exact_utf8_whitespace_is_preserved(env):
    env.body = ' [ { "name": "Łódź", "extra": null } ]\r\n'.encode("utf-8")
    result = env.adapter.get_fixtures()
    assert result.payload == [{"name": "Łódź", "extra": None}]
    assert env.raw.read_bytes(result.raw_snapshot) == result.response.body == env.body


def test_filtered_fixtures_have_distinct_cache_keys(env):
    keys = []
    for event in (None, 1, 38):
        env.now += timedelta(seconds=1)
        env.body = json.dumps([{"event": event}]).encode()
        result = env.adapter.get_fixtures(event=event)
        keys.append(result.response.cache_key)
        assert result.payload == [{"event": event}]
        assert env.adapter.get_fixtures(event=event).from_cache
    assert len(set(keys)) == len(env.calls) == len(raw_metadata(env)) == 3
    assert [dict(call.url.params) for call in env.calls] == [{}, {"event": "1"}, {"event": "38"}]


@pytest.mark.parametrize("method,identifiers,entity", [
    ("get_element_summary", (123, 456), "element_summary"),
    ("get_event_live", (5, 6), "event_live"),
    ("get_fixtures", (None, 5), "fixtures"),
    ("get_fixtures", (5, 6), "fixtures"),
])
def test_distinct_fpl_sources_with_identical_body_and_timestamp_coexist(env, method, identifiers, entity):
    env.body = (FIXTURES / f"{entity}.json").read_bytes()
    clock = Mock(return_value=NOW)
    adapter = OfficialFPLAdapter(**{**env.options, "clock": clock})
    first = getattr(adapter, method)(identifiers[0])
    first_paths = [env.raw.root / first.raw_snapshot.payload_path,
                   env.raw.root / first.raw_snapshot.metadata_path]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in first_paths]
    second = getattr(adapter, method)(identifiers[1])

    assert first.raw_snapshot.snapshot_id != second.raw_snapshot.snapshot_id
    assert first.response.cache_key != second.response.cache_key
    assert first.raw_snapshot.checksum == second.raw_snapshot.checksum == hashlib.sha256(env.body).hexdigest()
    for result, identifier, call in zip((first, second), identifiers, env.calls):
        snapshot = result.raw_snapshot
        assert snapshot.retrieved_at == NOW
        assert snapshot.source_provider == "official_fpl_api"
        assert snapshot.entity == entity
        assert snapshot.source_record_id == (None if identifier is None else str(identifier))
        assert snapshot.source_url == str(call.url)
        assert env.raw.read_bytes(snapshot) == result.response.body == env.body
        env.raw.verify_snapshot(snapshot)
        assert not result.from_cache
        assert getattr(adapter, method)(identifier).from_cache
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in first_paths] == before
    assert len(env.calls) == len(raw_metadata(env)) == clock.call_count == 2
    assert env.now == NOW


def test_stale_refresh_creates_new_evidence_even_for_identical_bytes(env):
    first = env.adapter.get_bootstrap_static()
    before = env.raw.read_bytes(first.raw_snapshot)
    env.now += timedelta(seconds=10)
    second = env.adapter.get_bootstrap_static()
    assert not second.from_cache
    assert len(env.calls) == len(raw_metadata(env)) == 2
    assert second.raw_snapshot.snapshot_id != first.raw_snapshot.snapshot_id
    assert second.raw_snapshot.retrieved_at == env.now
    assert env.raw.read_bytes(first.raw_snapshot) == before
    assert env.raw.read_bytes(second.raw_snapshot) == env.body
    assert env.adapter.get_bootstrap_static().from_cache
    assert len(env.calls) == 2


def test_immutable_policy_avoids_refresh(env):
    adapter = OfficialFPLAdapter(**{**env.options, "ttl": None})
    first = adapter.get_bootstrap_static()
    env.now += timedelta(days=3650)
    second = adapter.get_bootstrap_static()
    assert first.response.expires_at is None
    assert second.from_cache
    assert len(env.calls) == len(raw_metadata(env)) == 1


def test_zero_ttl_refreshes_with_new_retrieval_time(env):
    adapter = OfficialFPLAdapter(**{**env.options, "ttl": timedelta(0)})
    adapter.get_bootstrap_static()
    env.now += timedelta(microseconds=1)
    assert not adapter.get_bootstrap_static().from_cache
    assert len(env.calls) == len(raw_metadata(env)) == 2


def test_retrieval_clock_normalizes_utc_and_differs_from_cache_clock(env):
    retrieval = NOW.astimezone(timezone(timedelta(hours=3)))
    clock = Mock(return_value=retrieval)
    env.now += timedelta(seconds=2)
    adapter = OfficialFPLAdapter(**{**env.options, "clock": clock})
    result = adapter.get_bootstrap_static()
    assert result.raw_snapshot.retrieved_at == NOW
    assert result.raw_snapshot.retrieved_at.tzinfo is timezone.utc
    assert result.response.stored_at == env.now
    assert adapter.get_bootstrap_static().from_cache
    clock.assert_called_once_with()


@pytest.mark.parametrize("method,args,payload", [
    ("get_bootstrap_static", (), []),
    ("get_bootstrap_static", (), {"events": [], "elements": [], "teams": []}),
    ("get_bootstrap_static", (), {"elements": [], "teams": [], "element_types": []}),
    ("get_bootstrap_static", (), {"events": [], "teams": [], "element_types": []}),
    ("get_bootstrap_static", (), {"events": [], "elements": [], "element_types": []}),
    ("get_fixtures", (), {}), ("get_fixtures", (), None),
    ("get_element_summary", (123,), []),
    ("get_element_summary", (123,), {"history": [], "history_past": []}),
    ("get_element_summary", (123,), {"fixtures": [], "history_past": []}),
    ("get_element_summary", (123,), {"fixtures": [], "history": []}),
    ("get_event_live", (5,), []), ("get_event_live", (5,), {}),
    ("get_event_live", (5,), "wrong-root"),
])
def test_bad_shapes_fail_on_fetch_and_cache_read_but_keep_audit(env, method, args, payload):
    env.body = json.dumps(payload).encode()
    for _ in range(2):
        with pytest.raises(FPLApiResponseError, match="root"):
            getattr(env.adapter, method)(*args)
    assert len(env.calls) == len(raw_metadata(env)) == 1
    metadata = raw_metadata(env)[0]
    assert (env.raw.root / metadata["payload_path"]).read_bytes() == env.body


def test_root_validation_does_not_deeply_enforce_provider_fields(env):
    payload = {"events": None, "elements": {"new_shape": []}, "teams": [], "element_types": [], "added": 1}
    env.body = json.dumps(payload).encode()
    assert env.adapter.get_bootstrap_static().payload == payload


@pytest.mark.parametrize("body", [b"", b"<html>private-response-body</html>", b"{broken", b"\xff", b"[NaN]", b"[Infinity]"])
def test_invalid_json_is_preserved_but_never_returned(env, caplog, body):
    env.body = body
    with pytest.raises(FPLApiParseError) as caught:
        env.adapter.get_bootstrap_static()
    assert caught.value.__cause__ is not None
    assert "bootstrap-static/" in str(caught.value)
    assert "private-response-body" not in str(caught.value) + caplog.text
    assert len(raw_metadata(env)) == 1
    assert env.cache.get(cache_request()).response.body == body
    with pytest.raises(FPLApiParseError):
        env.adapter.get_bootstrap_static()
    assert len(env.calls) == len(raw_metadata(env)) == 1


@pytest.mark.parametrize("status", [200, 201, 206, 299])
def test_successful_status_is_preserved(env, status):
    env.status = status
    assert env.adapter.get_bootstrap_static().response.status_code == status
    assert len(raw_metadata(env)) == 1


@pytest.mark.parametrize("status", [204, 205])
def test_success_with_empty_body_keeps_evidence_and_fails_json(env, status):
    env.status, env.body = status, b""
    with pytest.raises(FPLApiParseError):
        env.adapter.get_bootstrap_static()
    assert len(raw_metadata(env)) == 1


@pytest.mark.parametrize("status", [100, 301, 302, 304, 400, 401, 404, 429, 500, 503])
def test_non_success_status_has_context_no_cache_and_no_raw(env, caplog, status):
    env.status = status
    env.headers["Location"] = "https://elsewhere.test/private"
    env.body = b"private-response-body"
    with pytest.raises(FPLApiResponseError) as caught:
        env.adapter.get_bootstrap_static()
    assert str(status) in str(caught.value) and "bootstrap-static/" in str(caught.value)
    assert "private-response-body" not in str(caught.value) + caplog.text
    assert "secret-cookie-value" not in str(caught.value) + caplog.text
    assert env.cache.get(cache_request()).state is CacheState.MISS
    assert not raw_metadata(env)
    assert len(env.calls) == 1  # No retries or redirects.


@pytest.mark.parametrize("error,match", [
    (httpx.ConnectError("private-transport-detail"), "transport failed"),
    (httpx.RemoteProtocolError("private-transport-detail"), "transport failed"),
    (httpx.ReadTimeout("private-transport-detail"), "timed out"),
    (httpx.ConnectTimeout("private-transport-detail"), "timed out"),
])
def test_transport_failure_is_chained_without_response_data(env, error, match):
    env.error = error
    with pytest.raises(FPLApiRequestError, match=match) as caught:
        env.adapter.get_bootstrap_static()
    assert caught.value.__cause__ is error
    assert "private-transport-detail" not in str(caught.value)
    assert "bootstrap-static/" in str(caught.value)
    assert len(env.calls) == 1
    assert not raw_metadata(env)
    assert env.cache.get(cache_request()).state is CacheState.MISS


@pytest.mark.parametrize("failure", ["status", "transport"])
def test_failed_refresh_preserves_previous_raw_and_stale_cache(env, failure):
    first = env.adapter.get_bootstrap_static()
    env.now += timedelta(seconds=10)
    if failure == "status":
        env.status = 503
    else:
        env.error = httpx.ReadTimeout("timeout")
    with pytest.raises((FPLApiRequestError, FPLApiResponseError)):
        env.adapter.get_bootstrap_static()
    assert len(env.calls) == 2 and len(raw_metadata(env)) == 1
    lookup = env.cache.get(cache_request())
    assert lookup.state is CacheState.HIT_STALE
    assert lookup.response.body == env.raw.read_bytes(first.raw_snapshot)


@pytest.mark.parametrize("player_id", [0, -1, "5", True, False, 1.0, None])
def test_invalid_provider_player_id_before_io(env, player_id):
    with pytest.raises(FPLApiValidationError, match="player_id"):
        env.adapter.get_element_summary(player_id)
    assert not env.calls and not raw_metadata(env)
    assert not env.cache.root.exists()


@pytest.mark.parametrize("gameweek", [0, -1, 39, "5", True, False, 1.0])
@pytest.mark.parametrize("method", ["get_fixtures", "get_event_live"])
def test_invalid_gw_before_io(env, gameweek, method):
    with pytest.raises(FPLApiValidationError):
        getattr(env.adapter, method)(gameweek)
    assert not env.calls and not raw_metadata(env)
    assert not env.cache.root.exists()


def test_none_is_not_an_event_live_gameweek(env):
    with pytest.raises(FPLApiValidationError):
        env.adapter.get_event_live(None)


@pytest.mark.parametrize("gameweek", [1, 38])
def test_valid_gameweek_boundaries(env, gameweek):
    env.body = (FIXTURES / "event_live.json").read_bytes()
    assert env.adapter.get_event_live(gameweek).payload["elements"]
    assert str(env.calls[0].url).endswith(f"event/{gameweek}/live/")


@pytest.mark.parametrize("base_url", ["https://example.test/custom/api", "https://example.test/custom/api/"])
def test_injected_base_url_and_timeout(env, base_url):
    adapter = OfficialFPLAdapter(**{**env.options, "base_url": base_url, "timeout": 2.5})
    result = adapter.get_bootstrap_static()
    assert str(env.calls[0].url) == "https://example.test/custom/api/bootstrap-static/"
    assert result.raw_snapshot.source_url == str(env.calls[0].url)
    assert set(env.calls[0].extensions["timeout"].values()) == {2.5}
    assert env.cache.get(cache_request()).state is CacheState.MISS


@pytest.mark.parametrize("options", [
    {"client": None}, {"cache": None}, {"raw_store": None},
    {"ttl": -1}, {"ttl": "10"}, {"ttl": timedelta(seconds=-1)},
    {"timeout": None}, {"timeout": 0}, {"timeout": -1}, {"timeout": True},
    {"timeout": float("inf")}, {"timeout": float("nan")},
    {"clock": 1}, {"base_url": None}, {"base_url": ""},
    {"base_url": "https://example.test/api?key=secret"},
    {"base_url": "https://example.test/api#fragment"},
    {"base_url": "https://user:secret@example.test/api/"},
    {"base_url": "file:///tmp/"}, {"base_url": "/api/"},
])
def test_invalid_constructor_arguments_before_io(env, options):
    with pytest.raises(FPLApiValidationError):
        OfficialFPLAdapter(**{**env.options, **options})
    assert not env.calls and not raw_metadata(env)


@pytest.mark.parametrize("now", [datetime(2026, 9, 7), None, "now"])
def test_invalid_retrieval_clock_is_explicit(env, now):
    adapter = OfficialFPLAdapter(**{**env.options, "clock": lambda: now})
    with pytest.raises(FPLApiValidationError, match="aware"):
        adapter.get_bootstrap_static()
    assert not raw_metadata(env)
    assert env.cache.get(cache_request()).state is CacheState.MISS


def test_raw_write_failure_prevents_cache_publication(env, monkeypatch):
    failure = RawStoreWriteError("disk failure")
    monkeypatch.setattr(env.raw, "store_bytes", Mock(side_effect=failure))
    with pytest.raises(FPLApiStorageError) as caught:
        env.adapter.get_bootstrap_static()
    assert caught.value.__cause__ is failure
    assert len(env.calls) == 1
    assert env.cache.get(cache_request()).state is CacheState.MISS


def test_cache_write_failure_leaves_raw_evidence(env, monkeypatch):
    failure = HttpCacheWriteError("disk failure")
    monkeypatch.setattr(env.cache, "put", Mock(side_effect=failure))
    with pytest.raises(FPLApiStorageError) as caught:
        env.adapter.get_bootstrap_static()
    assert caught.value.__cause__ is failure
    assert len(env.calls) == len(raw_metadata(env)) == 1
    assert env.cache.get(cache_request()).state is CacheState.MISS


def test_existing_raw_collision_is_not_overwritten_or_retimestamped(env):
    adapter = OfficialFPLAdapter(**{**env.options, "ttl": timedelta(0)})
    first = adapter.get_bootstrap_static()
    with pytest.raises(FPLApiStorageError) as caught:
        adapter.get_bootstrap_static()
    assert isinstance(caught.value.__cause__, RawSnapshotExistsError)
    assert len(env.calls) == 2 and len(raw_metadata(env)) == 1
    assert env.raw.read_bytes(first.raw_snapshot) == env.body
    assert env.cache.get(cache_request()).response.stored_at == NOW


def test_corrupt_cache_fails_before_network_or_raw_write(env):
    first = env.adapter.get_bootstrap_static()
    key = first.response.cache_key
    (env.cache.root / "official_fpl_api" / key[:2] / f"{key}.zip").write_bytes(b"broken")
    with pytest.raises(FPLApiStorageError):
        env.adapter.get_bootstrap_static()
    assert len(env.calls) == len(raw_metadata(env)) == 1
