from pathlib import Path

path = Path(
    "src/fpl_engine/current.py"
)

lines = path.read_text(
    encoding="utf-8-sig",
    errors="replace",
).splitlines()

terms = (
    "talent_history",
    "PlayerPerformanceObservation",
    "to_player_performance",
    "advanced_event",
    "advanced_history",
    "performance_history",
)

hits = []

for i, line in enumerate(
    lines,
    start=1,
):
    if any(
        term in line
        for term in terms
    ):
        hits.append(i)

shown = set()

for hit in hits:

    start = max(
        1,
        hit - 12,
    )

    end = min(
        len(lines),
        hit + 18,
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
