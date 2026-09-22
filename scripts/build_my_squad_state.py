from __future__ import annotations

import json
from pathlib import Path
import unicodedata


SQUAD = {
    # name: (position, actual selling price in tenths)

    "Donnarumma": ("GK", 55),
    "Dubravka": ("GK", 40),

    "Thomas": ("DEF", 40),
    "Diop": ("DEF", 40),
    "Virgil": ("DEF", 65),
    "Gvardiol": ("DEF", 55),
    "Shaw": ("DEF", 44),

    "Ndiaye": ("MID", 59),
    "Szoboszlai": ("MID", 70),
    "B.Fernandes": ("MID", 120),
    "Mbeumo": ("MID", 79),
    "Xhaka": ("MID", 55),

    "Joao Pedro": ("FWD", 76),
    "Kusi-Asare": ("FWD", 45),
    "Haaland": ("FWD", 155),
}

BANK_TENTHS = 0
FREE_TRANSFERS = 3
ACTIVE_GAMEWEEK = 4


def normalize(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    return "".join(
        c
        for c in text
        if not unicodedata.combining(c)
    ).casefold().strip()


root = Path.cwd()

base = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

MIN_DECISION_SIMULATIONS = 64


def estimate_simulation_count(
    rows,
):
    probabilities = []

    for player in rows:
        for gw in player.get(
            "gameweeks",
            []
        ):
            for value in gw.get(
                "points_distribution",
                {}
            ).values():

                value = float(value)

                if (
                    value > 0.0
                    and value < 1.0
                ):
                    probabilities.append(
                        value
                    )

    if not probabilities:
        return 1

    return round(
        1.0 / min(probabilities)
    )


projection_candidates = []

for path in base.glob(
    "*/player_projections.json"
):
    rows = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        not rows
        or rows[0].get(
            "current_gameweek"
        ) != ACTIVE_GAMEWEEK
    ):
        continue

    simulation_count = (
        estimate_simulation_count(
            rows
        )
    )

    if (
        simulation_count
        < MIN_DECISION_SIMULATIONS
    ):
        continue

    projection_candidates.append(
        (
            path.parent,
            simulation_count,
        )
    )

if not projection_candidates:
    raise SystemExit(
        "No decision-quality projection "
        f"run found for GW{ACTIVE_GAMEWEEK} "
        f"with >= "
        f"{MIN_DECISION_SIMULATIONS} "
        "simulations"
    )

run_dir, selected_simulations = max(
    projection_candidates,
    key=lambda item: (
        item[0].name
    ),
)

players = json.loads(
    (
        run_dir
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

by_name = {}

for row in players:
    by_name.setdefault(
        normalize(
            row["display_name"]
        ),
        [],
    ).append(row)

mapped = []

for name, (
    expected_position,
    selling_price,
) in SQUAD.items():

    name_matches = by_name.get(
        normalize(name),
        [],
    )

    matches = [
        row
        for row in name_matches
        if row.get(
            "position"
        ) == expected_position
    ]

    if len(matches) != 1:
        print()
        print(
            f"AMBIGUOUS: {name} "
            f"({expected_position})"
        )

        for candidate in name_matches:
            print(
                "  ",
                candidate.get(
                    "display_name"
                ),
                "|",
                candidate.get(
                    "position"
                ),
                "| current ?",
                (
                    candidate.get(
                        "current_price",
                        0,
                    )
                    / 10
                ),
                "| team",
                candidate.get(
                    "provider_team_id"
                ),
                "|",
                candidate.get(
                    "player_id"
                ),
            )

        raise SystemExit(
            f"{name}: expected exactly "
            f"1 {expected_position} match, "
            f"got {len(matches)}"
        )

    row = matches[0]

    mapped.append({
        "player_id": row["player_id"],
        "name": row["display_name"],
        "position": row["position"],
        "team_id": row["team_id"],
        "provider_team_id": (
            row.get(
                "provider_team_id"
            )
        ),
        "selling_price_tenths": (
            selling_price
        ),
    })

team_members = {}

for row in mapped:
    team_members.setdefault(
        row["team_id"],
        [],
    ).append(
        row["name"]
    )

violations = {
    team_id: names
    for team_id, names
    in team_members.items()
    if len(names) > 3
}

payload = {
    "active_gameweek": (
        ACTIVE_GAMEWEEK
    ),
    "projection_run": str(
        run_dir
    ),
    "bank_tenths": (
        BANK_TENTHS
    ),
    "bank_m": (
        BANK_TENTHS / 10
    ),
    "free_transfers": (
        FREE_TRANSFERS
    ),
    "players": mapped,
    "club_limit_violations": (
        violations
    ),
}

output = (
    root
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

output.parent.mkdir(
    parents=True,
    exist_ok=True,
)

output.write_text(
    json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

print()
print(
    "=== MY SQUAD STATE ==="
)

print(
    "active_gameweek:",
    ACTIVE_GAMEWEEK,
)

print(
    "projection_run:",
    run_dir.name,
)

print(
    "simulation_count:",
    selected_simulations,
)

print(
    "bank:",
    "£0.0m",
)

print(
    "free_transfers:",
    FREE_TRANSFERS,
)

print(
    "players:",
    len(mapped),
)

print()
print(
    "club_limit_violations:"
)

if violations:
    for team_id, names in (
        violations.items()
    ):
        print(
            " ",
            team_id,
            "=>",
            ", ".join(names),
        )
else:
    print(
        " none"
    )

print()
print(
    "saved:",
    output,
)
