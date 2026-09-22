"""Append-only raw snapshots with deterministic bytes and verified sidecars."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field, ValidationError

from fpl_engine.types import SourceProvenance


class RawStoreError(Exception):
    """Base error for raw storage operations."""


class RawStoreValidationError(RawStoreError):
    """Invalid payload, provenance or unsafe storage path."""


class RawStoreWriteError(RawStoreError):
    """The filesystem could not publish a complete snapshot."""


class RawSnapshotExistsError(RawStoreError):
    """The intended snapshot directory already exists; nothing was overwritten."""


class RawSnapshotIntegrityError(RawStoreError):
    """Stored bytes or metadata are missing, unreadable or inconsistent."""


class RawSnapshot(SourceProvenance):
    """Frozen snapshot receipt; all stored paths are relative to the raw root."""

    snapshot_id: str
    entity: str
    checksum: str
    checksum_algorithm: Literal["sha256"] = "sha256"
    payload_format: Literal["json", "bytes"]
    payload_path: str
    metadata_path: str
    content_length: int = Field(ge=0)
    metadata_version: Literal[1] = 1

    @property
    def source_provider(self) -> str:
        return self.source


def _component(value: str) -> str:
    # A portable subset also excludes Windows devices, ADS, trailing dots/spaces.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", value):
        raise RawStoreValidationError(f"Unsafe provider/entity component: {value!r}")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise RawStoreValidationError(f"Reserved Windows provider/entity component: {value!r}")
    return value


def _json_bytes(value: Any) -> bytes:
    def check(item: Any) -> None:
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("Payload must contain only JSON-compatible values")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _metadata_bytes(snapshot: RawSnapshot) -> bytes:
    metadata = snapshot.model_dump(mode="json")
    metadata["source_provider"] = metadata.pop("source")
    return _json_bytes(metadata)


def _comparison_path(path: Path) -> Path | PureWindowsPath:
    # Windows resolve() may retain the extended prefix while paths are created.
    # Compare equivalent DOS/UNC spellings without changing the actual I/O path.
    if os.name == "nt":
        text = str(path)
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            text = text[4:]
        return PureWindowsPath(text)
    return path


def _snapshot_id(provenance: SourceProvenance, entity: str, checksum: str, payload_format: str) -> str:
    # Source identity distinguishes equal responses retrieved at the same instant.
    # Optional values serialize as JSON null; source text never enters filenames.
    identity = {
        "source_provider": provenance.source,
        "entity": entity,
        "retrieved_at": provenance.model_dump(mode="json")["retrieved_at"],
        "checksum": checksum,
        "payload_format": payload_format,
        "source_record_id": provenance.source_record_id,
        "source_url": provenance.source_url,
    }
    return hashlib.sha256(_json_bytes(identity)).hexdigest()


class RawStore:
    """Store JSON or exact bytes beneath an explicit, resolved root.

    Identical writes raise RawSnapshotExistsError, including concurrent writes.
    Each snapshot owns a directory reserved with exclusive mkdir. Complete,
    fsynced temporary files are published with no-overwrite hard links, metadata
    last. Local filesystem hard-link support is required (including NTFS).

    Metadata is the completion marker, not a two-file filesystem transaction.
    A process/machine crash can leave an incomplete directory; reads reject it
    and subsequent writes do not overwrite it. Known symlink escapes are rejected;
    this is not a sandbox against hostile concurrent filesystem replacement.
    """

    def __init__(self, root: Path):
        try:
            self.root = Path(root).resolve()
        except (OSError, RuntimeError) as exc:
            raise RawStoreValidationError(f"Cannot resolve raw root '{root}': {exc}") from exc

    def _path(self, relative: str) -> Path:
        path = PurePosixPath(relative)
        if path.is_absolute() or "\\" in relative or ":" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise RawStoreValidationError(f"Unsafe raw path {relative!r} under '{self.root}'")
        candidate = self.root / path
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise RawStoreValidationError(f"Cannot resolve raw path '{candidate}': {exc}") from exc
        if not _comparison_path(resolved).is_relative_to(_comparison_path(self.root)):
            raise RawStoreValidationError(f"Raw path '{candidate}' resolves to '{resolved}' outside root '{self.root}'")
        return candidate

    def store_json(
        self, payload: Any, *, source_provider: str, entity: str,
        retrieved_at: datetime, source_url: str | None = None,
        source_record_id: str | None = None,
    ) -> RawSnapshot:
        """Serialize JSON as sorted, compact UTF-8; never modify caller data."""
        try:
            content = _json_bytes(payload)
        except (ValueError, TypeError, RecursionError) as exc:
            raise RawStoreValidationError(
                f"Invalid JSON for {source_provider!r}/{entity!r} under '{self.root}': {exc}"
            ) from exc
        return self._store(content, "json", source_provider, entity, retrieved_at, source_url, source_record_id)

    def store_bytes(
        self, payload: bytes, *, source_provider: str, entity: str,
        retrieved_at: datetime, source_url: str | None = None,
        source_record_id: str | None = None,
    ) -> RawSnapshot:
        """Persist bytes unchanged; encode text explicitly before calling."""
        if type(payload) is not bytes:
            raise RawStoreValidationError(
                f"Expected bytes for {source_provider!r}/{entity!r} under '{self.root}'"
            )
        return self._store(payload, "bytes", source_provider, entity, retrieved_at, source_url, source_record_id)

    def _store(self, content, payload_format, source_provider, entity, retrieved_at, source_url, source_record_id):
        try:
            _component(source_provider)
            _component(entity)
            provenance = SourceProvenance(
                source=source_provider, retrieved_at=retrieved_at,
                source_url=source_url, source_record_id=source_record_id,
            )
        except (ValidationError, RawStoreValidationError) as exc:
            raise RawStoreValidationError(
                f"Invalid snapshot for {source_provider!r}/{entity!r} under '{self.root}': {exc}"
            ) from exc
        checksum = hashlib.sha256(content).hexdigest()
        snapshot_id = _snapshot_id(provenance, entity, checksum, payload_format)
        partition = provenance.retrieved_at.date().isoformat()
        directory = f"{source_provider}/{entity}/{partition}/{snapshot_id}"
        extension = "json" if payload_format == "json" else "bin"
        snapshot = RawSnapshot(
            **provenance.model_dump(), snapshot_id=snapshot_id, entity=entity,
            checksum=checksum, payload_format=payload_format,
            payload_path=f"{directory}/payload.{extension}",
            metadata_path=f"{directory}/snapshot.metadata.json", content_length=len(content),
        )
        try:
            metadata_content = _metadata_bytes(snapshot)
        except (ValueError, TypeError, RecursionError) as exc:
            raise RawStoreValidationError(f"Invalid metadata for snapshot '{directory}': {exc}") from exc
        self._publish(snapshot, content, metadata_content)
        return snapshot

    def _publish(self, snapshot: RawSnapshot, content: bytes, metadata_content: bytes) -> None:
        payload = self._path(snapshot.payload_path)
        metadata = self._path(snapshot.metadata_path)
        directory = payload.parent
        reserved = False
        published = []
        complete = False
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            self._path(snapshot.payload_path)
            directory.mkdir()  # Exclusive reservation across threads/processes.
            reserved = True
            with TemporaryDirectory(prefix=".raw-", dir=directory.parent) as staging:
                for filename, data in (("payload", content), ("metadata", metadata_content)):
                    with (Path(staging) / filename).open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                for filename, destination in (("payload", payload), ("metadata", metadata)):
                    self._path(destination.relative_to(self.root).as_posix())
                    os.link(Path(staging) / filename, destination)
                    published.append(destination)
                complete = True
        except FileExistsError as exc:
            raise RawSnapshotExistsError(f"Raw snapshot already exists at '{directory}'") from exc
        except OSError as exc:
            raise RawStoreWriteError(f"Cannot publish raw snapshot at '{directory}': {exc}") from exc
        finally:
            if reserved and not complete:
                # Remove only files published by this failed call, never prior snapshots.
                for path in reversed(published):
                    try:
                        self._path(path.relative_to(self.root).as_posix()).unlink()
                    except (OSError, RawStoreValidationError):
                        pass
                try:
                    self._path(directory.relative_to(self.root).as_posix()).rmdir()
                except (OSError, RawStoreValidationError):
                    pass

    def read_bytes(self, snapshot: RawSnapshot) -> bytes:
        """Read exact bytes, verifying the sidecar, SHA-256 and byte length.

        The frozen receipt is the expected metadata. Paths remain portable when
        the raw root moves. This detects corruption, not signed authenticity.
        """
        try:
            metadata = self._path(snapshot.metadata_path)
            payload = self._path(snapshot.payload_path)
            if metadata.read_bytes() != _metadata_bytes(snapshot):
                raise RawSnapshotIntegrityError(f"Metadata mismatch at '{metadata}'")
            content = payload.read_bytes()
            if len(content) != snapshot.content_length or hashlib.sha256(content).hexdigest() != snapshot.checksum:
                raise RawSnapshotIntegrityError(f"Payload checksum/length mismatch at '{payload}'")
            return content
        except OSError as exc:
            raise RawSnapshotIntegrityError(
                f"Cannot read raw snapshot '{snapshot.snapshot_id}' under '{self.root}': {exc}"
            ) from exc

    def verify_snapshot(self, snapshot: RawSnapshot) -> None:
        """Raise RawSnapshotIntegrityError if the snapshot fails verification."""
        self.read_bytes(snapshot)
