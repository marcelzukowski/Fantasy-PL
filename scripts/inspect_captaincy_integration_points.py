from pathlib import Path


ROOT = Path.cwd()

FILES = (
    Path("src/fpl_engine/decision/captaincy_value.py"),
    Path("src/fpl_engine/decision/chip_squads.py"),
    Path("src/fpl_engine/decision/rolling_transfers.py"),
)


PATTERNS = (
    "captain",
    "captaincy_weight",
    "objective",
    "starter",
    "starting",
    "lineup",
    "xi",
    "GameweekProjection",
    "expected_points",
)


for path in FILES:

    print()
    print(
        "=" * 72
    )
    print(path)
    print(
        "=" * 72
    )

    if not path.exists():
        print("MISSING")
        continue

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    # captaincy_value.py should be short enough
    # to show completely.
    if path.name == "captaincy_value.py":

        for number, line in enumerate(
            lines,
            start=1,
        ):
            print(
                f"{number:4}: {line}"
            )

        continue


    hits = []

    for number, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            pattern.casefold()
            in line.casefold()
            for pattern in PATTERNS
        ):
            hits.append(
                number
            )


    ranges = []

    for hit in hits:

        start = max(
            1,
            hit - 6,
        )

        end = min(
            len(lines),
            hit + 10,
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

        for number in range(
            start,
            end + 1,
        ):
            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )


print()
print(
    "=== END ==="
)
