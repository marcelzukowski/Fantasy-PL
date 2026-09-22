"""Read-only adapter from materialized STRICT seasons to current V1 histories."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import lzma
from pathlib import Path
from typing import Mapping
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from fpl_engine.data.raw_store import RawSnapshot, RawStore
from fpl_engine.data.identity import (
    IdentityResolutionError, official_fpl_player_identity_key,
)
from fpl_engine.features.minutes_dataset import MinutesObservation
from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.models.team_strength import MatchObservation
from fpl_engine.validation.leakage import assert_information_known


@dataclass(frozen=True)
class HistoricalModelContext:
    matches: tuple[MatchObservation, ...]
    minutes: Mapping[str, tuple[MinutesObservation, ...]]
    talent: Mapping[str, tuple[PlayerPerformanceObservation, ...]]
    source_versions: tuple[str, ...]
    warnings: tuple[str, ...]


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("historical timestamp must be aware")
    return parsed.astimezone(timezone.utc)


def _id(kind: str, value: str) -> str:
    return f"{kind}_{uuid5(NAMESPACE_URL, value.casefold().strip())}"


def _float(value):
    return None if pd.isna(value) else float(value)


def _receipts(raw_root: Path) -> dict[str, RawSnapshot]:
    result = {}
    for path in raw_root.rglob("snapshot.metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            checksum = metadata["checksum"]
            metadata["source"] = metadata.pop("source_provider")
            result.setdefault(checksum, RawSnapshot.model_validate_json(json.dumps(metadata)))
        except (OSError, ValueError, KeyError):
            continue
    return result



def reconcile_current_targets_with_known_history(
    current_states,
    match_rows,
    *,
    prediction_timestamp: datetime,
):
    """Reconcile stale scheduled targets against PIT-known completed matches.

    A historical schedule snapshot may still place a rescheduled fixture in
    the future even though the match was already played.  We may remove such
    a target only when the completed match was actually knowable at the
    prediction timestamp.

    Returns
    -------
    tuple
        ``(filtered_current_states, history_matches)``.
    """
    at = _utc(prediction_timestamp)

    history_matches = [
        row
        for row in match_rows
        if _utc(row.known_at) <= at
        and _utc(row.kickoff) < at
    ]

    known_completed_fixture_ids = {
        row.fixture_id
        for row in history_matches
    }

    if "canonical_fixture_id" not in current_states.columns:
        raise ValueError(
            "current_states must contain canonical_fixture_id"
        )

    filtered_current_states = current_states.loc[
        ~current_states["canonical_fixture_id"].isin(
            known_completed_fixture_ids
        )
    ].copy()

    return filtered_current_states, history_matches


def load_strict_historical_context(
    project_root: Path, seasons: tuple[str, ...], *, prediction_timestamp: datetime,
) -> HistoricalModelContext:
    """Load only immutable STRICT evidence already materialized by this repository.

    Vaastav ``xP`` is intentionally never read into a model record.  Match
    outcomes become knowable four hours after kickoff, matching the frozen
    historical runner's conservative rule.
    """
    at = _utc(prediction_timestamp)
    if not seasons:
        return HistoricalModelContext((), {}, {}, (), ())
    root = Path(project_root)
    raw = RawStore(root / "data" / "raw")
    receipt_by_checksum = _receipts(raw.root)
    matches: list[MatchObservation] = []
    minutes: dict[str, list[MinutesObservation]] = defaultdict(list)
    talent: dict[str, list[PlayerPerformanceObservation]] = defaultdict(list)
    versions: list[str] = []
    warnings: list[str] = []
    for season in seasons:
        interim = root / "data" / "interim" / "strict" / season
        manifest_path = interim / "source_manifest.json"
        states_path = interim / "canonical_fixture_states.parquet"
        if not manifest_path.exists() or not states_path.exists():
            warnings.append(f"STRICT {season} context is not materialized.")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            states = pd.read_parquet(states_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"STRICT {season} materialization is unreadable: {type(exc).__name__}.")
            continue
        vaastav_meta = manifest.get("vaastav", {})
        vaastav_checksum = vaastav_meta.get("checksum")
        receipt = receipt_by_checksum.get(vaastav_checksum)
        if receipt is None:
            warnings.append(f"STRICT {season} Vaastav RawStore receipt is unavailable.")
            continue
        try:
            body = raw.read_bytes(receipt)
            frame = pd.read_csv(BytesIO(body))
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            warnings.append(f"STRICT {season} Vaastav source is unreadable: {type(exc).__name__}.")
            continue
        # Presence is audited, but this unsafe field is never copied below.
        if "xP" not in frame.columns:
            warnings.append(f"STRICT {season} source lacks the expected xP audit column.")
        first_states = states.sort_values("prediction_gameweek").drop_duplicates("provider_fixture_id")
        fixture_ids = dict(zip(first_states.provider_fixture_id.astype(str), first_states.canonical_fixture_id))
        team_ids: dict[str, str] = {}
        for state in first_states.itertuples():
            team_ids[str(state.provider_home_team_id)] = state.canonical_home_team_id
            team_ids[str(state.provider_away_team_id)] = state.canonical_away_team_id

        first_elements: dict[int, dict] = {}
        team_name_to_provider: dict[str, str] = {}
        for point in manifest.get("prediction_points", []):
            snap = receipt_by_checksum.get(point.get("checksum"))
            if snap is None:
                continue
            try:
                payload = json.loads(lzma.decompress(raw.read_bytes(snap)))
            except (OSError, ValueError, lzma.LZMAError, json.JSONDecodeError) as exc:
                warnings.append(
                    f"STRICT {season} fplcache snapshot is unreadable: {type(exc).__name__}."
                )
                continue
            for element in payload.get("elements", []):
                first_elements.setdefault(int(element["id"]), element)
            for team in payload.get("teams", []):
                for name in (team.get("name"), team.get("short_name")):
                    if name:
                        team_name_to_provider[str(name)] = str(team["id"])
        player_ids = {}
        seen_player_keys = {}
        for provider_id, element in first_elements.items():
            try:
                identity_key = official_fpl_player_identity_key(element)
            except IdentityResolutionError as exc:
                raise RuntimeError(
                    f"STRICT {season} player {provider_id} lacks a safe identity key: {exc}"
                ) from exc

            previous = seen_player_keys.get(identity_key)
            if previous is not None and previous != provider_id:
                raise RuntimeError(
                    f"STRICT {season} player code identity collision: "
                    f"{previous} and {provider_id} share {identity_key}"
                )

            seen_player_keys[identity_key] = provider_id
            player_ids[provider_id] = _id("ply", identity_key)

        frame["fixture_key"] = frame["fixture"].astype(int).astype(str)
        frame["kickoff_dt"] = pd.to_datetime(frame["kickoff_time"], utc=True)
        for fixture_key, group in frame.groupby("fixture_key", sort=False):
            fixture_id = fixture_ids.get(fixture_key)
            if fixture_id is None:
                continue
            kickoff = group["kickoff_dt"].iloc[0].to_pydatetime()
            known_at = kickoff + timedelta(hours=4)
            if known_at > at:
                continue
            assert_information_known(
                known_at=known_at, prediction_timestamp=at,
                entity=fixture_id, source=f"vaastav:{season}",
            )
            state_rows = first_states[first_states.provider_fixture_id.astype(str) == fixture_key]
            if state_rows.empty:
                continue
            state = state_rows.iloc[0]
            home = group[group["was_home"] == True]
            away = group[group["was_home"] == False]
            home_score = group["team_h_score"].dropna()
            away_score = group["team_a_score"].dropna()
            if home_score.empty or away_score.empty:
                continue
            home_xg = home["expected_goals"].sum(min_count=1) if "expected_goals" in frame else None
            away_xg = away["expected_goals"].sum(min_count=1) if "expected_goals" in frame else None
            matches.append(MatchObservation(
                fixture_id, kickoff, known_at,
                state.canonical_home_team_id, state.canonical_away_team_id,
                float(home_score.iloc[0]), float(away_score.iloc[0]),
                _float(home_xg), _float(away_xg), season,
            ))
            team_xa = {
                True: _float(home["expected_assists"].sum(min_count=1)) if "expected_assists" in frame else None,
                False: _float(away["expected_assists"].sum(min_count=1)) if "expected_assists" in frame else None,
            }
            for row in group.to_dict(orient="records"):
                provider_player = int(row["element"])
                player_id = player_ids.get(provider_player)
                provider_team = team_name_to_provider.get(str(row.get("team")))
                team_id = team_ids.get(provider_team or "")
                if player_id is None or team_id is None:
                    continue
                played = int(row["minutes"])
                started = bool(int(row["starts"]))
                minutes[player_id].append(MinutesObservation(
                    player_id, fixture_id, kickoff, known_at, played, started,
                ))
                talent[player_id].append(PlayerPerformanceObservation(
                    player_id, fixture_id, kickoff, known_at, played, team_id,
                    _id("comp", "Premier League"), str(row["position"]),
                    npxg=None,
                    xa=_float(row.get("expected_assists")),
                    goals=_float(row.get("goals_scored")),
                    team_xa=team_xa[bool(row["was_home"])],
                    source="vaastav", source_fields=("expected_assists",),
                ))
        versions.extend((
            str(manifest.get("fplcache_repository_ref", "unknown")),
            str(manifest.get("vaastav_repository_ref", "unknown")),
        ))
    return HistoricalModelContext(
        tuple(sorted(matches, key=lambda row: (row.kickoff, row.fixture_id))),
        {key: tuple(sorted(value, key=lambda row: row.kickoff)) for key, value in minutes.items()},
        {key: tuple(sorted(value, key=lambda row: row.kickoff)) for key, value in talent.items()},
        tuple(sorted(set(versions))), tuple(warnings),
    )
