from pathlib import Path

path = Path(
    "scripts/replay_minutes_v21_fair.py"
)

text = path.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Unique output/report names
# ------------------------------------------------------------

text = text.replace(
    'f"minutes_v21_replay_seed{SEED}_{STAMP}"',
    'f"minutes_v21_fair_seed{SEED}_{STAMP}"',
)

text = text.replace(
    "minutes_v21_replay_report_seed",
    "minutes_v21_fair_report_seed",
)


# ------------------------------------------------------------
# Replace runtime patch block:
# Minutes V2.1 + its OWN frozen calibration artifact.
# ------------------------------------------------------------

old = '''current_module.MinutesModel = (
    HurdleTimeDecayMinutesModel
)

if (
    CurrentPredictionPipeline
    .run
    .__globals__
    .get("MinutesModel")
    is not HurdleTimeDecayMinutesModel
):
    raise RuntimeError(
        "Minutes V2.1 runtime patch "
        "was not applied"
    )

print(
    "[replay] MinutesModel="
    "HurdleTimeDecayMinutesModel"
)

pipeline = CurrentPredictionPipeline(
'''

new = '''current_module.MinutesModel = (
    HurdleTimeDecayMinutesModel
)

if (
    CurrentPredictionPipeline
    .run
    .__globals__
    .get("MinutesModel")
    is not HurdleTimeDecayMinutesModel
):
    raise RuntimeError(
        "Minutes V2.1 runtime patch "
        "was not applied"
    )


# ------------------------------------------------------------
# Load V2.1 calibration before replacing current.py loader.
# Production file is NOT modified.
# ------------------------------------------------------------

import hashlib

V21_CALIBRATION_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "minutes_calibration_v21_2025-26.json"
)

EXPECTED_V21_SHA = (
    "363dc095df15e777178cf8f58c6976fad7012c870cce30245d119fec96c7f68b"
)

if not V21_CALIBRATION_PATH.exists():
    raise RuntimeError(
        f"V2.1 calibration missing: "
        f"{V21_CALIBRATION_PATH}"
    )

actual_v21_sha = hashlib.sha256(
    V21_CALIBRATION_PATH.read_bytes()
).hexdigest()

if actual_v21_sha != EXPECTED_V21_SHA:
    raise RuntimeError(
        "Unexpected V2.1 calibration SHA: "
        f"{actual_v21_sha}"
    )


_original_calibration_loader = (
    current_module.load_minutes_calibration
)

v21_calibration = (
    _original_calibration_loader(
        V21_CALIBRATION_PATH
    )
)


def _load_v21_calibration(
    _production_path,
):
    return v21_calibration


current_module.load_minutes_calibration = (
    _load_v21_calibration
)


if (
    CurrentPredictionPipeline
    .run
    .__globals__
    .get("load_minutes_calibration")
    is not _load_v21_calibration
):
    raise RuntimeError(
        "V2.1 calibration runtime patch "
        "was not applied"
    )


print(
    "[replay] MinutesModel="
    "HurdleTimeDecayMinutesModel"
)

print(
    "[replay] MinutesCalibration="
    f"{V21_CALIBRATION_PATH}"
)

print(
    "[replay] MinutesCalibrationSHA="
    f"{actual_v21_sha}"
)

print(
    "[replay] MinutesCalibrationTrainedThrough="
    f"{v21_calibration.trained_through.isoformat()}"
)


pipeline = CurrentPredictionPipeline(
'''

if old not in text:
    raise RuntimeError(
        "runtime patch block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


path.write_text(
    text,
    encoding="utf-8",
)

print(
    "fair V2.1 replay prepared"
)
