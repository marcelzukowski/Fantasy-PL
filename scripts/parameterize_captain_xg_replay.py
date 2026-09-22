from pathlib import Path

path = Path(
    "scripts/replay_captain_xg_ab.py"
)

text = path.read_text(
    encoding="utf-8"
)

# ------------------------------------------------------------
# Add os import
# ------------------------------------------------------------

if "import os\n" not in text:

    text = text.replace(
        "import json\n",
        "import json\nimport os\n",
        1,
    )


# ------------------------------------------------------------
# Parameter block
# ------------------------------------------------------------

old = '''OLD_RUN = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / "20260912T100351Z"
)
'''

new = '''SEED = int(
    os.environ[
        "CAPTAIN_REPLAY_SEED"
    ]
)

OLD_RUN_ID = os.environ[
    "CAPTAIN_OLD_RUN_ID"
]

OLD_RUN = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / OLD_RUN_ID
)
'''

if old not in text:

    raise RuntimeError(
        "OLD_RUN block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ------------------------------------------------------------
# Unique report per seed
# ------------------------------------------------------------

old = '''REPORT_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "captain_xg_ab_report.txt"
)
'''

new = '''REPORT_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / f"captain_xg_ab_report_seed{SEED}.txt"
)
'''

if old not in text:

    raise RuntimeError(
        "REPORT_PATH block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ------------------------------------------------------------
# Seed
# ------------------------------------------------------------

old = '''        random_seed=42,
'''

new = '''        random_seed=SEED,
'''

if old not in text:

    raise RuntimeError(
        "random_seed=42 block not found"
    )

text = text.replace(
    old,
    new,
    1,
)


# ------------------------------------------------------------
# Header
# ------------------------------------------------------------

old = '''lines.append(
    "same pre-deadline snapshots | 256 sims | seed 42"
)
'''

new = '''lines.append(
    f"same pre-deadline snapshots | 256 sims | seed {SEED}"
)
'''

if old not in text:

    raise RuntimeError(
        "header seed block not found"
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
    "parameterized replay script"
)
