from pathlib import Path

source = Path(
    "scripts/export_minutes_calibration.py"
)

target = Path(
    "scripts/export_minutes_calibration_scratch.py"
)

text = source.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Add V2.1 import
# ------------------------------------------------------------

marker = (
    "# Reuse the STRICT runner's "
    "frozen source-loading helpers."
)

addition = '''from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)

'''

if (
    "HurdleTimeDecayMinutesModel"
    not in text
):

    if marker not in text:
        raise RuntimeError(
            "import insertion marker not found"
        )

    text = text.replace(
        marker,
        addition + marker,
        1,
    )


# ------------------------------------------------------------
# Add CLI model/output arguments
# ------------------------------------------------------------

old = '''    parser.add_argument("--season", required=True)
    args = parser.parse_args()
'''

new = '''    parser.add_argument("--season", required=True)
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
'''

if old not in text:
    raise RuntimeError(
        "argparse block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ------------------------------------------------------------
# Select Minutes model
# ------------------------------------------------------------

old = '''    minute_model = MinutesModel()
    calibration_points = []
'''

new = '''    if args.model == "v1":
        minute_model = MinutesModel()
    else:
        minute_model = HurdleTimeDecayMinutesModel()

    calibration_points = []
'''

if old not in text:
    raise RuntimeError(
        "MinutesModel construction "
        "block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ------------------------------------------------------------
# Redirect artifact away from production
# ------------------------------------------------------------

old = '''    destination = (
        ROOT
        / "data"
        / "processed"
        / "models"
        / "minutes"
        / f"minutes_calibration_{season}.json"
    )
'''

new = '''    destination = Path(
        args.output
    ).resolve()
'''

if old not in text:
    raise RuntimeError(
        "destination block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


target.write_text(
    text,
    encoding="utf-8",
)

print(
    f"created {target}"
)
