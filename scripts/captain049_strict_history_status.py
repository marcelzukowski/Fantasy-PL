from pathlib import Path
import json


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


print("=== RUN WARNINGS / HISTORY STATUS ===")

needles = (
    "Historical STRICT",
    "No materialized prior-season STRICT",
    "history_versions",
    "source_versions",
    "Current non-penalty xG",
)


for path in sorted(
    RUN.rglob("*")
):
    if (
        not path.is_file()
        or path.suffix.lower()
        not in {".json", ".txt", ".log"}
    ):
        continue

    try:
        text = path.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )
    except Exception:
        continue

    hits = [
        needle
        for needle in needles
        if needle in text
    ]

    if hits:
        print()
        print(path.name)

        for needle in hits:
            print(" ", needle)


print()
print("=== current_history.py WIRING ===")

path = Path(
    "src/fpl_engine/current_history.py"
)

lines = path.read_text(
    encoding="utf-8-sig",
    errors="replace",
).splitlines()


terms = (
    "def load_strict_historical_context",
    "PlayerPerformanceObservation",
    "talent[",
    "talent=",
    "player_id",
    "npxg",
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
