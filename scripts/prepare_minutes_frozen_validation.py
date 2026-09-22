from __future__ import annotations

from pathlib import Path

source = Path(
    "scripts/export_minutes_calibration.py"
)

target = Path(
    "scripts/evaluate_minutes_frozen_prior_season.py"
)

text = source.read_text(
    encoding="utf-8"
)


# ============================================================
# 1. IMPORTS
# ============================================================

text = text.replace(
    "import argparse\n",
    """import argparse
import math
from statistics import mean, median
""",
    1,
)


old = """from fpl_engine.models.minutes.calibration import (
    MinutesCalibrationPoint,
    fit_minutes_calibration,
    save_minutes_calibration,
)
"""

new = """from fpl_engine.models.minutes.calibration import (
    MinutesCalibrationPoint,
    fit_minutes_calibration,
    save_minutes_calibration,
    load_minutes_calibration,
)

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)
"""

if old not in text:
    raise RuntimeError(
        "calibration import block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# 2. ADD METRIC HELPERS
# ============================================================

marker = "def main() -> None:\n"

helpers = r'''
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


'''

if marker not in text:
    raise RuntimeError(
        "main marker not found"
    )

text = text.replace(
    marker,
    helpers + marker,
    1,
)


# ============================================================
# 3. REPLACE MODEL INITIALIZATION
# ============================================================

old = """    minute_model = MinutesModel()
    calibration_points = []
"""

new = """    v1_model = MinutesModel()

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
"""

if old not in text:
    raise RuntimeError(
        "model initialization block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ============================================================
# 4. REPLACE PER-PLAYER RAW CALIBRATION POINT CREATION
#    WITH FROZEN-CALIBRATOR V1/V2.1 SCORING
# ============================================================

start_marker = """                    raw = minute_model.predict(
                        prior_minutes,
                        context,
                    )
"""

start = text.find(
    start_marker
)

if start < 0:
    raise RuntimeError(
        "raw prediction block start not found"
    )

end_marker = """                    )

    if len(calibration_points) < 200:
"""

# We need the final close of calibration_points.append(),
# immediately before the exporter finalization section.
final_section = text.find(
    "    if len(calibration_points) < 200:",
    start,
)

if final_section < 0:
    raise RuntimeError(
        "export finalization marker not found"
    )


# Locate the beginning of the raw block and replace everything
# from it up to the final exporter section.  The surrounding
# fixture/player loops stay exactly as in the frozen exporter.
#
# First find the end of the append block by walking backwards
# from final_section to the last indented close.
segment = text[
    start:final_section
]

needle = """                    calibration_points.append(
                        MinutesCalibrationPoint(
"""

append_start = segment.find(
    needle
)

if append_start < 0:
    raise RuntimeError(
        "calibration append block not found"
    )


# The exporter append block terminates with:
#
#                         )
#                     )
#
append_tail = """                        )
                    )
"""

append_end = segment.find(
    append_tail,
    append_start,
)

if append_end < 0:
    raise RuntimeError(
        "calibration append end not found"
    )

append_end += len(
    append_tail
)

replace_end = (
    start
    + append_end
)


replacement = r'''                    ordered_prior = sorted(
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
'''

text = (
    text[:start]
    + replacement
    + text[replace_end:]
)


# ============================================================
# 5. REPLACE EXPORT FINALIZATION WITH COMPACT REPORT
# ============================================================

final_start = text.find(
    "    if len(calibration_points) < 200:"
)

if final_start < 0:
    raise RuntimeError(
        "final exporter block not found"
    )

footer = '\n\nif __name__ == "__main__":'

final_end = text.find(
    footer,
    final_start,
)

if final_end < 0:
    raise RuntimeError(
        "script footer not found"
    )


report_block = r'''    if not score_rows:
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
'''

text = (
    text[:final_start]
    + report_block
    + text[final_end:]
)


target.write_text(
    text,
    encoding="utf-8",
)

print(
    f"created {target}"
)
