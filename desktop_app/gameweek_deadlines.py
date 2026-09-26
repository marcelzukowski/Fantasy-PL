"""Read cached official FPL event deadlines for desktop GW selection.

The desktop deliberately reads immutable bootstrap snapshots already materialized
by the current-data pipeline.  It never refreshes the official API itself, so
opening the application remains free of external calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


_OFFICIAL_BOOTSTRAP_SOURCE = "official_fpl_api.bootstrap_static.local_snapshot"
_OFFICIAL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


@dataclass(frozen=True)
class OfficialEventDeadline:
    """One official FPL event deadline, represented in aware UTC."""

    gameweek: int
    deadline: datetime


@dataclass(frozen=True)
class ValidatedOfficialDeadline:
    """A deadline tied to the exact immutable bootstrap input of one run.

    ``season`` is the already-validated target season supplied by the current
    prediction context.  The Official FPL bootstrap API does not itself expose
    a season identifier, so this object never claims that the payload supplied
    one.
    """

    season: str
    gameweek: int
    deadline: datetime
    source: str
    observed_at: datetime
    raw_snapshot_id: str
    source_url: str

    def to_prediction_context_fields(self) -> dict[str, str | int]:
        return {
            "planning_gameweek": self.gameweek,
            "official_deadline": self.deadline.astimezone(timezone.utc).isoformat(),
            "deadline_source": self.source,
            "deadline_verification_status": "VERIFIED",
            "deadline_observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "deadline_raw_snapshot_id": self.raw_snapshot_id,
            "deadline_source_url": self.source_url,
        }


def _utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_season(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        start, end = value.split("/", 1)
        start_year = int(start)
        end_year = int(end)
    except (AttributeError, ValueError):
        return None
    if len(start) != 4 or len(end) != 2 or end_year != (start_year + 1) % 100:
        return None
    return value


def event_deadlines(payload: Mapping[str, Any]) -> tuple[OfficialEventDeadline, ...]:
    """Extract valid event ids and official ``deadline_time`` values."""
    rows = payload.get("events")
    if not isinstance(rows, list):
        return ()
    result: list[OfficialEventDeadline] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        gameweek = row.get("id")
        if type(gameweek) is not int or gameweek < 1:
            continue
        deadline = _utc(row.get("deadline_time"))
        if deadline is not None:
            result.append(OfficialEventDeadline(gameweek, deadline))
    return tuple(sorted(result, key=lambda event: event.gameweek))


def first_actionable_gameweek(
    events: Iterable[OfficialEventDeadline], *, now: datetime,
) -> int | None:
    """Return the first GW whose official deadline has not yet passed.

    Equality remains actionable: the deadline becomes unavailable only once
    the current time is strictly later than the official deadline.
    """
    current = _utc(now)
    if current is None:
        raise ValueError("now must be timezone-aware")
    for event in sorted(events, key=lambda value: value.gameweek):
        if event.deadline >= current:
            return event.gameweek
    return None


def _bootstrap_receipts(root: Path) -> Iterable[tuple[Path, Mapping[str, Any]]]:
    receipt_root = root / "data" / "snapshots" / "official_fpl_api"
    receipts = sorted(
        receipt_root.glob("*/bootstrap_static.snapshot.json"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for receipt_path in receipts:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(receipt, Mapping):
            yield receipt_path, receipt


def _receipt_payload(root: Path, receipt: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    raw = receipt.get("raw_snapshot")
    if not isinstance(raw, Mapping):
        return None
    raw_path = raw.get("payload_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    raw_root = (root / "data" / "raw").resolve()
    candidate = (raw_root / raw_path).resolve()
    try:
        candidate.relative_to(raw_root)
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return None
    return (payload, raw) if isinstance(payload, Mapping) else None


def load_cached_event_deadlines(root: Path) -> tuple[OfficialEventDeadline, ...]:
    """Load the newest readable cached official bootstrap snapshot.

    Local FPL snapshot receipts refer to the corresponding immutable RawStore
    payload.  A corrupt or incomplete receipt is ignored in favour of the
    preceding snapshot; no network fallback is ever attempted.
    """
    root = Path(root).resolve()
    for _receipt_path, receipt in _bootstrap_receipts(root):
        item = _receipt_payload(root, receipt)
        if item is None:
            continue
        payload, _raw = item
        deadlines = event_deadlines(payload)
        if deadlines:
            return deadlines
    return ()


def load_validated_official_deadline(
    root: Path,
    *,
    season: object,
    planning_gameweek: object,
    source_checksum: object,
    source_snapshot_timestamp: object,
) -> ValidatedOfficialDeadline | None:
    """Return a deadline only when it belongs to this run's bootstrap input.

    The caller supplies the selected season/GW and the bootstrap source record
    that was already validated by the current-data pipeline.  A receipt must
    match that record's checksum and snapshot timestamp exactly; a newer local
    bootstrap is never substituted.  Invalid or incomplete local data simply
    returns ``None`` and preserves the conservative unverified path.
    """
    validated_season = _valid_season(season)
    if validated_season is None or type(planning_gameweek) is not int or not 1 <= planning_gameweek <= 38:
        return None
    if not isinstance(source_checksum, str) or len(source_checksum) != 64:
        return None
    expected_timestamp = _utc(source_snapshot_timestamp)
    if expected_timestamp is None:
        return None
    root = Path(root).resolve()
    for _receipt_path, receipt in _bootstrap_receipts(root):
        observed_at = _utc(receipt.get("snapshot_timestamp"))
        item = _receipt_payload(root, receipt)
        if observed_at is None or item is None or observed_at != expected_timestamp:
            continue
        payload, raw = item
        raw_snapshot_id = raw.get("snapshot_id")
        raw_checksum = raw.get("checksum")
        if (
            receipt.get("season") != validated_season
            or not isinstance(raw_snapshot_id, str)
            or not raw_snapshot_id
            or raw_checksum != source_checksum
            or receipt.get("checksum") != source_checksum
            or raw.get("entity") != "bootstrap_static"
            or raw.get("source") != "local_fpl_archive"
        ):
            continue
        source_url = raw.get("source_url") or receipt.get("source_url")
        if source_url != _OFFICIAL_BOOTSTRAP_URL:
            continue
        deadline = next(
            (event.deadline for event in event_deadlines(payload) if event.gameweek == planning_gameweek),
            None,
        )
        if deadline is None:
            continue
        return ValidatedOfficialDeadline(
            season=validated_season,
            gameweek=planning_gameweek,
            deadline=deadline,
            source=_OFFICIAL_BOOTSTRAP_SOURCE,
            observed_at=observed_at,
            raw_snapshot_id=raw_snapshot_id,
            source_url=source_url,
        )
    return None
