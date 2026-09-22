from pathlib import Path

FILES = (
    Path(
        "src/fpl_engine/models/"
        "player_talent/model.py"
    ),
    Path(
        "src/fpl_engine/models/"
        "player_talent/v2.py"
    ),
    Path(
        "src/fpl_engine/models/"
        "events/model.py"
    ),
    Path(
        "src/fpl_engine/current.py"
    ),
)

TERMS = (
    "class PlayerTalentPrediction",
    "PlayerTalentPrediction(",
    "class PlayerFixtureInput",
    "PlayerFixtureInput(",
    "asdict(",
    "talent_outputs",
    "player_talent",
    "model_dump",
)

for path in FILES:

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
            hit - 10,
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
