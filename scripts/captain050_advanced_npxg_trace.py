from pathlib import Path


TERMS = (
    "TemporalEventRecord",
    "to_player_performance",
    "derived_npxg",
    "penalty_xg",
    "advanced_event_data",
)


for base in (
    Path("src"),
    Path("scripts"),
):

    for path in sorted(
        base.rglob("*.py")
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
                hit - 8,
            )

            end = min(
                len(lines),
                hit + 12,
            )

            for n in range(
                start,
                end + 1,
            ):

                if n in shown:
                    continue

                shown.add(n)

                print(
                    f"{n:4}: "
                    f"{lines[n - 1]}"
                )
