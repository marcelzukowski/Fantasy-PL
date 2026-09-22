from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from fpl_engine.models.minutes.calibration import (
    fit_minutes_calibration,
    load_minutes_calibration,
)


ROOT = Path.cwd()

ARTIFACT = (
    ROOT
    / "data"
    / "processed"
    / "models"
    / "minutes"
    / "minutes_calibration_2025-26.json"
)


# ============================================================
# 1. EXISTING ARTIFACT
# ============================================================

print()
print(
    "============================================"
)
print(
    "EXISTING 2025-26 ARTIFACT"
)
print(
    "============================================"
)

artifact = load_minutes_calibration(
    ARTIFACT
)

print(
    f"path={ARTIFACT}"
)

print(
    f"trained_through="
    f"{artifact.trained_through.isoformat()}"
    if hasattr(
        artifact,
        "trained_through",
    )
    else "trained_through=<not on artifact>"
)

raw = json.loads(
    ARTIFACT.read_text(
        encoding="utf-8"
    )
)

print(
    "top-level keys="
    + ", ".join(
        sorted(
            raw.keys()
        )
    )
)

print(
    json.dumps(
        raw,
        indent=2,
        ensure_ascii=False,
    )[:5000]
)


# ============================================================
# 2. FIND ALL TRAINING CALLERS
# ============================================================

print()
print(
    "============================================"
)
print(
    "FIT_MINUTES_CALIBRATION CALLERS"
)
print(
    "============================================"
)

roots = (
    ROOT / "src",
    ROOT / "scripts",
)

matches = []

for root in roots:

    if not root.exists():
        continue

    for path in root.rglob(
        "*.py"
    ):

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if (
            "fit_minutes_calibration"
            not in text
            and "minutes_calibration_"
            not in text
        ):
            continue

        matches.append(
            path
        )


for path in sorted(
    matches
):

    print()
    print(
        f"--- {path.relative_to(ROOT)} ---"
    )

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    hits = []

    for number, line in enumerate(
        lines,
        start=1,
    ):

        if (
            "fit_minutes_calibration"
            in line
            or "minutes_calibration_"
            in line
            or "MinutesCalibrationPoint"
            in line
        ):

            hits.append(
                number
            )

    ranges = []

    for hit in hits:

        start = max(
            1,
            hit - 8,
        )

        end = min(
            len(lines),
            hit + 14,
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

        print(
            f"[L{start}-L{end}]"
        )

        for number in range(
            start,
            end + 1,
        ):

            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )


# ============================================================
# 3. CALIBRATION IMPLEMENTATION
# ============================================================

print()
print(
    "============================================"
)
print(
    "FIT IMPLEMENTATION"
)
print(
    "============================================"
)

print(
    inspect.getsource(
        fit_minutes_calibration
    )
)


# ============================================================
# 4. ARTIFACT TYPE / FIELDS
# ============================================================

print()
print(
    "============================================"
)
print(
    "ARTIFACT OBJECT"
)
print(
    "============================================"
)

print(
    type(
        artifact
    )
)

for name in (
    "appearance",
    "start",
    "sixty_plus",
    "seventy_five_plus",
    "ninety",
):

    item = getattr(
        artifact,
        name,
    )

    print()
    print(
        name
    )

    for field in (
        "method",
        "trained_through",
        "x",
        "y",
    ):

        if hasattr(
            item,
            field,
        ):

            value = getattr(
                item,
                field,
            )

            if isinstance(
                value,
                tuple,
            ):

                print(
                    f"  {field}: "
                    f"n={len(value)} "
                    f"head={value[:5]} "
                    f"tail={value[-5:]}"
                )

            else:

                print(
                    f"  {field}: {value}"
                )


print()
print(
    "=== END ==="
)
