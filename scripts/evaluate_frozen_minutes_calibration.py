from __future__ import annotations

import importlib.util
import json
import math
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import pandas as pd

from fpl_engine.data.identity import (
    IdentityResolutionError,
    official_fpl_player_identity_key,
)
from fpl_engine.features.minutes_dataset import MinutesObservation
from fpl_engine.models.minutes import (
    MinutesContext,
    MinutesFeatureSignal,
    MinutesModel,
)
from fpl_engine.models.minutes.calibration import (
    load_minutes_calibration,
)

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "strict_runner",
    ROOT / "scripts" / "run_strict_model_backtest.py",
)
strict = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(strict)

TARGET_SEASON = "2025-26"
CALIBRATION_SEASON = "2024-25"

strict.SEASON = TARGET_SEASON

interim = ROOT / "data" / "interim" / "strict" / TARGET_SEASON

source = json.loads(
    (interim / "source_manifest.json").read_text(encoding="utf-8")
)

snapshots = strict._snapshots(ROOT, source)
outcomes = strict._vaastav(ROOT, source)

states = pd.read_parquet(
    interim / "canonical_fixture_states.parquet"
)
states["prediction_timestamp"] = pd.to_datetime(
    states["prediction_timestamp"], utc=True
)
states["information_known_at"] = pd.to_datetime(
    states["information_known_at"], utc=True
)

first_states = (
    states
    .sort_values("prediction_gameweek")
    .drop_duplicates("provider_fixture_id")
)

fixture_ids = dict(
    zip(
        first_states.provider_fixture_id.astype(str),
        first_states.canonical_fixture_id,
    )
)

first_elements = {}

for gw in sorted(snapshots):
    for element in snapshots[gw]["payload"]["elements"]:
        first_elements.setdefault(int(element["id"]), element)

player_ids = {}
seen = {}

for element_id, element in first_elements.items():
    try:
        key = official_fpl_player_identity_key(element)
    except IdentityResolutionError as exc:
        raise RuntimeError(
            f"Unsafe player identity for {element_id}: {exc}"
        ) from exc

    previous = seen.get(key)
    if previous is not None and previous != element_id:
        raise RuntimeError(
            f"Identity collision: {previous}, {element_id}, {key}"
        )

    seen[key] = element_id
    player_ids[element_id] = strict._identifier("player", key)

outcomes["fixture_key"] = (
    outcomes["fixture"].astype(int).astype(str)
)
outcomes["kickoff_dt"] = pd.to_datetime(
    outcomes["kickoff_time"], utc=True
)

minutes_history = defaultdict(list)
actuals = {}

for fixture_key, group in outcomes.groupby(
    "fixture_key", sort=False
):
    if fixture_key not in fixture_ids:
        continue

    kickoff = group["kickoff_dt"].iloc[0].to_pydatetime()
    known_at = kickoff + timedelta(hours=4)

    for _, row in group.iterrows():
        element_id = int(row["element"])

        if element_id not in player_ids:
            continue

        pid = player_ids[element_id]

        obs = MinutesObservation(
            pid,
            fixture_ids[fixture_key],
            kickoff,
            known_at,
            int(row["minutes"]),
            bool(int(row["starts"])),
        )

        minutes_history[element_id].append(obs)
        actuals[(fixture_key, element_id)] = obs

artifact_path = (
    ROOT
    / "data"
    / "processed"
    / "models"
    / "minutes"
    / f"minutes_calibration_{CALIBRATION_SEASON}.json"
)

artifact = load_minutes_calibration(artifact_path)
model = MinutesModel()

