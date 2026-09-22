from __future__ import annotations

import argparse
import math
from statistics import mean, median

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
    load_minutes_calibration,
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



def _clip_probability(value: float) -> float:
    return min(
        1.0 - 1e-7,
        max(
            1e-7,
            float(value),
        ),
    )


def _logloss(
    probability: float,
    outcome: bool,
) -> float:

    p = _clip_probability(
        probability
    )

    y = float(
        outcome
    )

    return -(
        y * math.log(p)
        + (1.0 - y)
        * math.log(1.0 - p)
    )


def _score_prediction(
    *,
    model_name,
    gw,
    regular_three,
    prediction,
    actual,
):

    minutes = float(
        actual.minutes
    )

    appeared = bool(
        actual.appeared
    )

    started = bool(
        actual.started
    )

    return {
        "model": model_name,
        "gw": int(gw),
        "regular_three": bool(
            regular_three
        ),

        "ae": abs(
            float(
                prediction.expected_minutes
            )
            - minutes
        ),

        "se": (
            float(
                prediction.expected_minutes
            )
            - minutes
        ) ** 2,

        "app_brier": (
            float(
                prediction.p_appearance
            )
            - float(appeared)
        ) ** 2,

        "app_log": _logloss(
            prediction.p_appearance,
            appeared,
        ),

        "start_brier": (
            float(
                prediction.p_start
            )
            - float(started)
        ) ** 2,

        "start_log": _logloss(
            prediction.p_start,
            started,
        ),

        "b60": (
            float(
                prediction.p60
            )
            - float(
                minutes >= 60
            )
        ) ** 2,

        "b75": (
            float(
                prediction.p75
            )
            - float(
                minutes >= 75
            )
        ) ** 2,

        "b90": (
            float(
                prediction.p90
            )
            - float(
                minutes >= 90
            )
        ) ** 2,
    }


def _aggregate(rows):

    if not rows:
        raise RuntimeError(
            "empty score group"
        )

    return {
        "n": len(rows),

        "mae": mean(
            row["ae"]
            for row in rows
        ),

        "rmse": math.sqrt(
            mean(
                row["se"]
                for row in rows
            )
        ),

        "median_ae": median(
            row["ae"]
            for row in rows
        ),

        "app_brier": mean(
            row["app_brier"]
            for row in rows
        ),

        "app_log": mean(
            row["app_log"]
            for row in rows
        ),

        "start_brier": mean(
            row["start_brier"]
            for row in rows
        ),

        "start_log": mean(
            row["start_log"]
            for row in rows
        ),

        "b60": mean(
            row["b60"]
            for row in rows
        ),

        "b75": mean(
            row["b75"]
            for row in rows
        ),

        "b90": mean(
            row["b90"]
            for row in rows
        ),
    }


def _material_gate(
    incumbent,
    challenger,
):

    old_core = (
        incumbent["start_brier"]
        + incumbent["b60"]
    ) / 2.0

    new_core = (
        challenger["start_brier"]
        + challenger["b60"]
    ) / 2.0

    passed = (
        (
            challenger["mae"]
            < incumbent["mae"] * 0.99
            and new_core <= old_core
        )
        or
        (
            new_core
            < old_core * 0.98
            and challenger["mae"]
            <= incumbent["mae"]
        )
    )

    return (
        passed,
        old_core,
        new_core,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
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

    v1_model = MinutesModel()

    v21_model = (
        HurdleTimeDecayMinutesModel()
    )

    prior_season = "2024-25"

    v1_calibration_path = (
        ROOT
        / "data"
        / "processed"
        / "models"
        / "minutes"
        / f"minutes_calibration_{prior_season}.json"
    )

    v21_calibration_path = (
        ROOT
        / "scratch"
        / "decision"
        / f"minutes_calibration_v21_{prior_season}.json"
    )

    if not v1_calibration_path.exists():
        raise RuntimeError(
            f"missing V1 calibration: "
            f"{v1_calibration_path}"
        )

    if not v21_calibration_path.exists():
        raise RuntimeError(
            f"missing V2.1 calibration: "
            f"{v21_calibration_path}"
        )

    v1_calibration = (
        load_minutes_calibration(
            v1_calibration_path
        )
    )

    v21_calibration = (
        load_minutes_calibration(
            v21_calibration_path
        )
    )

    score_rows = []

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

                    ordered_prior = sorted(
                        prior_minutes,
                        key=lambda row: (
                            row.kickoff,
                            row.fixture_id,
                        ),
                    )

                    recent_three = (
                        ordered_prior[-3:]
                    )

                    regular_three = (
                        len(recent_three) == 3
                        and all(
                            row.appeared
                            and row.started
                            for row
                            in recent_three
                        )
                    )


                    v1_prediction = (
                        v1_model.predict(
                            prior_minutes,
                            context,
                            calibration=(
                                v1_calibration
                            ),
                        )
                    )

                    v21_prediction = (
                        v21_model.predict(
                            prior_minutes,
                            context,
                            calibration=(
                                v21_calibration
                            ),
                        )
                    )


                    score_rows.append(
                        _score_prediction(
                            model_name="V1",
                            gw=gw,
                            regular_three=(
                                regular_three
                            ),
                            prediction=(
                                v1_prediction
                            ),
                            actual=actual,
                        )
                    )

                    score_rows.append(
                        _score_prediction(
                            model_name="V2.1",
                            gw=gw,
                            regular_three=(
                                regular_three
                            ),
                            prediction=(
                                v21_prediction
                            ),
                            actual=actual,
                        )
                    )

    if not score_rows:
        raise RuntimeError(
            "no validation rows produced"
        )


    groups = {
        "ALL": (
            lambda row: True
        ),

        "EARLY_GW1_8": (
            lambda row:
            row["gw"] <= 8
        ),

        "REGULAR_3_OF_3": (
            lambda row:
            row["regular_three"]
        ),

        "EARLY_REGULAR": (
            lambda row:
            row["gw"] <= 8
            and row["regular_three"]
        ),
    }


    results = {}

    for group_name, selector in (
        groups.items()
    ):

        for model_name in (
            "V1",
            "V2.1",
        ):

            selected = [
                row
                for row in score_rows
                if (
                    row["model"]
                    == model_name
                    and selector(row)
                )
            ]

            results[
                (
                    group_name,
                    model_name,
                )
            ] = _aggregate(
                selected
            )


    lines = []

    lines.append(
        "============================================================"
    )

    lines.append(
        "MINUTES V1 vs V2.1 | "
        "FROZEN PRIOR-SEASON CALIBRATION"
    )

    lines.append(
        "============================================================"
    )

    lines.append(
        f"target season={season}"
    )

    lines.append(
        "calibration season=2024-25"
    )

    lines.append(
        "NO in-season calibration refit"
    )

    lines.append(
        "STRICT snapshots + historical availability"
    )

    lines.append("")


    for group_name in (
        "ALL",
        "EARLY_GW1_8",
        "REGULAR_3_OF_3",
        "EARLY_REGULAR",
    ):

        lines.append(
            f"=== {group_name} ==="
        )

        lines.append(
            f"{'MODEL':<8}"
            f"{'N':>8}"
            f"{'MAE':>9}"
            f"{'RMSE':>9}"
            f"{'MEDAE':>9}"
            f"{'APP_B':>9}"
            f"{'APP_L':>9}"
            f"{'START_B':>10}"
            f"{'B60':>9}"
            f"{'B75':>9}"
            f"{'B90':>9}"
        )


        for model_name in (
            "V1",
            "V2.1",
        ):

            row = results[
                (
                    group_name,
                    model_name,
                )
            ]

            lines.append(
                f"{model_name:<8}"
                f"{row['n']:>8}"
                f"{row['mae']:>9.3f}"
                f"{row['rmse']:>9.3f}"
                f"{row['median_ae']:>9.3f}"
                f"{row['app_brier']:>9.4f}"
                f"{row['app_log']:>9.4f}"
                f"{row['start_brier']:>10.4f}"
                f"{row['b60']:>9.4f}"
                f"{row['b75']:>9.4f}"
                f"{row['b90']:>9.4f}"
            )


        old = results[
            (
                group_name,
                "V1",
            )
        ]

        new = results[
            (
                group_name,
                "V2.1",
            )
        ]

        passed, old_core, new_core = (
            _material_gate(
                old,
                new,
            )
        )


        lines.append(
            "DELTA "
            f"MAE={new['mae']-old['mae']:+.3f} "
            f"APP_B={new['app_brier']-old['app_brier']:+.4f} "
            f"START_B={new['start_brier']-old['start_brier']:+.4f} "
            f"B60={new['b60']-old['b60']:+.4f} "
            f"CORE={new_core-old_core:+.4f}"
        )

        lines.append(
            "MATERIAL_GATE="
            + (
                "PASS"
                if passed
                else "FAIL"
            )
        )

        lines.append("")


    all_old = results[
        (
            "ALL",
            "V1",
        )
    ]

    all_new = results[
        (
            "ALL",
            "V2.1",
        )
    ]

    all_pass, _, _ = (
        _material_gate(
            all_old,
            all_new,
        )
    )


    early_old = results[
        (
            "EARLY_GW1_8",
            "V1",
        )
    ]

    early_new = results[
        (
            "EARLY_GW1_8",
            "V2.1",
        )
    ]

    early_pass, _, _ = (
        _material_gate(
            early_old,
            early_new,
        )
    )


    lines.append(
        "============================================================"
    )

    lines.append(
        "DEPLOYMENT-PROTOCOL SUMMARY"
    )

    lines.append(
        "============================================================"
    )

    lines.append(
        "FULL_SEASON_GATE="
        + (
            "PASS"
            if all_pass
            else "FAIL"
        )
    )

    lines.append(
        "EARLY_GW1_8_GATE="
        + (
            "PASS"
            if early_pass
            else "FAIL"
        )
    )

    lines.append("")

    lines.append(
        "NOTE: this is production-protocol validation, "
        "not a pristine untouched holdout."
    )

    lines.append("")

    lines.append(
        "=== END ==="
    )


    report = "\n".join(
        lines
    )

    destination = (
        ROOT
        / "scratch"
        / "decision"
        / "minutes_v21_frozen_prior_validation_2025-26.txt"
    )

    destination.write_text(
        report + "\n",
        encoding="utf-8",
    )

    print(
        report
    )


if __name__ == "__main__":
    main()
