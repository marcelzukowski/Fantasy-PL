from pathlib import Path


TARGETS = {
    "def _shrunk_rate",
    "eligible_talent_history",
    "PlayerTalentModel(",
    "PlayerTalentModelV2(",
    "talent_model.predict",
    ".predict(",
    "PlayerPerformanceObservation(",
    "to_player_performance(",
}


FILES = [
    Path("src/fpl_engine/models/player_talent/model.py"),
    Path("src/fpl_engine/models/player_talent/v2.py"),
    Path("src/fpl_engine/features/player_talent_dataset.py"),
    Path("src/fpl_engine/current.py"),
]


for path in FILES:

    if not path.exists():
        continue

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
            for term in TARGETS
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
            hit - 10,
        )

        end = min(
            len(lines),
            hit + 18,
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
