from pathlib import Path
import re


ROOTS = (
    Path("src"),
    Path("scripts"),
)

PATTERNS = (
    "optimize_rolling_free_transfers(",
    "optimize_unlimited_squad(",
    "adapt_player_projections(",
    "player_projections.json",
    "minutes.json",
)


for root in ROOTS:

    if not root.exists():
        continue

    for path in sorted(
        root.rglob("*.py")
    ):

        text = path.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )

        lines = text.splitlines()

        hits = []

        for number, line in enumerate(
            lines,
            start=1,
        ):

            if any(
                pattern in line
                for pattern in PATTERNS
            ):
                hits.append(number)

        if not hits:
            continue


        print()
        print("=" * 76)
        print(path)
        print("=" * 76)


        ranges = []

        for hit in hits:

            start = max(
                1,
                hit - 10,
            )

            end = min(
                len(lines),
                hit + 22,
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
print("=== END ===")
