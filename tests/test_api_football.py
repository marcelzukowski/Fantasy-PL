"""DATA-006 API-Football adapter tests use only httpx.MockTransport."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fpl_engine.data.http_cache import CacheRequest, CacheState, HttpCache
from fpl_engine.data.providers.api_football import (
    APIFootballAdapter, APIFootballParseError, APIFootballQuota,
    APIFootballQuotaExceededError, APIFootballRequestError, APIFootballResponseError,
    APIFootballValidationError, DEFAULT_BASE_URL,
)
from fpl_engine.data.raw_store import RawStore


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
KEY = "very-private-api-key"


def envelope(*, response=None, errors=None, paging=None, **extra):
    return {
        "get": "fixtures", "parameters": {"league": "39"}, "errors": errors or {},
        "results": len(response or []), "paging": paging or {"current": 1, "total": 1},
        "response": response or [{"fixture": {"id": 123}, "unknown_provider_field": {"kept": True}}],
        **extra,
    }


@pytest.fixture
def env(tmp_path):
    state = SimpleNamespace(now=NOW, calls=[], status=200, headers={
        "x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "79",
        "x-ratelimit-requests-reset": "tomorrow", "Set-Cookie": "private",
    }, body=json.dumps(envelope(), separators=(",", ":")).encode())

    def handle(request):
        state.calls.append(request)
        return httpx.Response(state.status, content=state.body, headers=state.headers)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        state.cache = HttpCache(tmp_path / "cache", clock=lambda: state.now)
        state.raw = RawStore(tmp_path / "raw")
        state.quota = APIFootballQuota(80, clock=lambda: state.now)
        state.options = dict(client=client, api_key=KEY, cache=state.cache, raw_store=state.raw,
                             quota=state.quota, ttl=timedelta(minutes=5), clock=lambda: state.now)
        state.adapter = APIFootballAdapter(**state.options)
        yield state


def metadata(env):
    return [path.read_text(encoding="utf-8") for path in env.raw.root.rglob("snapshot.metadata.json")]


@pytest.mark.parametrize("call,path,query", [
    (lambda a: a.get_fixtures(league=39, season=2025, team=42), "/fixtures", "league=39&season=2025&team=42"),
    (lambda a: a.get_fixture_statistics(123), "/fixtures/statistics", "fixture=123"),
    (lambda a: a.get_lineups(123), "/fixtures/lineups", "fixture=123"),
    (lambda a: a.get_injuries(league=39, season=2025, team=42), "/injuries", "league=39&season=2025&team=42"),
    (lambda a: a.get_sidelined(9), "/sidelined", "player=9"),
    (lambda a: a.get_transfers(9), "/transfers", "player=9"),
    (lambda a: a.get_coaches(42), "/coachs", "team=42"),
    (lambda a: a.get_player_statistics(league=39, season=2025), "/players", "league=39&season=2025&page=1"),
    (lambda a: a.get_player_statistics(league=39, season=2025, team=42), "/players", "league=39&season=2025&team=42&page=1"),
])
def test_required_endpoint_urls_parameters_and_authentication(env, call, path, query):
    result = call(env.adapter)
    request = env.calls[-1]
    assert request.url.path == path and str(request.url.query, "ascii") == query
    assert request.headers["x-apisports-key"] == KEY
    assert result.payload[0]["unknown_provider_field"] == {"kept": True}
    assert result.rate_limit.limit == 100 and result.rate_limit.remaining == 79
    assert result.rate_limit.reset == "tomorrow"


def test_exact_bytes_cache_hit_raw_evidence_and_secret_redaction(env):
    first = env.adapter.get_lineups(123)
    second = env.adapter.get_lineups(123)
    assert len(env.calls) == 1 and not first.from_cache and second.from_cache
    assert first.raw_snapshot is not None and second.raw_snapshot is None
    assert env.raw.read_bytes(first.raw_snapshot) == env.body == first.response.body
    assert env.adapter.quota_status.requests_used == 1
    all_persisted = "\n".join(metadata(env) + [
        path.read_text(encoding="utf-8", errors="ignore")
        for path in env.cache.root.rglob("*.zip")
    ])
    assert KEY not in all_persisted
    assert "x-apisports-key" not in all_persisted.lower()
    assert first.raw_snapshot.source_url == f"{DEFAULT_BASE_URL}/fixtures/lineups?fixture=123"


def test_http_error_does_not_store_raw_or_cache_but_counts_network_request(env):
    env.status, env.body = 429, b"private provider detail"
    with pytest.raises(APIFootballResponseError, match="429") as caught:
        env.adapter.get_sidelined(9)
    assert "private provider detail" not in str(caught.value)
    assert env.adapter.quota_status.requests_used == 1
    assert not metadata(env)
    assert env.cache.get(CacheRequest("api_football", "GET", f"{DEFAULT_BASE_URL}/sidelined", params={"player": 9})).state is CacheState.MISS


def test_api_level_error_in_http_200_is_raw_auditable_and_secret_free(env):
    env.body = json.dumps(envelope(errors={"token": "denied"})).encode()
    with pytest.raises(APIFootballResponseError, match="reported an error") as caught:
        env.adapter.get_transfers(9)
    assert KEY not in str(caught.value)
    assert len(env.calls) == len(metadata(env)) == 1
    with pytest.raises(APIFootballResponseError):
        env.adapter.get_transfers(9)
    assert len(env.calls) == 1


def test_pagination_fetches_only_provider_declared_pages(env):
    def handle(request):
        env.calls.append(request)
        page = int(request.url.params["page"])
        body = envelope(response=[{"page": page}], paging={"current": page, "total": 2})
        return httpx.Response(200, content=json.dumps(body).encode())
    env.options["client"] = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = APIFootballAdapter(**env.options)
    result = adapter.get_all_player_statistics(league=39, season=2025, team=42)
    assert [item["page"] for item in result.payload] == [1, 2]
    assert [str(request.url.params["page"]) for request in env.calls] == ["1", "2"]
    assert adapter.quota_status.requests_used == 2
    env.options["client"].close()


def test_local_quota_blocks_network_only_when_cache_cannot_satisfy_request(env):
    env.options["quota"] = APIFootballQuota(1, clock=lambda: env.now)
    adapter = APIFootballAdapter(**env.options)
    adapter.get_lineups(123)
    adapter.get_lineups(123)
    with pytest.raises(APIFootballQuotaExceededError):
        adapter.get_sidelined(9)
    assert len(env.calls) == 1 and adapter.quota_status.requests_used == 1


@pytest.mark.parametrize("method,args", [
    ("get_fixture_statistics", (True,)), ("get_lineups", (0,)), ("get_sidelined", ("9",)),
    ("get_transfers", (-1,)), ("get_coaches", (None,)),
])
def test_strict_provider_id_validation_happens_before_http(env, method, args):
    with pytest.raises(APIFootballValidationError):
        getattr(env.adapter, method)(*args)
    assert not env.calls


@pytest.mark.parametrize("kwargs", [
    {"league": True, "season": 2025}, {"league": 39, "season": "2025"},
    {"league": 39, "season": 2025, "page": 0},
])
def test_player_statistics_requires_strict_ids(env, kwargs):
    with pytest.raises(APIFootballValidationError):
        env.adapter.get_player_statistics(**kwargs)
    assert not env.calls


def test_transport_clock_and_bad_envelope_fail_explicitly(env):
    env.body = b'{"get":"fixtures"}'
    with pytest.raises(APIFootballParseError):
        env.adapter.get_fixtures(league=39, season=2025)
    assert len(metadata(env)) == 1
    bad = APIFootballAdapter(**{**env.options, "clock": lambda: datetime(2026, 1, 1)})
    with pytest.raises(APIFootballValidationError, match="aware"):
        bad.get_lineups(555)


def test_request_errors_are_chained_without_provider_detail_or_key(env):
    def fail(_request):
        raise httpx.ConnectError("secret transport detail")
    env.options["client"] = httpx.Client(transport=httpx.MockTransport(fail))
    adapter = APIFootballAdapter(**env.options)
    with pytest.raises(APIFootballRequestError) as caught:
        adapter.get_sidelined(9)
    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert KEY not in str(caught.value) and "secret transport detail" not in str(caught.value)
    env.options["client"].close()
