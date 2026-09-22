"""DATA-002 contracts using temporary storage, fake fetchers and explicit clocks."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from threading import Barrier
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from fpl_engine.data import http_cache
from fpl_engine.data.http_cache import (
    CacheRequest, CacheState, CachedHttpResponse, HttpCache, HttpCacheIntegrityError,
    HttpCacheReadError, HttpCacheValidationError, HttpCacheWriteError, HttpResponse,
)
from fpl_engine.data.raw_store import RawStore


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cache(tmp_path, clock):
    return HttpCache(tmp_path / "http", clock=clock)


def request(**kwargs):
    return CacheRequest(**{
        "namespace": "example_provider", "method": "GET",
        "url": "https://example.test/items", **kwargs,
    })


def response(body=b"exact\x00\xff\r\n { \"a\": 1 } ", status=200, headers=None):
    return HttpResponse(status_code=status, body=body, headers=headers or {})


def entry_path(cache, req):
    return cache.root / req.namespace / req.cache_key[:2] / f"{req.cache_key}.zip"


def read_entry(cache, req):
    with ZipFile(entry_path(cache, req)) as archive:
        return json.loads(archive.read("cache.metadata.json")), archive.read("response.bin")


def rewrite_entry(cache, req, *, change_metadata=None, body=None, compression=ZIP_STORED):
    metadata, old_body = read_entry(cache, req)
    if change_metadata:
        change_metadata(metadata)
    with ZipFile(entry_path(cache, req), "w", compression=compression) as archive:
        archive.writestr("cache.metadata.json", json.dumps(metadata))
        archive.writestr("response.bin", old_body if body is None else body)


def test_equivalent_query_and_method_identities():
    identities = [
        request(url="https://example.test/items?a=1&b=2"),
        request(method="get", url="https://example.test/items?b=2&a=1"),
        request(params={"b": 2, "a": 1}),
        request(params={"a": "1", "b": "2"}),
        request(url="https://example.test/items?b=2", params={"a": 1}),
    ]
    assert len({item.cache_key for item in identities}) == 1
    assert all(item.redacted_url.endswith("?a=1&b=2") for item in identities)
    assert len(identities[0].cache_key) == 64


@pytest.mark.parametrize("changes", [
    {"url": "https://example.test/other"}, {"method": "POST"}, {"body": b"x"},
    {"namespace": "another_provider"}, {"params": {"a": 2}},
    {"vary": {"account_scope": "private"}},
    {"url": "http://example.test/items"}, {"url": "https://example.test/Items"},
    {"url": "https://example.test:443/items"},
    {"url": "https://example.test/items/"},
])
def test_meaningful_changes_change_key(changes):
    assert request(**changes).cache_key != request().cache_key


def test_json_and_vary_are_deterministic_and_copied():
    body = {"z": [1, None, True, 1.5], "a": {"b": "Łódź"}}
    vary = {"language": "pl", "account_scope": "public"}
    req = request(body=body, vary=vary)
    key = req.cache_key
    assert key == request(body={"a": {"b": "Łódź"}, "z": [1, None, True, 1.5]},
                          vary=dict(reversed(list(vary.items())))).cache_key
    assert body == {"z": [1, None, True, 1.5], "a": {"b": "Łódź"}}
    body["z"].append(2)
    vary["language"] = "en"
    assert req.cache_key == key
    assert request(body=body, vary=vary).cache_key != key


def test_body_types_remain_distinct():
    bodies = [None, b"", "", b"hello", "hello", {}, [], False, 0]
    assert len({request(body=body).cache_key for body in bodies}) == len(bodies)


def test_query_utf8_repeated_names_and_blank_values():
    first = request(url="https://example.test/items?z=3&a=1&a=2&blank=&city=%C5%81%C3%B3d%C5%BA")
    equivalent = request(params=[("city", "Łódź"), ("a", 1), ("blank", ""), ("a", 2), ("z", 3)])
    assert first.cache_key == equivalent.cache_key
    assert request(params=[("a", 1), ("a", 2)]).cache_key != request(params=[("a", 2), ("a", 1)]).cache_key
    assert request(params={"blank": ""}).cache_key != request().cache_key
    assert request(params={"q": "a b"}).cache_key == request(url="https://example.test/items?q=a+b").cache_key
    assert request(params={"q": "a+b"}).cache_key != request(params={"q": "a b"}).cache_key


def test_credentials_affect_hash_but_never_metadata_or_logs(cache, caplog):
    secrets = ["url-secret-ABC", "param-secret-DEF", "Bearer auth-GHI", "api-key-JKL", "cookie-MNO", "body-secret-PQR"]
    req = request(url=f"https://example.test/items?token={secrets[0]}&a=1",
                  params={"api_key": secrets[1]}, body={"password": secrets[5]},
                  vary={"account_scope": "public"}, sensitive_params=("token", "api_key"))
    other = request(url="https://example.test/items?token=other&a=1",
                    params={"api_key": secrets[1]}, body={"password": secrets[5]},
                    vary={"account_scope": "public"}, sensitive_params=("token", "api_key"))
    assert req.cache_key != other.cache_key
    raw_headers = {"Authorization": secrets[2], "X-ApiSports-Key": secrets[3],
                   "Set-Cookie": secrets[4], "Cookie": secrets[4], "ETag": "safe-version"}
    cache.put(req, response(headers=raw_headers), ttl=None)
    metadata, _ = read_entry(cache, req)
    assert metadata["headers"] == {"etag": "safe-version"}
    query = parse_qs(urlsplit(metadata["request_url"]).query)
    assert query == {"a": ["1"], "api_key": ["[REDACTED]"], "token": ["[REDACTED]"]}
    assert cache.get(req).state is CacheState.HIT_FRESH
    for secret in secrets:
        assert secret not in json.dumps(metadata)
        assert secret not in repr(req)
        assert secret not in caplog.text
        assert secret.encode() not in entry_path(cache, req).read_bytes()
        assert not any(secret in str(path) for path in cache.root.rglob("*"))
    assert raw_headers["Authorization"] == secrets[2]


def test_redaction_does_not_change_key_and_is_caller_controlled():
    normal = request(params={"key": "not-necessarily-secret"})
    redacted = request(params={"key": "not-necessarily-secret"}, sensitive_params=("key",))
    assert normal.cache_key == redacted.cache_key
    assert "not-necessarily-secret" in normal.redacted_url
    assert "not-necessarily-secret" not in redacted.redacted_url
    with pytest.raises(TypeError):
        request(headers={"Authorization": "Bearer private"})


@pytest.mark.parametrize("body", [b"", bytes(range(256)), b'{ "b": 2,\r\n "a": 1 }\n', "Łódź".encode("utf-16")])
def test_exact_storage_metadata_and_reload(cache, clock, body):
    req = request()
    clock.now = NOW.astimezone(timezone(timedelta(hours=2)))
    original = response(body, status=206, headers={"Content-Type": "application/octet-stream",
                                                "ETag": '"v1"', "Last-Modified": "safe-date",
                                                "Cache-Control": "max-age=999"})
    stored = cache.put(req, original, ttl=timedelta(seconds=5))
    assert isinstance(stored, CachedHttpResponse)
    assert not stored.from_cache
    metadata, payload = read_entry(cache, req)
    assert payload == body
    assert stored.checksum == metadata["body_checksum"] == hashlib.sha256(body).hexdigest()
    assert stored.content_length == metadata["content_length"] == len(body)
    assert metadata["metadata_version"] == 1
    assert metadata["cache_key"] == metadata["request_fingerprint"] == req.cache_key
    assert metadata["namespace"] == req.namespace
    assert metadata["request_method"] == "GET"
    assert metadata["request_url"] == req.redacted_url
    assert metadata["checksum_algorithm"] == "sha256"
    assert metadata["payload_path"] == "response.bin"
    assert not Path(metadata["payload_path"]).is_absolute()
    assert datetime.fromisoformat(metadata["stored_at"]) == NOW
    assert stored.stored_at.tzinfo is timezone.utc
    assert stored.expires_at == NOW + timedelta(seconds=5)
    assert set(metadata["headers"]) == {"content-type", "etag", "last-modified", "cache-control"}
    loaded = HttpCache(cache.root, clock=clock).get(req)
    assert loaded.state is CacheState.HIT_FRESH
    assert loaded.response.body == body
    assert loaded.response.status_code == 206
    assert loaded.response.from_cache
    with ZipFile(entry_path(cache, req)) as archive:
        assert all(info.compress_type == ZIP_STORED for info in archive.infolist())
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_response_and_request_are_deeply_immutable(cache):
    headers = {"ETag": "old"}
    original = response(headers=headers)
    headers["ETag"] = "new"
    req = request()
    stored = cache.put(req, original, ttl=None)
    assert stored.headers["etag"] == "old"
    with pytest.raises(TypeError):
        stored.headers["etag"] = "mutated"
    with pytest.raises(FrozenInstanceError):
        stored.body = b"mutated"
    with pytest.raises(FrozenInstanceError):
        req.namespace = "other"
    with pytest.raises(FrozenInstanceError):
        cache.get(req).state = CacheState.MISS


def test_lookup_is_read_only_and_immutable_never_expires(cache, clock):
    req = request()
    assert cache.get(req).state is CacheState.MISS
    assert cache.get(req).response is None
    assert not cache.root.exists()
    cache.put(req, response(), ttl=None)
    path = entry_path(cache, req)
    before = path.read_bytes(), path.stat().st_mtime_ns
    clock.now += timedelta(days=36500)
    hit = cache.get(req)
    assert hit.state is CacheState.HIT_FRESH
    assert hit.response.expires_at is None
    assert hit.response.stored_at == NOW
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)


@pytest.mark.parametrize("elapsed,state", [
    (timedelta(0), CacheState.HIT_FRESH),
    (timedelta(seconds=10, microseconds=-1), CacheState.HIT_FRESH),
    (timedelta(seconds=10), CacheState.HIT_STALE),
    (timedelta(seconds=11), CacheState.HIT_STALE),
])
def test_ttl_boundary_is_not_sliding(cache, clock, elapsed, state):
    req = request()
    cache.put(req, response(), ttl=timedelta(seconds=10))
    clock.now += elapsed
    lookup = cache.get(req)
    assert lookup.state is state
    assert lookup.response.stored_at == NOW
    assert lookup.response.expires_at == NOW + timedelta(seconds=10)
    assert cache.get(req) == lookup


def test_zero_ttl_is_immediately_stale(cache):
    cache.put(request(), response(), ttl=timedelta(0))
    assert cache.get(request()).state is CacheState.HIT_STALE


def test_get_or_fetch_miss_hit_stale_refresh(cache, clock):
    req = request()
    fetch = Mock(side_effect=[response(b"first"), response(b"second")])
    first = cache.get_or_fetch(req, fetch, ttl=timedelta(seconds=10))
    assert first.body == b"first" and not first.from_cache
    assert fetch.call_count == 1
    assert cache.get(req).response.body == b"first"
    # New call's policy only applies to a new write, never silently extends a hit.
    second = cache.get_or_fetch(req, fetch, ttl=None)
    assert second.from_cache and second.expires_at == first.expires_at
    assert fetch.call_count == 1
    clock.now += timedelta(seconds=10)
    refreshed = cache.get_or_fetch(req, fetch, ttl=timedelta(seconds=20))
    assert not refreshed.from_cache and refreshed.body == b"second"
    assert refreshed.stored_at == clock.now
    assert refreshed.expires_at == clock.now + timedelta(seconds=20)
    assert fetch.call_count == 2
    assert cache.get(req).state is CacheState.HIT_FRESH


@pytest.mark.parametrize("status", [200, 201, 204, 206, 299])
def test_all_2xx_are_cacheable(cache, status):
    stored = cache.put(request(), response(status=status), ttl=None)
    assert cache.get(request()).response.status_code == stored.status_code == status


@pytest.mark.parametrize("status", [100, 301, 304, 400, 401, 404, 429, 500, 503, 599])
def test_other_statuses_are_not_cached(cache, status):
    fetch = Mock(return_value=response(status=status))
    result = cache.get_or_fetch(request(), fetch, ttl=None)
    assert result.status_code == status and not result.from_cache
    assert cache.get(request()).state is CacheState.MISS
    assert not cache.root.exists()
    cache.get_or_fetch(request(), fetch, ttl=None)
    assert fetch.call_count == 2


def test_failed_status_does_not_replace_stale_entry(cache):
    req = request()
    cache.put(req, response(b"old"), ttl=timedelta(0))
    before = entry_path(cache, req).read_bytes()
    result = cache.get_or_fetch(req, lambda: response(status=503), ttl=None)
    assert result.status_code == 503 and not result.from_cache
    assert entry_path(cache, req).read_bytes() == before
    assert cache.get(req).state is CacheState.HIT_STALE


@pytest.mark.parametrize("stale", [False, True])
def test_fetch_exception_propagates_without_stale_fallback(cache, stale):
    req = request()
    if stale:
        cache.put(req, response(), ttl=timedelta(0))
    failure = RuntimeError("transport failed")
    fetch = Mock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        cache.get_or_fetch(req, fetch, ttl=None)
    assert caught.value is failure
    assert fetch.call_count == 1
    assert cache.get(req).state is (CacheState.HIT_STALE if stale else CacheState.MISS)


@pytest.mark.parametrize("corruption", [
    {"body_checksum": "0" * 64}, {"content_length": 999}, {"cache_key": "0" * 64},
    {"request_fingerprint": "0" * 64}, {"namespace": "other"},
    {"request_method": "POST"}, {"request_url": "https://other.test"},
    {"payload_path": "../escape"}, {"metadata_version": 2},
    {"status_code": 500}, {"content_length": "3"}, {"checksum_algorithm": "md5"},
    {"stored_at": "2026-09-07T12:00:00"}, {"expires_at": "2026-09-06T12:00:00Z"},
    {"headers": {"Set-Cookie": "private"}}, {"headers": {"ETag": "noncanonical"}},
    {"headers": {"etag": "bad\r\nheader"}}, {"unknown": "field"},
])
def test_corrupted_metadata_rejected(cache, corruption):
    req = request()
    cache.put(req, response(), ttl=None)
    rewrite_entry(cache, req, change_metadata=lambda data: data.update(corruption))
    with pytest.raises(HttpCacheIntegrityError):
        cache.get(req)


def test_body_corruption_detected_even_with_valid_zip_crc(cache):
    req = request()
    cache.put(req, response(b"original"), ttl=None)
    rewrite_entry(cache, req, body=b"modified")
    with pytest.raises(HttpCacheIntegrityError, match="checksum/length"):
        cache.get(req)
    fetch = Mock(return_value=response())
    with pytest.raises(HttpCacheIntegrityError):
        cache.get_or_fetch(req, fetch, ttl=None)
    fetch.assert_not_called()


@pytest.mark.parametrize("kind", ["not_zip", "truncated", "invalid_json", "missing_member", "extra_member", "compressed"])
def test_invalid_container_rejected(cache, kind):
    req = request()
    cache.put(req, response(), ttl=None)
    path = entry_path(cache, req)
    if kind == "not_zip":
        path.write_bytes(b"invalid")
    elif kind == "truncated":
        path.write_bytes(path.read_bytes()[:30])
    elif kind == "compressed":
        rewrite_entry(cache, req, compression=ZIP_DEFLATED)
    elif kind == "extra_member":
        with ZipFile(path, "a") as archive:
            archive.writestr("../escape", b"never extracted")
    else:
        with ZipFile(path, "w") as archive:
            archive.writestr("response.bin", b"body")
            if kind == "invalid_json":
                archive.writestr("cache.metadata.json", b"{broken")
    with pytest.raises(HttpCacheIntegrityError):
        cache.get(req)


def test_invalidation_is_scoped_and_does_not_touch_raw_store(cache, tmp_path):
    req, another, other_namespace = request(), request(params={"a": 1}), request(namespace="other")
    for item in (req, another, other_namespace):
        cache.put(item, response(), ttl=None)
    raw = RawStore(tmp_path / "raw")
    snapshot = raw.store_bytes(b"historical", source_provider="example_provider",
                               entity="items", retrieved_at=NOW)
    assert cache.invalidate(req)
    assert not entry_path(cache, req).exists()
    assert cache.get(req).state is CacheState.MISS
    assert not cache.invalidate(req)
    assert cache.get(another).state is CacheState.HIT_FRESH
    assert cache.get(other_namespace).state is CacheState.HIT_FRESH
    assert raw.read_bytes(snapshot) == b"historical"


@pytest.mark.parametrize("namespace", ["", " ", "..", "../x", "..\\x", "/absolute", "C:/absolute",
                                       "C:relative", "\\\\server\\share", "CON", "nul", "COM1", "lPt9",
                                       "bad.", "bad ", "a:b", "x" * 65, "-start", None, 1])
def test_unsafe_namespace_rejected(namespace):
    with pytest.raises(HttpCacheValidationError):
        request(namespace=namespace)


@pytest.mark.parametrize("method", ["", "GET ", "GE T", "GET\r\n", "GÉT", None, 1])
def test_invalid_method_rejected(method):
    with pytest.raises(HttpCacheValidationError):
        request(method=method)


@pytest.mark.parametrize("url", ["", "file:///tmp/file", "/relative", "https:///missing",
    "https://user:password@example.test/", "https://example.test/path#fragment",
    "https://example.test/path\n", "https://example.test:bad/", "https://[broken/",
    "https://example.test/a b", "https://example.test/?a=%GG", "https://example.test/?a=%FF", None])
def test_invalid_url_rejected(url):
    with pytest.raises(HttpCacheValidationError):
        request(url=url)


@pytest.mark.parametrize("kwargs", [
    {"params": {"a": None}}, {"params": {1: "a"}}, {"params": {"a": True}},
    {"params": "a=1"}, {"params": ["ab"]}, {"params": [("a", "b", "c")]},
    {"sensitive_params": "token"}, {"sensitive_params": [1]},
    {"vary": {"account": 1}}, {"vary": "public"},
    {"body": {1: "bad"}}, {"body": {"bad": float("nan")}},
    {"body": (1, 2)}, {"body": bytearray(b"mutable")}, {"body": "\ud800"},
])
def test_invalid_identity_values_rejected(kwargs):
    with pytest.raises(HttpCacheValidationError):
        request(**kwargs)


def test_circular_body_rejected():
    body = []
    body.append(body)
    with pytest.raises(HttpCacheValidationError):
        request(body=body)


@pytest.mark.parametrize("ttl", [-1, 0, 1.5, "10", True, timedelta(seconds=-1)])
def test_invalid_ttl_prevents_fetch_and_write(cache, ttl):
    fetch = Mock(return_value=response())
    with pytest.raises(HttpCacheValidationError):
        cache.get_or_fetch(request(), fetch, ttl=ttl)
    fetch.assert_not_called()
    with pytest.raises(HttpCacheValidationError):
        cache.put(request(), response(), ttl=ttl)
    assert not cache.root.exists()


def test_overflow_ttl_rejected(cache):
    with pytest.raises(HttpCacheValidationError, match="range"):
        cache.put(request(), response(), ttl=timedelta.max)
    assert not cache.root.exists()


@pytest.mark.parametrize("now", [datetime(2026, 9, 7), "now", None])
def test_invalid_clock_value_rejected(cache, clock, now):
    clock.now = now
    with pytest.raises(HttpCacheValidationError, match="aware"):
        cache.put(request(), response(), ttl=None)
    assert not cache.root.exists()


@pytest.mark.parametrize("kwargs", [
    {"status_code": True}, {"status_code": 99}, {"status_code": 600},
    {"body": "text"}, {"body": bytearray(b"x")}, {"headers": []},
    {"headers": {"ETag": 3}}, {"headers": {1: "x"}},
    {"headers": {"ETag": "a", "etag": "b"}}, {"headers": {"ETag": "x\r\ny"}},
])
def test_invalid_response_rejected(kwargs):
    with pytest.raises(HttpCacheValidationError):
        HttpResponse(**{"status_code": 200, "body": b"body", **kwargs})


def test_invalid_api_arguments(cache):
    with pytest.raises(HttpCacheValidationError):
        HttpCache(cache.root, clock=42)
    with pytest.raises(HttpCacheValidationError):
        HttpCache(None)
    with pytest.raises(HttpCacheValidationError):
        cache.get("../key")
    with pytest.raises(HttpCacheValidationError):
        cache.put(request(), b"not-response", ttl=None)
    with pytest.raises(HttpCacheValidationError):
        cache.get_or_fetch(request(), None, ttl=None)
    with pytest.raises(HttpCacheValidationError):
        cache.get_or_fetch(request(), lambda: b"not-response", ttl=None)


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_preserves_old_complete_entry(cache, monkeypatch, failure, existing):
    req = request()
    if existing:
        cache.put(req, response(b"old"), ttl=None)
        before = entry_path(cache, req).read_bytes()
    def fail(*args, **kwargs):
        raise OSError("simulated publication failure")
    if failure == "write":
        original = ZipFile.writestr
        def fail_after_body(archive, name, data, *args, **kwargs):
            if name.filename == "cache.metadata.json":
                fail()
            return original(archive, name, data, *args, **kwargs)
        monkeypatch.setattr(ZipFile, "writestr", fail_after_body)
    else:
        monkeypatch.setattr(http_cache.os, failure, fail)
    with pytest.raises(HttpCacheWriteError) as caught:
        cache.put(req, response(b"new"), ttl=None)
    assert isinstance(caught.value.__cause__, OSError)
    if existing:
        assert entry_path(cache, req).read_bytes() == before
        assert cache.get(req).response.body == b"old"
    else:
        assert cache.get(req).state is CacheState.MISS
    assert not list(cache.root.rglob("*.tmp"))


def test_read_at_publication_sees_old_then_new(cache, monkeypatch):
    req = request()
    cache.put(req, response(b"old"), ttl=None)
    replace = http_cache.os.replace
    seen = []
    def inspect_then_replace(source, destination):
        # Metadata and body are complete but still invisible under final name.
        seen.append(cache.get(req).response.body)
        with ZipFile(source) as archive:
            assert archive.read("response.bin") == b"new"
            assert json.loads(archive.read("cache.metadata.json"))["body_checksum"] == hashlib.sha256(b"new").hexdigest()
        replace(source, destination)
    monkeypatch.setattr(http_cache.os, "replace", inspect_then_replace)
    cache.put(req, response(b"new"), ttl=None)
    assert seen == [b"old"]
    assert cache.get(req).response.body == b"new"


@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_reads_and_refreshes_across_instances(cache, clock, attempt):
    req = request()
    cache.put(req, response(b"initial", headers={"ETag": "initial"}), ttl=None)
    def work(index):
        local = HttpCache(cache.root, clock=clock)
        if index % 3 == 0:
            value = str(index)
            local.put(req, response(value.encode(), headers={"ETag": value}), ttl=None)
        result = local.get(req).response
        assert result.headers["etag"].encode() == result.body
        assert result.checksum == hashlib.sha256(result.body).hexdigest()
        assert result.content_length == len(result.body)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, range(48)))
    assert cache.get(req).state is CacheState.HIT_FRESH
    assert len(list(cache.root.rglob("*.zip"))) == 1
    assert not list(cache.root.rglob("*.tmp"))


def test_simultaneous_misses_may_both_fetch_without_corruption(cache, clock):
    barrier = Barrier(2)
    req = request()
    def work(index):
        def fetch():
            barrier.wait(timeout=10)
            return response(str(index).encode())
        return HttpCache(cache.root, clock=clock).get_or_fetch(req, fetch, ttl=None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    assert {result.body for result in results} == {b"0", b"1"}
    assert all(not result.from_cache for result in results)
    assert cache.get(req).response.body in {b"0", b"1"}


def test_invalidation_during_fetch_allows_later_publication(cache):
    req = request()
    cache.put(req, response(b"old"), ttl=timedelta(0))
    def fetch():
        assert cache.invalidate(req)
        assert cache.get(req).state is CacheState.MISS
        return response(b"new")
    cache.get_or_fetch(req, fetch, ttl=None)
    assert cache.get(req).response.body == b"new"


def test_moving_cache_and_changing_cwd(cache, clock, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = HttpCache(Path("relative-cache"), clock=clock)
    req = request()
    cache.put(req, response(), ttl=None)
    moved = tmp_path / "moved"
    shutil.copytree(cache.root, moved)
    monkeypatch.chdir(moved)
    assert cache.get(req).response.body == response().body
    assert HttpCache(moved, clock=clock).get(req).response.body == response().body


@pytest.mark.parametrize("operation,error", [("get", HttpCacheReadError), ("invalidate", HttpCacheWriteError)])
def test_io_errors_are_chained(cache, monkeypatch, operation, error):
    req = request()
    cache.put(req, response(), ttl=None)
    def fail(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "read_bytes" if operation == "get" else "unlink", fail)
    with pytest.raises(error) as caught:
        getattr(cache, operation)(req)
    assert isinstance(caught.value.__cause__, PermissionError)


def test_resolved_escape_blocks_read_write_and_invalidation(cache, tmp_path, monkeypatch):
    original = Path.resolve
    def escape(path, *args, **kwargs):
        if path.suffix == ".zip":
            return tmp_path / "outside.zip"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", escape)
    for operation in (lambda: cache.get(request()), lambda: cache.put(request(), response(), ttl=None),
                      lambda: cache.invalidate(request())):
        with pytest.raises(HttpCacheValidationError, match="outside root"):
            operation()
    assert not cache.root.exists()


def test_symlink_escape_rejected(cache, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    cache.root.mkdir()
    try:
        (cache.root / request().namespace).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(HttpCacheValidationError, match="outside root"):
        cache.put(request(), response(), ttl=None)
    assert list(outside.iterdir()) == []


def test_path_resolution_error_is_chained(cache, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("resolve failed")
    monkeypatch.setattr(Path, "resolve", fail)
    with pytest.raises(HttpCacheValidationError) as caught:
        cache.get(request())
    assert isinstance(caught.value.__cause__, OSError)
