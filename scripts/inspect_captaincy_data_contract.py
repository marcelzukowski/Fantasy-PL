from pathlib import Path


FILES = (
    Path("src/fpl_engine/decision/captaincy.py"),
    Path("src/fpl_engine/decision/projection_adapter.py"),
)


for path in FILES:

    print()
    print("=" * 70)
    print(path)
    print("=" * 70)

    if not path.exists():
        print("MISSING")
        continue

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    patterns = (
        "class ",
        "@dataclass",
        "expected_points",
        "p_appearance",
        "appearance",
        "captain",
        "vice",
        "weighted_",
        "gameweek",
    )

    hits = []

    for number, line in enumerate(
        lines,
        start=1,
    ):
        if any(
            pattern.casefold()
            in line.casefold()
            for pattern in patterns
        ):
            hits.append(number)

    ranges = []

    for hit in hits:

        start = max(1, hit - 4)
        end = min(len(lines), hit + 7)

        if (
            ranges
            and start <= ranges[-1][1] + 1
        ):
            ranges[-1] = (
                ranges[-1][0],
                max(ranges[-1][1], end),
            )
        else:
            ranges.append(
                (start, end)
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
print("=== END ===")
