from __future__ import annotations

from pathlib import Path


ROOT = Path.cwd()

TEAM_ID = (
    "team_406e0d7f-5ce9-5512-bd1c-db012ea76d0a"
)

TOKENS = (
    "previous_season",
    "promoted_teams",
    "MatchObservation",
    "TeamStrengthModel",
    "team_strength_model",
)


# ============================================================
# SOURCE PLUMBING
# ============================================================

print()
print(
    "============================================"
)
print(
    "TEAM STRENGTH INPUT PLUMBING"
)
print(
    "============================================"
)

hits = []

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

    matched = [
        i
        for i, line in enumerate(
            lines,
            start=1,
        )
        if any(
            token in line
            for token in TOKENS
        )
    ]

    if matched:

        hits.append(
            (
                path,
                lines,
                matched,
            )
        )


for path, lines, matched in hits:

    relevant = []

    for line_no in matched:

        line = lines[
            line_no - 1
        ]

        # Avoid dumping unrelated type definitions.
        if (
            "previous_season" in line
            or "promoted_teams" in line
            or "MatchObservation(" in line
            or ".predict(" in line
        ):

            relevant.append(
                line_no
            )

    if not relevant:
        continue

    print()
    print(
        f"### {path}"
    )

    ranges = []

    for n in relevant:

        start = max(
            1,
            n - 10,
        )

        end = min(
            len(lines),
            n + 15,
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


# ============================================================
# FIND RAW TEAM-ID OCCURRENCES IN DATA
# ============================================================

print()
print(
    "============================================"
)
print(
    "RAW DATA FILES CONTAINING TARGET TEAM"
)
print(
    "============================================"
)

SEARCH_ROOTS = (
    ROOT / "data",
    ROOT / "scratch",
)

found = []

for search_root in SEARCH_ROOTS:

    if not search_root.exists():
        continue

    for path in search_root.rglob("*"):

        if (
            not path.is_file()
            or path.suffix.lower()
            not in {
                ".json",
                ".jsonl",
                ".ndjson",
                ".csv",
            }
        ):
            continue

        # Skip obviously large generated outputs
        # unless target string is found quickly.
        try:

            if path.stat().st_size > 25_000_000:
                continue

            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )

        except Exception:
            continue

        if TEAM_ID in text:

            found.append(
                path
            )


for path in found[:40]:

    print(path)


print()
print(
    f"files found: {len(found)}"
)

print()
print(
    "=== END ==="
)
