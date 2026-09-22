"""DATA-004 Vaastav adapter tests with local CSV fixtures and MockTransport only."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pandas as pd
import pytest

from fpl_engine.data.http_cache import CacheRequest, CacheState, HttpCache, HttpCacheWriteError
from fpl_engine.data.providers.vaastav import (
    DEFAULT_BASE_URL, VaastavAdapter, VaastavParseError, VaastavRequestError,
    VaastavResponseError, VaastavStorageError, VaastavValidationError,
)
from fpl_engine.data.raw_store import RawStore, RawStoreWriteError


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "vaastav"
REF = "0123456789abcdef0123456789abcdef01234567"
SEASON = "2024-25"


@pytest.fixture
def env(tmp_path):
    state = SimpleNamespace(
        now=NOW, calls=[], status=200, error=None,
        body=(FIXTURES / "merged_gameweeks.csv").read_bytes(),
        headers={"Content-Type": "text/csv", "ETag": '"v1"', "Set-Cookie": "private-cookie"},
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
                             repository_ref=REF, ttl=timedelta(seconds=10), clock=lambda: state.now)
        state.adapter = VaastavAdapter(**state.options)
        yield state


def raw_metadata(env):
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in env.raw.root.rglob("snapshot.metadata.json")]


def url(ref=REF, season=SEASON, filename="merged_gw.csv"):
    return f"{DEFAULT_BASE_URL}/{ref}/data/{season}/gws/{filename}"


def request(ref=REF, season=SEASON, filename="merged_gw.csv"):
    return CacheRequest("vaastav", "GET", url(ref, season, filename))


def test_merged_end_to_end_fetch_raw_cache_and_dataframe(env, monkeypatch):
    store = Mock(wraps=env.raw.store_bytes)
    monkeypatch.setattr(env.raw, "store_bytes", store)
    first = env.adapter.get_merged_gameweeks(SEASON)
    second = env.adapter.get_merged_gameweeks(SEASON)

    assert len(env.calls) == store.call_count == len(raw_metadata(env)) == 1
    assert str(env.calls[0].url) == url()
    assert env.calls[0].method == "GET"
    assert env.calls[0].extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 10.0)
    assert not first.from_cache and second.from_cache
    assert first.raw_snapshot is not None and second.raw_snapshot is None
    assert first.data.equals(second.data)
    assert list(first.data.columns) == ["name", "position", "team", "GW", "element", "fixture", "total_points", "xP", "unknown_new_column"]
    assert len(first.data) == 2
    assert first.data.loc[0, "name"] == "Łukasz Example"
    assert first.data.loc[0, "unknown_new_column"] == "retained"
    assert "xP" in first.data.columns and first.unsafe_columns == frozenset({"xP"})
    assert "xP" not in first.safe_feature_columns
    assert "total_points" in first.safe_feature_columns
    assert first.repository_ref == REF and first.season == SEASON
    assert first.dataset_name == "merged_gameweeks" and first.gameweek is None
    assert first.source_url == url()
    assert first.retrieved_at == NOW and first.retrieved_at.tzinfo is timezone.utc
    assert first.response.body == env.body
    assert env.raw.read_bytes(first.raw_snapshot) == env.body
    metadata = raw_metadata(env)[0]
    assert metadata["source_provider"] == "vaastav"
    assert metadata["entity"] == "merged_gameweeks"
    assert metadata["source_url"] == url()
    assert metadata["source_record_id"] == f"{REF}:{SEASON}:merged_gw"
    assert metadata["retrieved_at"] == "2026-09-07T12:00:00Z"
    assert first.response.checksum == hashlib.sha256(env.body).hexdigest()
    assert "set-cookie" not in first.response.headers
    assert not env.options["client"].is_closed


@pytest.mark.parametrize("gameweek", [1, 38])
def test_gameweek_url_metadata_and_boundaries(env, gameweek):
    env.body = (FIXTURES / "gameweek_1.csv").read_bytes()
    if gameweek == 38:
        env.body = env.body.replace(b",1,123,456,", b",38,123,456,")
    result = env.adapter.get_gameweek(SEASON, gameweek)
    assert str(env.calls[0].url) == url(filename=f"gw{gameweek}.csv")
    assert result.dataset_name == "gameweek" and result.gameweek == gameweek
    assert result.raw_snapshot.source_record_id == f"{REF}:{SEASON}:gw:{gameweek}"
    assert result.raw_snapshot.source_url == str(env.calls[0].url)
    assert result.data["GW"].eq(gameweek).all()


def test_version_pinned_fixture_schedule_uses_root_season_path_and_exact_raw_bytes(env):
    env.body = b"id,event,kickoff_time,team_h,team_a,unknown\n1,1,2024-08-16T19:00:00Z,1,2,kept\n"
    result = env.adapter.get_fixture_schedule(SEASON)
    expected = f"{DEFAULT_BASE_URL}/{REF}/data/{SEASON}/fixtures.csv"
    assert str(env.calls[0].url) == expected
    assert result.dataset_name == "fixture_schedule" and result.gameweek is None
    assert result.source_url == expected
    assert result.raw_snapshot.source_record_id == f"{REF}:{SEASON}:fixtures"
    assert env.raw.read_bytes(result.raw_snapshot) == env.body
    assert result.data.loc[0, "unknown"] == "kept"


@pytest.mark.parametrize("season", ["2016-17", "2024-25", "2099-00"])
def test_valid_seasons_are_syntactically_accepted(env, season):
    result = env.adapter.get_merged_gameweeks(season)
    assert result.season == season
    assert f"/data/{season}/" in str(env.calls[0].url)


@pytest.mark.parametrize("season", ["", "2026", "26-27", "2026/27", "2026-28", "2024-24", "2024-225", "../foo", "2024-25/../x", " 2024-25", 2024, None])
def test_invalid_season_is_rejected_before_io(env, season):
    with pytest.raises(VaastavValidationError, match="season"):
        env.adapter.get_merged_gameweeks(season)
    assert not env.calls and not raw_metadata(env) and not env.cache.root.exists()


@pytest.mark.parametrize("gameweek", [0, -1, 39, "5", 5.0, True, False, None])
def test_invalid_gameweek_is_rejected_before_io(env, gameweek):
    with pytest.raises(VaastavValidationError, match="gameweek"):
        env.adapter.get_gameweek(SEASON, gameweek)
    assert not env.calls and not raw_metadata(env) and not env.cache.root.exists()


def test_ref_changes_url_cache_identity_and_result_metadata(env):
    second_ref = "release/2024-25"
    first = env.adapter.get_merged_gameweeks(SEASON)
    env.now += timedelta(seconds=1)
    second = VaastavAdapter(**{**env.options, "repository_ref": second_ref}).get_merged_gameweeks(SEASON)
    assert first.repository_ref == REF and second.repository_ref == second_ref
    assert first.response.cache_key != second.response.cache_key
    assert str(env.calls[0].url) == url()
    assert str(env.calls[1].url) == url(ref=second_ref)
    assert len(raw_metadata(env)) == 2


@pytest.mark.parametrize("ref", ["master", "v1.2.3", REF, "release/2024-25"])
def test_permitted_refs_are_retained_verbatim(env, ref):
    result = VaastavAdapter(**{**env.options, "repository_ref": ref}).get_merged_gameweeks(SEASON)
    assert result.repository_ref == ref and f"/{ref}/data/" in result.source_url


@pytest.mark.parametrize("ref", ["", ".", "..", "../master", "refs/../master", "/master", "master/", "master//x", "master\\x", "master x", "master?x", "master#x", "CON", 1, None])
def test_unsafe_ref_rejected_at_construction(env, ref):
    with pytest.raises(VaastavValidationError, match="ref"):
        VaastavAdapter(**{**env.options, "repository_ref": ref})
    assert not env.calls


def test_dataset_without_xp_retains_columns_and_does_not_invent_metadata(env):
    env.body = (FIXTURES / "gameweek_without_xp.csv").read_bytes()
    result = env.adapter.get_gameweek(SEASON, 2)
    assert list(result.data.columns) == ["name", "round", "element", "fixture", "total_points"]
    assert "xP" not in result.columns and not result.unsafe_columns
    assert result.safe_feature_columns == result.columns
    assert result.data.loc[0, "round"] == 2


def test_present_gw_mismatch_fails_without_rewriting_raw_or_cache(env):
    env.body = (FIXTURES / "gameweek_1.csv").read_bytes()
    with pytest.raises(VaastavResponseError, match="does not match"):
        env.adapter.get_gameweek(SEASON, 2)
    assert len(env.calls) == len(raw_metadata(env)) == 1
    assert env.cache.get(request(filename="gw2.csv")).state is CacheState.HIT_FRESH
    with pytest.raises(VaastavResponseError):
        env.adapter.get_gameweek(SEASON, 2)
    assert len(env.calls) == len(raw_metadata(env)) == 1


def test_headers_only_csv_is_valid_structural_empty_dataset(env):
    env.body = b"element,fixture,xP\n"
    result = env.adapter.get_merged_gameweeks(SEASON)
    assert result.data.empty
    assert result.columns == ("element", "fixture", "xP")
    assert result.unsafe_columns == frozenset({"xP"})
    assert len(raw_metadata(env)) == 1


@pytest.mark.parametrize("body", [b"", b"\xff", b"\xef\xbb\xbf", b",,\n", b"a,a\n1,2\n", b"a,b\n1,2,3\n", b'"unclosed,a\n'])
def test_empty_or_malformed_csv_is_preserved_but_not_returned(env, caplog, body):
    env.body = body
    with pytest.raises(VaastavParseError) as caught:
        env.adapter.get_merged_gameweeks(SEASON)
    assert "private" not in str(caught.value) + caplog.text
    assert len(raw_metadata(env)) == 1
    assert env.cache.get(request()).response.body == body
    with pytest.raises(VaastavParseError):
        env.adapter.get_merged_gameweeks(SEASON)
    assert len(env.calls) == len(raw_metadata(env)) == 1


@pytest.mark.parametrize("status", [100, 301, 304, 400, 404, 429, 500, 503])
def test_non_success_is_not_cached_or_stored_and_has_context(env, caplog, status):
    env.status, env.body = status, b"private response body"
    with pytest.raises(VaastavResponseError) as caught:
        env.adapter.get_gameweek(SEASON, 5)
    assert str(status) in str(caught.value)
    assert SEASON in str(caught.value) and "gw5.csv" in str(caught.value)
    assert "private response body" not in str(caught.value) + caplog.text
    assert not raw_metadata(env)
    assert env.cache.get(request(filename="gw5.csv")).state is CacheState.MISS
    assert len(env.calls) == 1


@pytest.mark.parametrize("error,match", [
    (httpx.ConnectError("private transport detail"), "transport failed"),
    (httpx.ReadTimeout("private timeout detail"), "timed out"),
    (httpx.ConnectTimeout("private timeout detail"), "timed out"),
])
def test_transport_failures_are_chained_and_not_cached(env, error, match):
    env.error = error
    with pytest.raises(VaastavRequestError, match=match) as caught:
        env.adapter.get_merged_gameweeks(SEASON)
    assert caught.value.__cause__ is error
    assert "private transport detail" not in str(caught.value)
    assert not raw_metadata(env) and env.cache.get(request()).state is CacheState.MISS


def test_stale_refresh_creates_new_raw_snapshot(env):
    first = env.adapter.get_merged_gameweeks(SEASON)
    env.now += timedelta(seconds=10)
    second = env.adapter.get_merged_gameweeks(SEASON)
    assert not second.from_cache
    assert second.raw_snapshot.snapshot_id != first.raw_snapshot.snapshot_id
    assert len(env.calls) == len(raw_metadata(env)) == 2
    assert env.raw.read_bytes(first.raw_snapshot) == env.raw.read_bytes(second.raw_snapshot) == env.body


def test_immutable_commit_policy_stays_cached(env):
    adapter = VaastavAdapter(**{**env.options, "ttl": None})
    first = adapter.get_merged_gameweeks(SEASON)
    env.now += timedelta(days=3650)
    second = adapter.get_merged_gameweeks(SEASON)
    assert first.response.expires_at is None and second.from_cache
    assert len(env.calls) == len(raw_metadata(env)) == 1


def test_cache_and_raw_write_failures_have_correct_ordering(env, monkeypatch):
    raw_failure = RawStoreWriteError("disk failure")
    monkeypatch.setattr(env.raw, "store_bytes", Mock(side_effect=raw_failure))
    with pytest.raises(VaastavStorageError) as caught:
        env.adapter.get_merged_gameweeks(SEASON)
    assert caught.value.__cause__ is raw_failure
    assert env.cache.get(request()).state is CacheState.MISS

    monkeypatch.undo()
    cache_failure = HttpCacheWriteError("disk failure")
    monkeypatch.setattr(env.cache, "put", Mock(side_effect=cache_failure))
    with pytest.raises(VaastavStorageError) as caught:
        env.adapter.get_merged_gameweeks(SEASON)
    assert caught.value.__cause__ is cache_failure
    assert len(raw_metadata(env)) == 1
    assert env.cache.get(request()).state is CacheState.MISS


def test_injected_clock_uses_utc_retrieval_time(env):
    clock = Mock(return_value=NOW.astimezone(timezone(timedelta(hours=3))))
    env.now += timedelta(seconds=2)
    result = VaastavAdapter(**{**env.options, "clock": clock}).get_merged_gameweeks(SEASON)
    assert result.raw_snapshot.retrieved_at == NOW
    assert result.retrieved_at == NOW
    assert result.response.stored_at == env.now
    clock.assert_called_once_with()


@pytest.mark.parametrize("now", [datetime(2026, 9, 7), None, "now"])
def test_invalid_retrieval_clock_is_explicit_before_raw_cache_write(env, now):
    adapter = VaastavAdapter(**{**env.options, "clock": lambda: now})
    with pytest.raises(VaastavValidationError, match="aware"):
        adapter.get_merged_gameweeks(SEASON)
    assert not raw_metadata(env) and env.cache.get(request()).state is CacheState.MISS


@pytest.mark.parametrize("options", [
    {"client": None}, {"cache": None}, {"raw_store": None},
    {"ttl": -1}, {"ttl": "10"}, {"ttl": timedelta(seconds=-1)},
    {"timeout": None}, {"timeout": 0}, {"timeout": -1}, {"timeout": True},
    {"timeout": float("inf")}, {"timeout": float("nan")}, {"clock": 1},
    {"base_url": None}, {"base_url": ""}, {"base_url": "https://example.test/api?x=1"},
    {"base_url": "https://example.test/api#fragment"}, {"base_url": "file:///tmp"},
])
def test_invalid_constructor_options_fail_before_io(env, options):
    with pytest.raises(VaastavValidationError):
        VaastavAdapter(**{**env.options, **options})
    assert not env.calls


def test_injected_base_url_and_no_redirects(env):
    adapter = VaastavAdapter(**{**env.options, "base_url": "https://example.test/raw/", "timeout": 2.5})
    result = adapter.get_merged_gameweeks(SEASON)
    assert str(env.calls[0].url) == f"https://example.test/raw/{REF}/data/{SEASON}/gws/merged_gw.csv"
    assert result.source_url == str(env.calls[0].url)
    assert set(env.calls[0].extensions["timeout"].values()) == {2.5}
    assert env.cache.get(request()).state is CacheState.MISS
