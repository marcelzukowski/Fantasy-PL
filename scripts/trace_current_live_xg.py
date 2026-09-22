from __future__ import annotations

import inspect
from pathlib import Path

import fpl_engine.current as current


ROOT = Path.cwd()


print()
print(
    "============================================"
)
print(
    "_current_history FULL SOURCE"
)
print(
    "============================================"
)

print(
    inspect.getsource(
        current._current_history
    )
)


print()
print(
    "============================================"
)
print(
    "EXPECTED_GOALS / EVENT_LIVE REFERENCES"
)
print(
    "============================================"
)


tokens = (
    "expected_goals",
    "event_live",
    "live=",
    ".event_live",
)


for path in (
    ROOT
    / "src"
    / "fpl_engine"
).rglob("*.py"):

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lines = text.splitlines()

    hits = [
        i
        for i, line in enumerate(
            lines,
            start=1,
        )
        if any(
            token in line
            for token in tokens
        )
    ]

    if not hits:
        continue

    print()
    print(
        f"### {path}"
    )

    ranges = []

    for n in hits:

        start = max(
            1,
            n - 5,
        )

        end = min(
            len(lines),
            n + 8,
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


print()
print(
    "=== END ==="
)
