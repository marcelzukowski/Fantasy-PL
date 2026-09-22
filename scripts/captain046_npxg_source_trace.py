from pathlib import Path
import re


TERMS = (
    "talent_npxg_per90",
    "npxg_per90",
    "0.35",
    "npxg =",
)


for path in sorted(
    Path("src/fpl_engine").rglob("*.py")
):

    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()

    hits = []

    for i, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            term in line
            for term in TERMS
        ):
            hits.append(i)


    if not hits:
        continue


    print()
    print("=" * 80)
    print(path)
    print("=" * 80)

    shown = set()

    for hit in hits:

        start = max(
            1,
            hit - 6,
        )

        end = min(
            len(lines),
            hit + 8,
        )

        for number in range(
            start,
            end + 1,
        ):

            if number in shown:
                continue

            shown.add(number)

            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )
