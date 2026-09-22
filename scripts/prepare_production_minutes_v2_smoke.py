from pathlib import Path


source = Path(
    "scripts/replay_minutes_v21_fair.py"
)

target = Path(
    "scripts/replay_production_minutes_v2_smoke.py"
)


text = source.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Give the smoke run its own namespace.
# ------------------------------------------------------------

text = text.replace(
    "minutes_v21_fair_seed",
    "production_minutes_v2_smoke_seed",
)

text = text.replace(
    "minutes_v21_fair_report_seed",
    "production_minutes_v2_smoke_report_seed",
)


# ------------------------------------------------------------
# REMOVE the Minutes runtime monkey-patch.
#
# Production current.py must choose:
#   minutes_hurdle_v2
#   HurdleTimeDecayMinutesModel
#   V2.1 calibration
#
# by itself.
# ------------------------------------------------------------

start_marker = (
    "current_module = "
    "importlib.import_module("
)

end_marker = (
    "pipeline = CurrentPredictionPipeline("
)


start = text.find(
    start_marker
)

end = text.find(
    end_marker,
    start,
)


if start < 0:
    raise RuntimeError(
        "Minutes runtime patch start "
        "not found"
    )

if end < 0:
    raise RuntimeError(
        "pipeline construction marker "
        "not found"
    )


replacement = '''print(
    "[smoke] Minutes runtime="
    "PRODUCTION_UNPATCHED"
)

'''


text = (
    text[:start]
    + replacement
    + text[end:]
)


# Safety: none of the previous Minutes monkey-patch
# instructions may survive.
for forbidden in (
    "current_module.MinutesModel =",
    "_load_v21_calibration",
    "current_module.load_minutes_calibration =",
    "MinutesCalibrationSHA=",
):

    if forbidden in text:
        raise RuntimeError(
            "Minutes monkey-patch survived: "
            f"{forbidden}"
        )


target.write_text(
    text,
    encoding="utf-8",
)

print(
    f"created {target}"
)

print(
    "Minutes monkey-patch removed"
)
