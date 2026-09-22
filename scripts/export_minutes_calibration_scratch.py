from __future__ import annotations

import argparse

import json
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
    MinutesCalibrationPoint,
    fit_minutes_calibration,
    save_minutes_calibration,
)

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)

# Reuse the STRICT runner's frozen source-loading helpers.
import importlib.util

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "strict_runner",
    ROOT / "scripts" / "run_strict_model_backtest.py",
)
strict = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(strict)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument(
        "--model",
        choices=("v1", "v21"),
        required=True,
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    args = parser.parse_args()

    season = args.season

    # STRICT helper functions use the runner's module-level SEASON.
    strict.SEASON = season

    interim = ROOT / "data" / "interim" / "strict" / season

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

    # Same provider -> canonical player identity rule as STRICT runner.
    first_elements = {}
    for gw in sorted(snapshots):
        for element in snapshots[gw]["payload"]["elements"]:
            first_elements.setdefault(int(element["id"]), element)

    player_ids = {}
    seen_keys = {}

    for element_id, element in first_elements.items():
        try:
            identity_key = official_fpl_player_identity_key(element)
        except IdentityResolutionError as exc:
            raise RuntimeError(
                f"Official FPL player {element_id} lacks safe identity: {exc}"
            ) from exc

        previous = seen_keys.get(identity_key)
        if previous is not None and previous != element_id:
            raise RuntimeError(
                f"Player-code collision: {previous} and "
                f"{element_id} share {identity_key}"
            )

        seen_keys[identity_key] = element_id
        player_ids[element_id] = strict._identifier(
            "player", identity_key
        )

    outcomes["fixture_key"] = (
        outcomes["fixture"].astype(int).astype(str)
    )
    outcomes["kickoff_dt"] = pd.to_datetime(
        outcomes["kickoff_time"], utc=True
    )

    minutes_history = defaultdict(list)
    outcome_by_fixture_player = {}

    # Build the same immutable outcome history used by STRICT.
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

            observation = MinutesObservation(
                pid,
                fixture_ids[fixture_key],
                kickoff,
                known_at,
                int(row["minutes"]),
                bool(int(row["starts"])),
            )

            minutes_history[element_id].append(observation)
            outcome_by_fixture_player[
                (fixture_key, element_id)
            ] = observation

    positions = {
        1: "GK",
        2: "DEF",
        3: "MID",
        4: "FWD",
    }

    if args.model == "v1":
        minute_model = MinutesModel()
    else:
        minute_model = HurdleTimeDecayMinutesModel()

    calibration_points = []

    for gw in sorted(snapshots):
        snap = snapshots[gw]
        payload = snap["payload"]

        at = snap["prediction_timestamp"]
        snapshot_at = snap["snapshot_timestamp"]

        # One fixture state as known at this exact prediction GW.
        current_states = states[
            (states["prediction_gameweek"] == gw)
            & (states["scheduled_gameweek"] == gw)
        ]

        element_by_team = defaultdict(list)
        for element in payload["elements"]:
            element_by_team[str(element["team"])].append(element)

        for state in current_states.itertuples():
            fixture_key = str(state.provider_fixture_id)

            # Work on both teams in this fixture.
            for provider_team in (
                str(state.provider_home_team_id),
                str(state.provider_away_team_id),
            ):
                for element in element_by_team.get(
                    provider_team, []
                ):
                    element_id = int(element["id"])

                    if element_id not in player_ids:
                        continue

                    element_type = int(
                        element.get("element_type", 0)
                    )
                    if element_type not in positions:
                        continue

                    actual = outcome_by_fixture_player.get(
                        (fixture_key, element_id)
                    )
                    if actual is None:
                        continue

                    player_id = player_ids[element_id]

                    prior_minutes = [
                        row
                        for row in minutes_history[element_id]
                        if row.known_at <= at
                        and row.fixture_id
                        != state.canonical_fixture_id
                    ]

                    probability, definitely_unavailable = (
                        strict._availability(element)
                    )

                    context = MinutesContext(
                        player_id,
                        state.canonical_fixture_id,
                        at,
                        position=positions[element_type],
                        availability_probability=probability,
                        availability_known_at=snapshot_at,
                        availability_confidence=(
                            1.0
                            if probability is not None
                            else None
                        ),
                        definitely_unavailable=(
                            definitely_unavailable
                        ),
                        signals=(
                            MinutesFeatureSignal(
                                "status",
                                element.get("status"),
                                snapshot_at,
                                snapshot_at,
                                "fplcache",
                                source_snapshot_timestamp=(
                                    snapshot_at
                                ),
                            ),
                        ),
                    )

                    raw = minute_model.predict(
                        prior_minutes,
                        context,
                    )

                    calibration_points.append(
                        MinutesCalibrationPoint(
                            raw.p_appearance,
                            raw.p_start,
                            raw.p60,
                            raw.p75,
                            raw.p90,
                            actual.appeared,
                            actual.started,
                            actual.minutes,
                            actual.known_at,
                        )
                    )

    if len(calibration_points) < 200:
        raise RuntimeError(
            f"Only {len(calibration_points)} calibration "
            "points; need at least 200."
        )

    cutoff = max(
        point.known_at for point in calibration_points
    )

    artifact = fit_minutes_calibration(
        calibration_points,
        training_cutoff=cutoff,
        method="platt",
    )

    destination = Path(
        args.output
    ).resolve()

    save_minutes_calibration(
        artifact,
        destination,
    )

    print(
        "MINUTES_CALIBRATION_ARTIFACT="
        f"{destination}"
    )
    print(
        "MINUTES_CALIBRATION_POINTS="
        f"{len(calibration_points)}"
    )
    print(
        "MINUTES_CALIBRATION_TRAINED_THROUGH="
        f"{artifact.trained_through.isoformat()}"
    )


if __name__ == "__main__":
    main()
