from pathlib import Path
import json


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/20260912T100351Z"
)


def rows(path):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(raw, list):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "projections",
        "minutes",
    ):
        value = raw.get(key)

        if isinstance(value, list):
            return value

    raise RuntimeError(
        f"cannot resolve rows: {path}"
    )


players = rows(
    RUN / "current_players.json"
)

haaland = next(
    row
    for row in players
    if row.get("display_name") == "Haaland"
)

pid = str(
    haaland["player_id"]
)


projections = rows(
    RUN / "player_projections.json"
)

projection = next(
    row
    for row in projections
    if str(row["player_id"]) == pid
)


print()
print("=== PLAYER PROJECTION TOP-LEVEL KEYS ===")
print(
    sorted(
        projection.keys()
    )
)


gameweeks = projection.get(
    "gameweeks",
    []
)

print()
print("=== GAMEWEEK PROJECTION KEYS ===")

if gameweeks:

    print(
        sorted(
            gameweeks[0].keys()
        )
    )

    print()
    print("=== HAALAND GAMEWEEK ROW ===")

    print(
        json.dumps(
            gameweeks[0],
            indent=2,
            ensure_ascii=False,
        )
    )

else:

    print("NO GAMEWEEKS")


minute_rows = [
    row
    for row in rows(
        RUN / "minutes.json"
    )
    if str(
        row["player_id"]
    ) == pid
]


print()
print("=== MINUTES ROW KEYS ===")

if minute_rows:

    print(
        sorted(
            minute_rows[0].keys()
        )
    )

    print()
    print("=== HAALAND FIRST MINUTES ROW ===")

    compact = {
        key: minute_rows[0].get(key)
        for key in (
            "player_id",
            "fixture_id",
            "p_appearance",
            "p_start",
            "expected_minutes",
            "model_version",
        )
    }

    print(
        json.dumps(
            compact,
            indent=2,
            ensure_ascii=False,
        )
    )

else:

    print("NO MINUTES ROWS")


print()
print("=== END ===")
