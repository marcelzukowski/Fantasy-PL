"""Read cached official FPL event deadlines for desktop GW selection.

The desktop deliberately reads the immutable bootstrap snapshot already
materialized by the current-data pipeline.  It never refreshes the official
API itself, so opening the application remains free of external calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class OfficialEventDeadline:
    """One official FPL event deadline, represented in aware UTC."""

    gameweek: int
    deadline: datetime


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


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
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(timezone.utc)
    for event in sorted(events, key=lambda value: value.gameweek):
        if event.deadline >= current:
            return event.gameweek
    return None


def load_cached_event_deadlines(root: Path) -> tuple[OfficialEventDeadline, ...]:
    """Load the newest readable cached official bootstrap snapshot.

    Local FPL snapshot receipts refer to the corresponding immutable RawStore
    payload.  A corrupt or incomplete receipt is ignored in favour of the
    preceding snapshot; no network fallback is ever attempted.
    """
    root = Path(root).resolve()
    receipt_root = root / "data" / "snapshots" / "official_fpl_api"
    receipts = sorted(
        receipt_root.glob("*/bootstrap_static.snapshot.json"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for receipt_path in receipts:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            raw = receipt.get("raw_snapshot")
            raw_path = raw.get("payload_path") if isinstance(raw, Mapping) else None
            if not isinstance(raw_path, str):
                continue
            payload = json.loads((root / "data" / "raw" / raw_path).read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                continue
        except (OSError, json.JSONDecodeError):
            continue
        deadlines = event_deadlines(payload)
        if deadlines:
            return deadlines
    return ()
