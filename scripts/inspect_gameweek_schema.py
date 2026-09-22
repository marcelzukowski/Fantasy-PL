from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, is_dataclass
from pathlib import Path

from fpl_engine.decision import (
    adapt_player_projections,
)


RUN = "20260911T214014Z"

TARGETS = {
    "shaw",
    "diop",
    "nwilliams",
}


def norm(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return (
        text.casefold()
        .replace(".", "")
        .replace("-", "")
        .replace(" ", "")
    )


def interesting_dict(data):
    if not isinstance(data, dict):
        return data

    result = {}

    for key, value in data.items():

        lower = str(key).lower()

        if (
            key in {
                "gameweek",
                "expected_points",
            }
            or any(
                token in lower
                for token in (
                    "minute",
                    "start",
                    "appear",
                    "play",
                    "avail",
                    "prob",
                )
            )
        ):
            result[key] = value

    return result


root = Path.cwd()

run_dir = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / RUN
)

raw_rows = json.loads(
    (
        run_dir
        / "player_projections.json"
    ).read_text(
        encoding="utf-8"
    )
)

player_rows = json.loads(
    (
        run_dir
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

metadata = {
    row["player_id"]: row
    for row in player_rows
}

adapted = {
    row.player_id: row
    for row in adapt_player_projections(
        raw_rows
    )
}


print()
print(
    "=== RAW GAMEWEEK SCHEMA AUDIT ==="
)


for raw in raw_rows:

    player_id = raw[
        "player_id"
    ]

    meta = metadata.get(
        player_id
    )

    if meta is None:
        continue

    name = meta[
        "display_name"
    ]

    if norm(name) not in TARGETS:
        continue

    print()
    print(
        "================================"
    )

    print(
        name,
        "|",
        meta["position"],
    )

    gameweeks = raw.get(
        "gameweeks"
    )

    print(
        "raw gameweeks type:",
        type(gameweeks).__name__,
    )

    if isinstance(
        gameweeks,
        dict,
    ):

        print(
            "raw GW keys:",
            list(
                gameweeks.keys()
            )[:10],
        )

        for key, value in list(
            gameweeks.items()
        )[:2]:

            print()
            print(
                f"RAW {key}:"
            )

            print(
                " value type:",
                type(value).__name__,
            )

            if isinstance(
                value,
                dict,
            ):
                print(
                    " all keys:",
                    sorted(
                        value.keys()
                    ),
                )

                print(
                    " relevant:",
                    interesting_dict(
                        value
                    ),
                )

            else:
                print(
                    " value:",
                    value,
                )

    elif isinstance(
        gameweeks,
        list,
    ):

        print(
            "raw GW count:",
            len(gameweeks),
        )

        for index, value in enumerate(
            gameweeks[:2]
        ):

            print()
            print(
                f"RAW item {index}:"
            )

            print(
                " value type:",
                type(value).__name__,
            )

            if isinstance(
                value,
                dict,
            ):
                print(
                    " all keys:",
                    sorted(
                        value.keys()
                    ),
                )

                print(
                    " relevant:",
                    interesting_dict(
                        value
                    ),
                )

            else:
                print(
                    value
                )

    else:

        print(
            "raw value:",
            gameweeks,
        )

    print()
    print(
        "ADAPTED GAMEWEEKS:"
    )

    projection = adapted[
        player_id
    ]

    for gw in (
        projection.gameweeks[:2]
    ):

        if is_dataclass(gw):
            print(
                asdict(gw)
            )
        else:
            print(
                vars(gw)
            )
