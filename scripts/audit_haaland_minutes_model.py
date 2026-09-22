from __future__ import annotations

import inspect
import json
from pathlib import Path

from fpl_engine.models.minutes import (
    MinutesModel,
)

try:
    from fpl_engine.models.minutes import (
        MinutesConfig,
    )
except ImportError:
    MinutesConfig = None


ROOT = Path.cwd()

RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "captain_xg_replay_20260912T191754Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

TARGETS = {
    "Haaland":
        "ply_f5b0178d-f837-5554-9cd4-723b48c97826",
    "B.Fernandes":
        "ply_e12222fa-6342-5394-a9ee-d1d9e71e96a5",
    "Palmer":
        "ply_19d5ba62-d425-51e6-b30b-de90a5adf4e8",
    "Szoboszlai":
        "ply_3db58329-d31f-5ed9-9e52-a2ef02ad8d2c",
}


def rows(path):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(raw, list):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "minutes",
        "fixtures",
    ):

        value = raw.get(key)

        if isinstance(value, list):
            return value

    raise RuntimeError(
        f"cannot resolve rows: {path}"
    )


# ============================================================
# CONFIG
# ============================================================

print()
print(
    "============================================"
)
print(
    "MINUTES CONFIG"
)
print(
    "============================================"
)

model = MinutesModel()

config = getattr(
    model,
    "config",
    None,
)

print(
    repr(config)
)


# ============================================================
# RELEVANT MODEL SOURCE
# ============================================================

print()
print(
    "============================================"
)
print(
    "MINUTES MODEL RELEVANT SOURCE"
)
print(
    "============================================"
)

source = inspect.getsource(
    MinutesModel
)

lines = source.splitlines()

tokens = (
    "appearance",
    "p_appearance",
    "p_start",
    "expected_minutes",
    "prior",
    "history",
    "sample",
    "weight",
    "start",
    "minutes",
    "availability",
)

hits = []

for i, line in enumerate(
    lines,
    start=1,
):

    if any(
        token in line.casefold()
        for token in tokens
    ):

        hits.append(i)


ranges = []

for n in hits:

    start = max(
        1,
        n - 3,
    )

    end = min(
        len(lines),
        n + 4,
    )

    if (
        ranges
        and start
        <= ranges[-1][1] + 1
    ):

        ranges[-1] = (
            ranges[-1][0],
            max(
                ranges[-1][1],
                end,
            ),
        )

    else:

        ranges.append(
            (
                start,
                end,
            )
        )


for start, end in ranges:

    print()
    print(
        f"--- L{start}-L{end} ---"
    )

    for n in range(
        start,
        end + 1,
    ):

        print(
            f"{n:4}: "
            f"{lines[n-1]}"
        )


# ============================================================
# ARTIFACT TRACE GW4-GW9
# ============================================================

print()
print(
    "============================================"
)
print(
    "FIXED RUN | MINUTES GW4-GW9"
)
print(
    "============================================"
)

fixtures = {
    str(row["fixture_id"]): row
    for row in rows(
        RUN
        / "fixture_horizon.json"
    )
}

minutes = rows(
    RUN
    / "minutes.json"
)


print(
    f"{'PLAYER':<16}"
    f"{'GW':>4}"
    f"{'MIN':>9}"
    f"{'P_APP':>9}"
    f"{'P_START':>9}"
)

for name, pid in TARGETS.items():

    found = []

    for row in minutes:

        if str(
            row.get(
                "player_id"
            )
        ) != pid:
            continue

        fixture = fixtures.get(
            str(
                row.get(
                    "fixture_id"
                )
            )
        )

        if fixture is None:
            continue

        gw = (
            fixture.get(
                "target_gameweek"
            )
            or fixture.get(
                "gameweek"
            )
            or fixture.get(
                "event"
            )
        )

        if gw is None:
            continue

        gw = int(gw)

        if 4 <= gw <= 9:

            found.append(
                (
                    gw,
                    row,
                )
            )

    for gw, row in sorted(
        found,
        key=lambda x: x[0],
    ):

        expected = (
            row.get(
                "expected_minutes"
            )
        )

        p_app = (
            row.get(
                "p_appearance"
            )
        )

        p_start = (
            row.get(
                "p_start"
            )
        )

        print(
            f"{name:<16}"
            f"{gw:>4}"
            f"{float(expected):>9.2f}"
            f"{float(p_app):>9.3f}"
            f"{float(p_start):>9.3f}"
        )


print()
print(
    "=== END ==="
)
