from pathlib import Path
import json

from fpl_engine.decision.appearance import (
    build_gameweek_appearance,
)


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

player_id = str(
    haaland["player_id"]
)


projection_rows = rows(
    RUN / "player_projections.json"
)

minutes_rows = rows(
    RUN / "minutes.json"
)


appearance = (
    build_gameweek_appearance(
        projection_rows=projection_rows,
        minutes_rows=minutes_rows,
    )
)


actual = appearance[
    player_id
][4]

expected = (
    0.9147693594004905
)


print()
print(
    "=== REAL GW4 APPEARANCE BRIDGE ==="
)

print(
    "Haaland GW4 p_appearance="
    f"{actual:.12f}"
)

print(
    "expected="
    f"{expected:.12f}"
)

print(
    "delta="
    f"{actual - expected:+.12e}"
)


if abs(
    actual - expected
) > 1e-12:

    raise RuntimeError(
        "GW4 appearance bridge mismatch"
    )


print()
print(
    "REAL CONTRACT CHECK: PASS"
)
