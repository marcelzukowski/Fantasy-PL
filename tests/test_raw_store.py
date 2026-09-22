"""DATA-001 raw persistence, integrity, collision and filesystem safety tests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from fpl_engine.data import raw_store
from fpl_engine.data.raw_store import (
    RawSnapshot, RawSnapshotExistsError, RawSnapshotIntegrityError,
    RawStore, RawStoreValidationError, RawStoreWriteError,
)
from fpl_engine.types import SourceProvenance


RETRIEVED = datetime(2026, 9, 7, 14, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2)))
UTC_TIME = RETRIEVED.astimezone(timezone.utc)


@pytest.fixture
def store(tmp_path):
    return RawStore(tmp_path / "raw")


def save(store, payload=b"evidence", **overrides):
    arguments = {"source_provider": "official_fpl_api", "entity": "fixtures", "retrieved_at": RETRIEVED}
    arguments.update(overrides)
    return store.store_bytes(payload, **arguments)


def test_json_stores_exact_deterministic_utf8_and_preserves_input(store):
    payload = {"players": [{"name": "Łódź", "id": 1}], "missing": None, "available": False}
    original = deepcopy(payload)
    snapshot = store.store_json(payload, source_provider="official_fpl_api", entity="bootstrap_static", retrieved_at=RETRIEVED)
    stored = store.read_bytes(snapshot)
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert stored == expected
    assert json.loads(stored) == payload == original
    assert "Łódź".encode("utf-8") in stored
    assert snapshot.checksum == hashlib.sha256(stored).hexdigest()
    assert snapshot.content_length == len(stored)
    assert snapshot.payload_format == "json"


def test_json_order_and_timezone_do_not_change_snapshot_identity(tmp_path):
    first, second = RawStore(tmp_path / "one"), RawStore(tmp_path / "two")
    a = first.store_json({"b": {"z": 1, "a": 2}, "a": 3}, source_provider="provider", entity="items", retrieved_at=RETRIEVED)
    b = second.store_json({"a": 3, "b": {"a": 2, "z": 1}}, source_provider="provider", entity="items", retrieved_at=UTC_TIME)
    assert a == b
    assert first.read_bytes(a) == second.read_bytes(b)
    assert (first.root / a.metadata_path).read_bytes() == (second.root / b.metadata_path).read_bytes()


@pytest.mark.parametrize("payload", [b"", b"\x00\xff\xfe\r\n\n", bytes(range(256))])
def test_bytes_are_unchanged_and_checksum_matches(store, payload):
    snapshot = save(store, payload)
    assert store.read_bytes(snapshot) == payload
    assert snapshot.checksum == hashlib.sha256(payload).hexdigest()
    assert snapshot.content_length == len(payload)
    assert snapshot.payload_format == "bytes"
    assert store.verify_snapshot(snapshot) is None


def test_sidecar_contains_portable_metadata_and_canonical_provenance(store):
    snapshot = save(store, source_url="https://example.com/fixtures", source_record_id="record-1")
    assert isinstance(snapshot, (RawSnapshot, SourceProvenance))
    assert snapshot.retrieved_at.tzinfo is timezone.utc
    assert snapshot.source_provider == snapshot.source == "official_fpl_api"
    metadata = json.loads((store.root / snapshot.metadata_path).read_bytes())
    assert metadata["retrieved_at"] == "2026-09-07T12:00:00.123456Z"
    for key in ("snapshot_id", "source_provider", "entity", "checksum", "checksum_algorithm", "payload_format", "payload_path", "metadata_path", "content_length", "metadata_version"):
        assert metadata[key] == getattr(snapshot, key)
    assert metadata["source_url"] == snapshot.source_url
    assert metadata["source_record_id"] == snapshot.source_record_id
    assert metadata["known_at"] is metadata["effective_at"] is None
    assert metadata["checksum_algorithm"] == "sha256"
    assert metadata["metadata_version"] == 1
    for key in ("payload_path", "metadata_path"):
        assert not Path(metadata[key]).is_absolute()
        assert "\\" not in metadata[key]
        assert metadata[key].startswith(f"official_fpl_api/fixtures/2026-09-07/{snapshot.snapshot_id}/")
    assert str(store.root) not in json.dumps(metadata)
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.checksum = "changed"


def test_identical_write_is_explicit_and_does_not_change_existing_files(store):
    snapshot = save(store)
    paths = [store.root / snapshot.payload_path, store.root / snapshot.metadata_path]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    with pytest.raises(RawSnapshotExistsError) as error:
        save(store)
    assert snapshot.snapshot_id in str(error.value)
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == before


@pytest.mark.parametrize("payload_format", ["bytes", "json"])
@pytest.mark.parametrize("field,first_value,second_value", [
    ("source_record_id", "123", "456"),
    ("source_record_id", None, "123"),
    ("source_url", "https://example.test/items/123/", "https://example.test/items/456/"),
    ("source_url", None, "https://example.test/items/123/"),
])
def test_source_identity_distinguishes_equal_payloads_at_same_time(
    store, payload_format, field, first_value, second_value,
):
    payload = b"identical evidence\x00\xff" if payload_format == "bytes" else {"items": []}
    write = store.store_bytes if payload_format == "bytes" else store.store_json
    arguments = dict(source_provider="provider", entity="items", retrieved_at=RETRIEVED)
    first = write(payload, **arguments, **{field: first_value})
    first_paths = [store.root / first.payload_path, store.root / first.metadata_path]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in first_paths]
    second = write(payload, **arguments, **{field: second_value})

    assert first.snapshot_id != second.snapshot_id
    assert first.retrieved_at == second.retrieved_at == UTC_TIME
    assert store.read_bytes(first) == store.read_bytes(second)
    assert first.checksum == second.checksum == hashlib.sha256(store.read_bytes(first)).hexdigest()
    assert first.payload_path != second.payload_path
    for snapshot, expected in ((first, first_value), (second, second_value)):
        store.verify_snapshot(snapshot)
        metadata = json.loads((store.root / snapshot.metadata_path).read_bytes())
        assert metadata[field] == expected
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in first_paths] == before
    assert len(list(store.root.rglob("snapshot.metadata.json"))) == 2


def test_source_identity_is_deterministic_and_exact_duplicate_is_rejected(store, tmp_path):
    identity = dict(source_record_id="123", source_url="https://example.test/items/123/?event=5")
    first = save(store, **identity)
    other_store = RawStore(tmp_path / "other")
    same = save(other_store, retrieved_at=UTC_TIME, **identity)
    assert first == same
    assert (store.root / first.metadata_path).read_bytes() == (other_store.root / same.metadata_path).read_bytes()
    paths = [store.root / first.payload_path, store.root / first.metadata_path]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    with pytest.raises(RawSnapshotExistsError):
        save(store, **identity)
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == before


def test_source_identity_values_never_appear_in_paths_or_logs(store, caplog):
    identity = dict(source_record_id="private-record-value",
                    source_url="https://example.test/items/?token=private-query-value")
    snapshot = save(store, **identity)
    with pytest.raises(RawSnapshotExistsError) as caught:
        save(store, **identity)
    relative_paths = [str(path.relative_to(store.root)) for path in store.root.rglob("*")]
    assert len(snapshot.snapshot_id) == 64
    assert all(character in "0123456789abcdef" for character in snapshot.snapshot_id)
    for secret in (identity["source_record_id"], identity["source_url"], "private-query-value"):
        assert all(secret not in path for path in relative_paths)
        assert secret not in str(caught.value) + caplog.text


def test_legacy_snapshot_remains_readable_and_unchanged(store, monkeypatch):
    # Reproduce the previous identity contract only to create an on-disk legacy receipt.
    def legacy_id(provenance, entity, checksum, payload_format):
        identity = dict(source_provider=provenance.source, entity=entity,
                        retrieved_at=provenance.model_dump(mode="json")["retrieved_at"],
                        checksum=checksum, payload_format=payload_format)
        return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    identity = dict(source_record_id="123", source_url="https://example.test/items/123/")
    with monkeypatch.context() as legacy:
        legacy.setattr(raw_store, "_snapshot_id", legacy_id)
        snapshot = save(store, **identity)
    paths = [store.root / snapshot.payload_path, store.root / snapshot.metadata_path]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    current = save(store, **identity)
    assert current.snapshot_id != snapshot.snapshot_id
    assert current.metadata_version == snapshot.metadata_version == 1
    assert store.read_bytes(snapshot) == store.read_bytes(current) == b"evidence"
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == before


def test_hash_collision_cannot_replace_existing_evidence(store, monkeypatch):
    snapshot = save(store)
    monkeypatch.setattr(raw_store, "_snapshot_id", lambda *args: snapshot.snapshot_id)
    with pytest.raises(RawSnapshotExistsError):
        save(store, b"different evidence")
    assert store.read_bytes(snapshot) == b"evidence"


@pytest.mark.parametrize("change", ["payload", "checksum", "missing_payload", "missing_metadata", "broken_metadata"])
def test_corruption_is_detected(store, change):
    snapshot = save(store)
    payload = store.root / snapshot.payload_path
    metadata = store.root / snapshot.metadata_path
    if change == "payload":
        payload.write_bytes(b"modified")
    elif change == "checksum":
        document = json.loads(metadata.read_bytes())
        document["checksum"] = "0" * 64
        metadata.write_text(json.dumps(document), encoding="utf-8")
    elif change == "missing_payload":
        payload.unlink()
    elif change == "missing_metadata":
        metadata.unlink()
    else:
        metadata.write_bytes(b"{")
    with pytest.raises(RawSnapshotIntegrityError) as error:
        store.verify_snapshot(snapshot)
    assert str(store.root) in str(error.value)


@pytest.mark.parametrize("field", ["source_provider", "entity"])
@pytest.mark.parametrize("value", ["", "  ", ".", "..", "../../outside", "..\\..\\outside", "/provider", "C:\\outside", "C:outside", "a/b", "a\\b", " provider", "provider ", "CON", "com1", "a:stream"])
def test_unsafe_components_are_rejected_without_writes(store, field, value):
    with pytest.raises(RawStoreValidationError):
        save(store, **{field: value})
    assert not store.root.exists()


@pytest.mark.parametrize("invalid", [datetime(2026, 9, 7, 12), "2026-09-07T12:00:00Z", None])
def test_invalid_retrieval_time_is_rejected(store, invalid):
    with pytest.raises(RawStoreValidationError) as error:
        save(store, retrieved_at=invalid)
    assert isinstance(error.value.__cause__, ValidationError)
    assert not store.root.exists()


def test_retrieval_time_is_mandatory(store):
    with pytest.raises(TypeError):
        store.store_bytes(b"data", source_provider="provider", entity="entity")


@pytest.mark.parametrize("payload", [{1: "not a string key"}, {"value": float("nan")}, float("inf"), {"value": UTC_TIME}, (1, 2), {"value": "\ud800"}])
def test_non_json_payloads_fail_before_writing(store, payload):
    with pytest.raises(RawStoreValidationError):
        store.store_json(payload, source_provider="provider", entity="items", retrieved_at=RETRIEVED)
    assert not store.root.exists()


def test_circular_json_fails_clearly(store):
    payload = []
    payload.append(payload)
    with pytest.raises(RawStoreValidationError):
        store.store_json(payload, source_provider="provider", entity="items", retrieved_at=RETRIEVED)


def test_non_bytes_payload_fails(store):
    with pytest.raises(RawStoreValidationError):
        save(store, "text must be explicitly encoded")


def test_invalid_optional_metadata_fails_before_writing(store):
    with pytest.raises(RawStoreValidationError):
        save(store, source_url="https://example.com/\ud800")
    assert not store.root.exists()


def test_providers_entities_times_and_content_have_separate_snapshots(store):
    snapshots = [
        save(store), save(store, source_provider="api_football"),
        save(store, entity="player_summary"),
        save(store, retrieved_at=RETRIEVED + timedelta(microseconds=1)),
        save(store, b"updated evidence"),
    ]
    assert len({item.snapshot_id for item in snapshots}) == len(snapshots)
    assert len({item.payload_path for item in snapshots}) == len(snapshots)
    assert snapshots[1].payload_path.startswith("api_football/")
    assert "/player_summary/" in snapshots[2].payload_path
    for item in snapshots:
        store.verify_snapshot(item)


def test_moving_root_does_not_break_receipt(store, tmp_path):
    snapshot = save(store)
    new_root = tmp_path / "moved"
    shutil.copytree(store.root, new_root)
    assert RawStore(new_root).read_bytes(snapshot) == b"evidence"


def test_root_is_anchored_before_cwd_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = RawStore(Path("raw"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    snapshot = save(store)
    assert store.root == tmp_path / "raw"
    assert store.read_bytes(snapshot) == b"evidence"


@pytest.mark.parametrize("attempt", range(10))
def test_concurrent_same_snapshot_has_one_winner(store, attempt):
    def write(_):
        try:
            return save(RawStore(store.root))
        except RawSnapshotExistsError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(8)))
    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    assert store.read_bytes(winners[0]) == b"evidence"
    assert sorted(path.name for path in (store.root / winners[0].payload_path).parent.iterdir()) == ["payload.bin", "snapshot.metadata.json"]


@pytest.mark.parametrize("failure", ["fsync", "metadata_link"])
def test_write_failure_never_leaves_a_completed_snapshot(store, monkeypatch, failure):
    original_link = os.link
    def fail_fsync(*args):
        raise OSError("simulated disk failure")
    def fail_metadata_link(source, destination):
        if str(destination).endswith("metadata.json"):
            raise OSError("simulated link failure")
        original_link(source, destination)
    monkeypatch.setattr(raw_store.os, "fsync" if failure == "fsync" else "link", fail_fsync if failure == "fsync" else fail_metadata_link)
    with pytest.raises(RawStoreWriteError) as error:
        save(store)
    assert isinstance(error.value.__cause__, OSError)
    assert not [path for path in store.root.rglob("*") if path.is_file()]


def test_symlink_escape_is_rejected(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.mkdir()
    try:
        (store.root / "official_fpl_api").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(RawStoreValidationError, match="outside root"):
        save(store)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("path", ["../outside", "/outside", "C:/outside", "..\\outside"])
def test_read_rejects_unsafe_receipt_paths(store, path):
    snapshot = save(store)
    unsafe = snapshot.model_copy(update={"payload_path": path})
    with pytest.raises(RawStoreValidationError):
        store.read_bytes(unsafe)
