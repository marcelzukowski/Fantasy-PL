from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path.cwd()

FILES = (
    ROOT / "src" / "fpl_engine" / "current.py",
    ROOT / "src" / "fpl_engine" / "current_history.py",
)


TOKENS = (
    "MatchObservation",
    "current_history",
    "build_current_history",
    "load_current_history",
    "matches.extend",
    "matches +=",
    "history.matches",
    "team_strength",
    "team_model",
    "TeamStrengthModel",
    "previous_season",
    "promoted_teams",
)


for path in FILES:

    print()
    print(
        "============================================================"
    )
    print(path)
    print(
        "============================================================"
    )

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lines = text.splitlines()

    hits = []

    for i, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            token in line
            for token in TOKENS
        ):

            hits.append(i)


    ranges = []

    for line_no in hits:

        start = max(
            1,
            line_no - 8,
        )

        end = min(
            len(lines),
            line_no + 12,
        )

        if (
            ranges
            and start <= ranges[-1][1] + 1
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
                f"{n:4}: {lines[n-1]}"
            )


print()
print(
    "============================================================"
)
print(
    "FUNCTION MAP"
)
print(
    "============================================================"
)


for path in FILES:

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    tree = ast.parse(text)

    print()
    print(path.name)

    for node in ast.walk(tree):

        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            continue

        source = ast.get_source_segment(
            text,
            node,
        ) or ""

        if any(
            token in source
            for token in (
                "MatchObservation",
                "current_history",
                "TeamStrengthModel",
                "team_strength",
            )
        ):

            print(
                f"  {node.name:<40} "
                f"L{node.lineno}-"
                f"L{getattr(node, 'end_lineno', '?')}"
            )


print()
print(
    "=== END ==="
)
