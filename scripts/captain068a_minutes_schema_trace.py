from pathlib import Path
import json


ROOT = Path(".").resolve()

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068"
    / "haaland_trace.log"
)


def load(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


if not ACCEPTANCE.exists():
    raise RuntimeError(
        "CAPTAIN-067C acceptance report missing."
    )


acceptance = load(
    ACCEPTANCE
)

run_dir = (
    ROOT
    / acceptance[
        "default_run"
    ]
)


required = (
    "current_players.json",
    "fixture_horizon.json",
    "minutes.json",
    "event_projections.json",
    "player_projections.json",
)


for name in required:
    path = run_dir / name

    if not path.exists():
        raise RuntimeError(
            f"Missing artifact: {path}"
        )


players = load(
    run_dir
    / "current_players.json"
)

fixtures = load(
    run_dir
    / "fixture_horizon.json"
)

minutes = load(
    run_dir
    / "minutes.json"
)

events = load(
    run_dir
    / "event_projections.json"
)

projections = load(
    run_dir
    / "player_projections.json"
)


#
# ------------------------------------------------------------
# Find Haaland canonical ID
# ------------------------------------------------------------
#

def player_name(row):

    for key in (
        "display_name",
        "web_name",
        "name",
        "player_name",
    ):

        value = row.get(
            key
        )

        if value:

            return str(
                value
            )

    return ""


haaland_candidates = [
    row
    for row in players
    if "haaland"
    in player_name(
        row
    ).lower()
]


if len(
    haaland_candidates
) != 1:

    raise RuntimeError(
        "Expected exactly one Haaland; "
        f"found {len(haaland_candidates)}"
    )


haaland = (
    haaland_candidates[
        0
    ]
)

player_id = str(
    haaland[
        "player_id"
    ]
)


#
# ------------------------------------------------------------
# Fixture map
# ------------------------------------------------------------
#

fixture_map = {
    str(
        row[
            "fixture_id"
        ]
    ):
    row
    for row in fixtures
}


#
# ------------------------------------------------------------
# Recursive event-player extraction
# ------------------------------------------------------------
#

event_player_rows = []


def walk(
    value,
    *,
    fixture_id=None,
    path="root",
):

    if isinstance(
        value,
        dict,
    ):

        current_fixture = (
            value.get(
                "fixture_id",
                fixture_id,
            )
        )


        if str(
            value.get(
                "player_id",
                ""
            )
        ) == player_id:

            event_player_rows.append({
                "fixture_id": (
                    str(
                        current_fixture
                    )
                    if current_fixture
                    is not None
                    else None
                ),
                "path": path,
                "row": value,
            })


        for key, child in (
            value.items()
        ):

            walk(
                child,
                fixture_id=(
                    current_fixture
                ),
                path=(
                    f"{path}.{key}"
                ),
            )


    elif isinstance(
        value,
        list,
    ):

        for index, child in (
            enumerate(
                value
            )
        ):

            walk(
                child,
                fixture_id=(
                    fixture_id
                ),
                path=(
                    f"{path}[{index}]"
                ),
            )


walk(
    events
)


#
# ------------------------------------------------------------
# Haaland minute rows
# ------------------------------------------------------------
#

haaland_minutes = [
    row
    for row in minutes
    if str(
        row.get(
            "player_id"
        )
    )
    == player_id
]


haaland_projection = [
    row
    for row in projections
    if str(
        row.get(
            "player_id"
        )
    )
    == player_id
]


#
# ------------------------------------------------------------
# Print compact schema
# ------------------------------------------------------------
#

print(
    "=== CAPTAIN-068A HAALAND TRACE ==="
)

print(
    "run:",
    run_dir.relative_to(
        ROOT
    ),
)

print(
    "player:",
    player_name(
        haaland
    ),
)

print(
    "player_id:",
    player_id,
)

print()


print(
    "=== TOP-LEVEL KEYS ==="
)

print(
    "current_player:",
    sorted(
        haaland.keys()
    ),
)

if minutes:

    print(
        "minutes:",
        sorted(
            minutes[
                0
            ].keys()
        ),
    )

if projections:

    print(
        "player_projection:",
        sorted(
            projections[
                0
            ].keys()
        ),
    )

if events:

    print(
        "event_projection:",
        sorted(
            events[
                0
            ].keys()
        ),
    )


print()
print(
    "=== HAALAND MINUTES ==="
)

print(
    "rows:",
    len(
        haaland_minutes
    ),
)


for row in haaland_minutes:

    fixture_id = str(
        row.get(
            "fixture_id"
        )
    )

    fixture = fixture_map.get(
        fixture_id,
        {},
    )

    print()
    print(
        "fixture:",
        fixture_id,
        "GW",
        fixture.get(
            "target_gameweek"
        ),
    )

    print(
        json.dumps(
            row,
            indent=2,
            sort_keys=True,
        )
    )


print()
print(
    "=== HAALAND EVENT ROWS ==="
)

print(
    "rows:",
    len(
        event_player_rows
    ),
)


for item in event_player_rows:

    fixture_id = (
        item[
            "fixture_id"
        ]
    )

    fixture = fixture_map.get(
        str(
            fixture_id
        ),
        {},
    )


    print()
    print(
        "fixture:",
        fixture_id,
        "GW",
        fixture.get(
            "target_gameweek"
        ),
    )

    print(
        "path:",
        item[
            "path"
        ],
    )

    print(
        json.dumps(
            item[
                "row"
            ],
            indent=2,
            sort_keys=True,
        )
    )


print()
print(
    "=== HAALAND PLAYER PROJECTION ==="
)

print(
    "rows:",
    len(
        haaland_projection
    ),
)


for row in (
    haaland_projection
):

    print(
        json.dumps(
            row,
            indent=2,
            sort_keys=True,
        )
    )


print()
print(
    "=== COUNTS ==="
)

print(
    "players:",
    len(
        players
    ),
)

print(
    "fixtures:",
    len(
        fixtures
    ),
)

print(
    "minutes rows:",
    len(
        minutes
    ),
)

print(
    "event fixtures:",
    len(
        events
    ),
)

print(
    "player projections:",
    len(
        projections
    ),
)
