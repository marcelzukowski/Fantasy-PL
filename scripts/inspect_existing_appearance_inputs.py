from __future__ import annotations

import json
from pathlib import Path


RUN = "20260911T214014Z"

ROOT = Path.cwd()

run_dir = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / RUN
)

FILES = (
    "event_projections.json",
    "minutes.json",
)


def walk(
    value,
    path="root",
):
    if isinstance(value, dict):

        if (
            "p_appearance" in value
            or "p_start" in value
        ):
            yield path, value

        for key, child in (
            value.items()
        ):
            yield from walk(
                child,
                f"{path}.{key}",
            )

    elif isinstance(value, list):

        for index, child in enumerate(
            value
        ):
            yield from walk(
                child,
                f"{path}[{index}]",
            )


print()
print(
    "=== EXISTING APPEARANCE INPUT AUDIT ==="
)


for filename in FILES:

    path = (
        run_dir
        / filename
    )

    print()
    print(
        "================================"
    )
    print(
        filename
    )
    print(
        "================================"
    )

    if not path.exists():

        print(
            "FILE NOT FOUND"
        )
        continue

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    matches = list(
        walk(
            payload
        )
    )

    print(
        "records with "
        "p_appearance/p_start:",
        len(matches),
    )

    for index, (
        location,
        record,
    ) in enumerate(
        matches[:12],
        start=1,
    ):

        print()
        print(
            f"--- MATCH {index} ---"
        )

        print(
            "path:",
            location,
        )

        for key in (
            "player_id",
            "fixture_id",
            "team_id",
            "position",
            "expected_minutes",
            "p_appearance",
            "p_start",
        ):

            if key in record:
                print(
                    f"{key}:",
                    record[key],
                )

        print(
            "keys:",
            sorted(
                record.keys()
            ),
        )
