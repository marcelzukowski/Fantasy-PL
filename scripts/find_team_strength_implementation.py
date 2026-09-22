from pathlib import Path

ROOT = Path("src/fpl_engine")

TOKENS = (
    "attack_strength",
    "defence_strength",
    "effective_sample_size",
    "reliability",
    "expected_home_goals",
    "expected_away_goals",
)

hits = {}

for path in ROOT.rglob("*.py"):

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lines = text.splitlines()

    matched = []

    for i, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            token in line
            for token in TOKENS
        ):

            matched.append(i)

    if matched:

        hits[path] = (
            lines,
            matched,
        )


print()
print(
    "============================================"
)
print(
    "FILES"
)
print(
    "============================================"
)

for path, (_, matched) in hits.items():

    print(
        f"{path} | lines: "
        + ", ".join(
            str(x)
            for x in matched
        )
    )


print()
print(
    "============================================"
)
print(
    "CONTEXT"
)
print(
    "============================================"
)

for path, (
    lines,
    matched,
) in hits.items():

    print()
    print(
        "############################################"
    )
    print(path)
    print(
        "############################################"
    )

    # Merge nearby contexts so output stays compact.
    ranges = []

    for line_no in matched:

        start = max(
            1,
            line_no - 12,
        )

        end = min(
            len(lines),
            line_no + 12,
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


print()
print(
    "=== END ==="
)