positions = {
    1: "GK",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

raw_scores = []
cal_scores = []

for gw in sorted(snapshots):
    snap = snapshots[gw]
    payload = snap["payload"]

    at = snap["prediction_timestamp"]
    snapshot_at = snap["snapshot_timestamp"]

    current_states = states[
        (states["prediction_gameweek"] == gw)
        & (states["scheduled_gameweek"] == gw)
    ]

    element_by_team = defaultdict(list)

    for element in payload["elements"]:
        element_by_team[str(element["team"])].append(element)

    for state in current_states.itertuples():
        fixture_key = str(state.provider_fixture_id)

        for provider_team in (
            str(state.provider_home_team_id),
            str(state.provider_away_team_id),
        ):
            for element in element_by_team.get(provider_team, []):
                element_id = int(element["id"])

                if element_id not in player_ids:
                    continue

                element_type = int(
                    element.get("element_type", 0)
                )

                if element_type not in positions:
                    continue

                actual = actuals.get(
                    (fixture_key, element_id)
                )

                if actual is None:
                    continue

                pid = player_ids[element_id]

                prior = [
                    row
                    for row in minutes_history[element_id]
                    if row.known_at <= at
                    and row.fixture_id != state.canonical_fixture_id
                ]

                probability, unavailable = strict._availability(
                    element
                )

                context = MinutesContext(
                    pid,
                    state.canonical_fixture_id,
                    at,
                    position=positions[element_type],
                    availability_probability=probability,
                    availability_known_at=snapshot_at,
                    availability_confidence=(
                        1.0 if probability is not None else None
                    ),
                    definitely_unavailable=unavailable,
                    signals=(
                        MinutesFeatureSignal(
                            "status",
                            element.get("status"),
                            snapshot_at,
                            snapshot_at,
                            "fplcache",
                            source_snapshot_timestamp=snapshot_at,
                        ),
                    ),
                )

                raw = model.predict(prior, context)

                calibrated = model.predict(
                    prior,
                    context,
                    calibration=artifact,
                )

                target_start = float(actual.started)
                target60 = float(actual.minutes >= 60)
                target75 = float(actual.minutes >= 75)
                target90 = float(actual.minutes >= 90)

                raw_scores.append((
                    abs(actual.minutes - raw.expected_minutes),
                    (actual.minutes - raw.expected_minutes) ** 2,
                    (raw.p_start - target_start) ** 2,
                    (raw.p60 - target60) ** 2,
                    (raw.p75 - target75) ** 2,
                    (raw.p90 - target90) ** 2,
                ))

                cal_scores.append((
                    abs(actual.minutes - calibrated.expected_minutes),
                    (actual.minutes - calibrated.expected_minutes) ** 2,
                    (calibrated.p_start - target_start) ** 2,
                    (calibrated.p60 - target60) ** 2,
                    (calibrated.p75 - target75) ** 2,
                    (calibrated.p90 - target90) ** 2,
                ))


def aggregate(rows):
    n = len(rows)

    return {
        "N": n,
        "MAE": sum(x[0] for x in rows) / n,
        "RMSE": math.sqrt(sum(x[1] for x in rows) / n),
        "BRIER_START": sum(x[2] for x in rows) / n,
        "BRIER_60": sum(x[3] for x in rows) / n,
        "BRIER_75": sum(x[4] for x in rows) / n,
        "BRIER_90": sum(x[5] for x in rows) / n,
    }


raw = aggregate(raw_scores)
cal = aggregate(cal_scores)

print("TARGET_SEASON:", TARGET_SEASON)
print("CALIBRATION_SEASON:", CALIBRATION_SEASON)
print("ARTIFACT:", artifact_path)
print("TRAINED_THROUGH:", artifact.trained_through.isoformat())
print("N:", raw["N"])

print("\nMETRIC              RAW          CALIBRATED     DELTA")
print("-" * 58)

for key in (
    "MAE",
    "RMSE",
    "BRIER_START",
    "BRIER_60",
    "BRIER_75",
    "BRIER_90",
):
    r = raw[key]
    c = cal[key]
    print(
        f"{key:<18}"
        f"{r:>11.6f} "
        f"{c:>14.6f} "
        f"{(c-r):>11.6f}"
    )
