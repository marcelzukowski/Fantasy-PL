from pathlib import Path

path = Path(
    "scripts/replay_minutes_v21.py"
)

text = path.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Import V2 model + importlib
# ------------------------------------------------------------

marker = "from pathlib import Path\n"

addition = '''from pathlib import Path
import importlib

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)
'''

if (
    "HurdleTimeDecayMinutesModel"
    not in text
):

    if marker not in text:
        raise RuntimeError(
            "path import marker not found"
        )

    text = text.replace(
        marker,
        addition,
        1,
    )


# ------------------------------------------------------------
# Give replay its own output namespace
# ------------------------------------------------------------

text = text.replace(
    'f"captain_xg_replay_{STAMP}"',
    'f"minutes_v21_replay_seed{SEED}_{STAMP}"',
)

text = text.replace(
    "captain_xg_ab_report_seed",
    "minutes_v21_replay_report_seed",
)

text = text.replace(
    "captain_xg_ab_report.txt",
    "minutes_v21_replay_report.txt",
)


# ------------------------------------------------------------
# Runtime-only MinutesModel substitution.
#
# CurrentPredictionPipeline methods resolve MinutesModel
# through fpl_engine.current globals, so patch only this
# Python process. No production source file is modified.
# ------------------------------------------------------------

needle = '''pipeline = CurrentPredictionPipeline(
'''

patch = '''current_module = importlib.import_module(
    CurrentPredictionPipeline.__module__
)

if not hasattr(
    current_module,
    "MinutesModel",
):
    raise RuntimeError(
        "fpl_engine.current has no "
        "MinutesModel global"
    )

current_module.MinutesModel = (
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

if needle not in text:
    raise RuntimeError(
        "pipeline construction marker "
        "not found"
    )

text = text.replace(
    needle,
    patch,
    1,
)


path.write_text(
    text,
    encoding="utf-8",
)

print(
    "V2.1 replay copy prepared"
)
