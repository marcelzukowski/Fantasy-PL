"""Materialize point-in-time Vaastav fixture schedules from Git history.

The Git checkout supplies revision timestamps and tree membership. Exact CSV
bytes are fetched from immutable commit URLs through VaastavAdapter, which writes
network responses to RawStore before parsing and uses HttpCache thereafter.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import lzma
from pathlib import Path
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
import pandas as pd

from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.providers.vaastav import VaastavAdapter
from fpl_engine.data.raw_store import RawSnapshot, RawStore


REPOSITORY_URL = "https://github.com/vaastav/Fantasy-Premier-League"
SOURCE_PATH_TEMPLATE = "data/{season}/fixtures.csv"


@dataclass(frozen=True)
class GitRevision:
    commit_sha: str
    commit_timestamp: datetime
    blob_sha: str


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return parsed.astimezone(timezone.utc)


def select_revisions(
    commits: Iterable[tuple[str, datetime]], deadlines: dict[int, datetime],
    blob_at: Callable[[str], str | None],
) -> tuple[dict[int, GitRevision], tuple[int, ...]]:
    """Choose the latest timestamped commit strictly before every deadline."""
    candidates: list[GitRevision] = []
    earliest = min(deadlines.values()) if deadlines else None
    latest = max(deadlines.values()) if deadlines else None
    for sha, timestamp in commits:
        timestamp = timestamp.astimezone(timezone.utc)
        if latest is not None and timestamp >= latest:
            continue
        # Retain older revisions because GW1 may need the first path-bearing tree.
        blob = blob_at(sha)
        if blob:
            candidates.append(GitRevision(sha, timestamp, blob))
    candidates.sort(key=lambda item: (item.commit_timestamp, item.commit_sha))
    selected: dict[int, GitRevision] = {}
    missing: list[int] = []
    for gameweek, deadline in sorted(deadlines.items()):
        eligible = [item for item in candidates if item.commit_timestamp < deadline]
        if not eligible:
            missing.append(gameweek)
        else:
            selected[gameweek] = eligible[-1]
    return selected, tuple(missing)


def _git_commits(repository: Path) -> list[tuple[str, datetime]]:
    result = subprocess.run(
        ["git", "log", "HEAD", "--format=%H%x09%cI"], cwd=repository,
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    commits = []
    for line in result.stdout.splitlines():
        sha, timestamp = line.split("\t", 1)
        commits.append((sha, _utc(timestamp)))
    return commits


def _blob_lookup(repository: Path, source_path: str) -> Callable[[str], str | None]:
    def lookup(commit_sha: str) -> str | None:
        result = subprocess.run(
            ["git", "ls-tree", commit_sha, "--", source_path], cwd=repository,
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        if not result.stdout.strip():
            return None
        prefix, listed_path = result.stdout.rstrip("\n").split("\t", 1)
        mode, kind, blob_sha = prefix.split()
        if mode != "100644" or kind != "blob" or listed_path != source_path:
            raise RuntimeError(f"unexpected Git tree entry for {commit_sha}:{source_path}")
        return blob_sha
    return lookup


def _raw_snapshot_for(root: Path, source_record_id: str, checksum: str) -> RawSnapshot:
    for path in root.rglob("snapshot.metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        record = metadata.get("source_record_id") or ""
        if (record == source_record_id or record.endswith(f":{source_record_id}")) and metadata.get("checksum") == checksum:
            metadata["source"] = metadata.pop("source_provider")
            return RawSnapshot.model_validate_json(json.dumps(metadata))
    raise RuntimeError(f"RawStore receipt missing for {source_record_id}")


def _team_names(raw_root: Path, point: dict[str, Any]) -> dict[int, str]:
    snapshot = _raw_snapshot_for(raw_root, point["snapshot_path"], point["checksum"])
    body = (raw_root / snapshot.payload_path).read_bytes()
    parsed = json.loads(lzma.decompress(body))
    return {int(team["id"]): str(team["name"]) for team in parsed["teams"]}


def _canonical_id(kind: str, semantic_key: str) -> str:
    # The namespace contains provider-neutral competition/club semantics; the
    # provider fixture ID is deliberately absent.
    return f"{kind}_{uuid5(NAMESPACE_URL, semantic_key)}"


def _json_row(row: pd.Series) -> str:
    value = {str(key): (None if pd.isna(item) else item.isoformat() if isinstance(item, pd.Timestamp) else item.item() if hasattr(item, "item") else item)
             for key, item in row.items()}
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def materialize(root: Path, repository: Path, season: str = "2024-25") -> Path:
    source_manifest_path = root / "data" / "interim" / "strict" / season / "source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    deadlines = {int(point["gameweek"]): _utc(point["prediction_timestamp"])
                 for point in source_manifest["prediction_points"]}
    source_path = SOURCE_PATH_TEMPLATE.format(season=season)
    selected, missing = select_revisions(
        _git_commits(repository), deadlines, _blob_lookup(repository, source_path),
    )
    raw_store = RawStore(root / "data" / "raw")
    cache = HttpCache(root / "data" / "interim" / "http_cache")
    point_by_gw = {int(point["gameweek"]): point for point in source_manifest["prediction_points"]}
    team_names = _team_names(raw_store.root, point_by_gw[min(point_by_gw)])
    state_rows: list[dict[str, Any]] = []
    revision_receipts: dict[str, dict[str, Any]] = {}
    with httpx.Client() as client:
        for gameweek, revision in sorted(selected.items()):
            adapter = VaastavAdapter(
                client=client, cache=cache, raw_store=raw_store,
                repository_ref=revision.commit_sha, ttl=None,
            )
            dataset = adapter.get_fixture_schedule(season)
            required = {"id", "event", "kickoff_time", "team_h", "team_a"}
            if missing_columns := required - set(dataset.columns):
                raise RuntimeError(f"fixture CSV {revision.commit_sha} lacks {sorted(missing_columns)}")
            raw_snapshot = dataset.raw_snapshot or _raw_snapshot_for(
                raw_store.root, f"{revision.commit_sha}:{season}:fixtures", dataset.response.checksum,
            )
            raw_store.verify_snapshot(raw_snapshot)
            if hashlib.sha256(raw_store.read_bytes(raw_snapshot)).hexdigest() != dataset.response.checksum:
                raise RuntimeError("RawStore bytes differ from parsed HTTP bytes")
            revision_receipts.setdefault(revision.commit_sha, {
                "commit_sha": revision.commit_sha,
                "commit_timestamp": revision.commit_timestamp.isoformat(),
                "blob_sha": revision.blob_sha,
                "source_path": source_path,
                "source_url": dataset.source_url,
                "raw_snapshot_id": raw_snapshot.snapshot_id,
                "raw_payload_path": raw_snapshot.payload_path,
                "raw_checksum": raw_snapshot.checksum,
                "content_length": raw_snapshot.content_length,
                "retrieved_at": raw_snapshot.retrieved_at.isoformat(),
                "from_cache": dataset.from_cache,
            })
            for _, row in dataset.data.iterrows():
                home_provider = int(row["team_h"])
                away_provider = int(row["team_a"])
                home_name, away_name = team_names[home_provider], team_names[away_provider]
                fixture_key = f"Premier League|{season}|{home_name.casefold()}|{away_name.casefold()}"
                kickoff = pd.to_datetime(row["kickoff_time"], utc=True, errors="coerce")
                state_rows.append({
                    "prediction_gameweek": gameweek,
                    "prediction_timestamp": deadlines[gameweek],
                    "information_known_at": revision.commit_timestamp,
                    "source_repository": REPOSITORY_URL,
                    "source_commit_sha": revision.commit_sha,
                    "source_path": source_path,
                    "raw_checksum": raw_snapshot.checksum,
                    "canonical_fixture_id": _canonical_id("fix", fixture_key),
                    "provider": "fpl",
                    "provider_fixture_id": str(int(row["id"])),
                    "canonical_home_team_id": _canonical_id("team", f"Premier League|{home_name.casefold()}"),
                    "provider_home_team_id": str(home_provider),
                    "canonical_away_team_id": _canonical_id("team", f"Premier League|{away_name.casefold()}"),
                    "provider_away_team_id": str(away_provider),
                    "scheduled_gameweek": None if pd.isna(row["event"]) else int(row["event"]),
                    "scheduled_kickoff": None if pd.isna(kickoff) else kickoff,
                    "provider_row_json": _json_row(row),
                })
    output = root / "data" / "interim" / "strict" / season
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "canonical_fixture_states.parquet"
    states = pd.DataFrame(state_rows)
    if not states.empty:
        states.sort_values(["prediction_gameweek", "canonical_fixture_id"], inplace=True)
    states.to_parquet(state_path, index=False)
    reschedules = 0
    if not states.empty:
        reschedules = int((states.groupby("canonical_fixture_id")["scheduled_kickoff"].nunique(dropna=True) > 1).sum())
    coverage = []
    for gameweek in sorted(deadlines):
        revision = selected.get(gameweek)
        coverage.append({
            "gameweek": gameweek,
            "prediction_timestamp": deadlines[gameweek].isoformat(),
            "covered": revision is not None,
            "commit_sha": revision.commit_sha if revision else None,
            "commit_timestamp": revision.commit_timestamp.isoformat() if revision else None,
            "blob_sha": revision.blob_sha if revision else None,
            "source_path": source_path if revision else None,
            "strictly_before": bool(revision and revision.commit_timestamp < deadlines[gameweek]),
            "fixture_rows": int((states["prediction_gameweek"] == gameweek).sum()) if not states.empty else 0,
        })
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()
    manifest = {
        "manifest_version": 1,
        "mode": "STRICT",
        "season": season,
        "selection_rule": "commit_timestamp < prediction_timestamp",
        "repository": REPOSITORY_URL,
        "repository_head_examined": head,
        "source_path": source_path,
        "prediction_points_requested": len(deadlines),
        "prediction_points_covered": len(selected),
        "missing_gameweeks": list(missing),
        "unique_commits_materialized": len(revision_receipts),
        "revisions": sorted(revision_receipts.values(), key=lambda item: item["commit_timestamp"]),
        "coverage": coverage,
        "canonical_fixture_state": {
            "path": state_path.relative_to(root).as_posix(),
            "rows": len(states),
            "canonical_fixtures": int(states["canonical_fixture_id"].nunique()) if not states.empty else 0,
            "rescheduled_fixtures": reschedules,
            "identity_rule": "provider-independent UUID5 of competition, season, home club and away club",
            "provider_ids_separate": True,
        },
    }
    target = output / "fixture_schedule_manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--season", default="2024-25")
    args = parser.parse_args()
    print(materialize(args.root.resolve(), args.repository.resolve(), args.season))
