"""Materialize pinned Vaastav outcomes and strict pre-deadline fplcache snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.providers.fplcache import FPLCacheAdapter
from fpl_engine.data.providers.vaastav import VaastavAdapter
from fpl_engine.data.raw_store import RawStore


FPLCACHE_REF = "68f1781b5a4c2c16148d641d9a07a6ba62d30bf2"
VAASTAV_REF = "9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88"


def _utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("seed cutoff must be aware")
    return value.astimezone(timezone.utc)


def _event_deadline(snapshot, gameweek: int) -> datetime:
    for event in snapshot.data.get("events", ()):
        if int(event.get("id", -1)) == gameweek and event.get("deadline_time"):
            return _utc(event["deadline_time"])
    raise RuntimeError(f"snapshot {snapshot.snapshot_path} has no deadline for GW{gameweek}")


def _resolve_snapshot(adapter, gameweek: int, initial_deadline: datetime):
    """Resolve schedule changes without reading a snapshot at/after the true deadline.

    A preseason bootstrap can contain a deadline that is subsequently moved
    earlier. Re-select until the selected pre-deadline snapshot itself agrees
    with the deadline used for selection.
    """
    deadline = initial_deadline
    seen = set()
    while deadline not in seen:
        seen.add(deadline)
        snapshot = adapter.get_snapshot_before(deadline)
        evidenced_deadline = _event_deadline(snapshot, gameweek)
        if evidenced_deadline == deadline:
            return deadline, snapshot
        deadline = evidenced_deadline
    raise RuntimeError(f"GW{gameweek} deadline resolution did not converge")


def materialize(root: Path, season: str, seed_cutoff: datetime) -> Path:
    index_path = root / "data" / "interim" / "source_indexes" / f"fplcache-{FPLCACHE_REF}.txt"
    paths = tuple(line.strip() for line in index_path.read_text(encoding="utf-8-sig").splitlines() if line.strip())
    raw_store = RawStore(root / "data" / "raw")
    cache = HttpCache(root / "data" / "interim" / "http_cache")
    with httpx.Client() as client:
        archive = FPLCacheAdapter(client=client, cache=cache, raw_store=raw_store,
                                  repository_ref=FPLCACHE_REF, snapshot_index=paths, ttl=None)
        seed = archive.get_snapshot_before(seed_cutoff)
        events = tuple(seed.data.get("events", ()))
        deadlines = {
            int(event["id"]): _utc(event["deadline_time"])
            for event in events
            if event.get("id") is not None and event.get("deadline_time")
        }
        if deadlines.get(1) != seed_cutoff:
            raise RuntimeError(
                f"seed cutoff {seed_cutoff.isoformat()} does not equal source GW1 deadline "
                f"{deadlines.get(1)!r}; choose an earlier verified seed snapshot/cutoff"
            )
        snapshots = []
        for gameweek, initial_deadline in sorted(deadlines.items()):
            deadline, snapshot = _resolve_snapshot(archive, gameweek, initial_deadline)
            snapshots.append({
                "gameweek": gameweek,
                "prediction_timestamp": deadline.isoformat(),
                "initial_preseason_deadline": initial_deadline.isoformat(),
                "deadline_changed_from_preseason": deadline != initial_deadline,
                "snapshot_timestamp": snapshot.snapshot_timestamp.isoformat(),
                "snapshot_path": snapshot.snapshot_path,
                "checksum": snapshot.response.checksum,
                "content_length": snapshot.response.content_length,
                "from_cache": snapshot.from_cache,
                "bootstrap_keys": sorted(snapshot.data),
                "player_count": len(snapshot.data.get("elements", ())),
                "team_count": len(snapshot.data.get("teams", ())),
                "contains_fixture_schedule": "fixtures" in snapshot.data,
            })
        vaastav = VaastavAdapter(client=client, cache=cache, raw_store=raw_store,
                                 repository_ref=VAASTAV_REF, ttl=None).get_merged_gameweeks(season)
    output = root / "data" / "interim" / "strict" / season
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "mode": "STRICT",
        "season": season,
        "fplcache_repository_ref": FPLCACHE_REF,
        "vaastav_repository_ref": VAASTAV_REF,
        "snapshot_rule": "snapshot_timestamp < prediction_timestamp",
        "prediction_points": snapshots,
        "vaastav": {
            "dataset": "merged_gw.csv",
            "checksum": vaastav.response.checksum,
            "content_length": vaastav.response.content_length,
            "columns": list(vaastav.columns),
            "unsafe_columns": sorted(vaastav.unsafe_columns),
            "rows": len(vaastav.data),
            "from_cache": vaastav.from_cache,
        },
    }
    target = output / "source_manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--seed-cutoff", default="2024-08-16T17:30:00Z")
    arguments = parser.parse_args()
    print(materialize(arguments.root.resolve(), arguments.season, _utc(arguments.seed_cutoff)))
