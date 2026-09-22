from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import math

from fpl_engine.models.player_talent.goal_allocation_history import (
    GoalAllocationPlayerRef,
    build_strict_goal_allocation_proxy,
)


ROOT = Path(".").resolve()

BASE_RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

REFERENCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain062_canonical_goal_allocation"
    / "goal_allocation_proxy_canonical.json"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066a"
    / "goal_allocation_proxy_builder.json"
)


def load(
    path,
):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


players_payload = load(
    BASE_RUN
    / "current_players.json"
)

context = load(
    BASE_RUN
    / "prediction_context.json"
)


players = tuple(
    GoalAllocationPlayerRef(
        player_id=str(
            row[
                "player_id"
            ]
        ),
        position=str(
            row[
                "position"
            ]
        ),
        display_name=(
            row.get(
                "display_name"
            )
            or row.get(
                "name"
            )
        ),
    )
    for row in players_payload
)


prediction_timestamp = (
    datetime.fromisoformat(
        str(
            context[
                "prediction_timestamp"
            ]
        ).replace(
            "Z",
            "+00:00",
        )
    )
)


artifact = (
    build_strict_goal_allocation_proxy(
        project_root=ROOT,
        source_season="2025-26",
        prediction_timestamp=(
            prediction_timestamp
        ),
        current_players=players,
    )
)


OUT.write_text(
    json.dumps(
        artifact.to_dict(),
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


reference = load(
    REFERENCE
)


reference_by_id = {
    str(
        row[
            "player_id"
        ]
    ):
    row
    for row in reference[
        "players"
    ]
}


builder_by_id = {
    row.player_id:
        row
    for row in artifact.rows
}


if (
    set(
        reference_by_id
    )
    != set(
        builder_by_id
    )
):

    raise RuntimeError(
        "Builder/reference player "
        "universes differ"
    )


used_reference = {
    player_id
    for player_id, row
    in reference_by_id.items()
    if row.get(
        "used_historical_total_xg"
    )
}

used_builder = {
    player_id
    for player_id, row
    in builder_by_id.items()
    if row.used_historical_total_xg
}


proxy_differences = []


for player_id in sorted(
    used_reference
    & used_builder
):

    old = float(
        reference_by_id[
            player_id
        ][
            "goal_allocation_proxy_per90"
        ]
    )

    new = float(
        builder_by_id[
            player_id
        ]
        .goal_allocation_proxy_per90
    )


    if not math.isclose(
        old,
        new,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):

        proxy_differences.append(
            (
                player_id,
                old,
                new,
            )
        )


evidence_sets_equal = (
    used_reference
    == used_builder
)


print(
    "=== CAPTAIN-066A "
    "MATERIALIZED BUILDER VALIDATION ==="
)

print(
    "current players:",
    artifact.current_player_count,
)

print(
    "STRICT identity players:",
    artifact.strict_identity_player_count,
)

print(
    "historical xG players:",
    artifact.historical_player_count,
)

print(
    "matched:",
    artifact.matched_count,
)

print(
    "match_rate:",
    f"{artifact.match_rate:.3f}",
)

print(
    "position mismatches:",
    artifact.position_mismatch_count,
)

print(
    "no history:",
    artifact.no_history_count,
)

print(
    "unresolved Vaastav rows:",
    artifact.unresolved_vaastav_rows,
)


print()
print(
    "=== CAPTAIN-062 EQUIVALENCE ==="
)

print(
    "reference evidence:",
    len(
        used_reference
    ),
)

print(
    "builder evidence:",
    len(
        used_builder
    ),
)

print(
    "evidence IDs:",
    (
        "PASS"
        if evidence_sets_equal
        else "FAIL"
    ),
)

print(
    "proxy differences:",
    len(
        proxy_differences
    ),
)


print()
print(
    "=== KEY PLAYERS ==="
)


for token in (
    "Haaland",
    "Palmer",
    "B.Fernandes",
    "Tavernier",
    "Szoboszlai",
):

    for row in artifact.rows:

        if (
            token.casefold()
            not in str(
                row.display_name
                or ""
            ).casefold()
        ):

            continue

        print(
            f"{str(row.display_name):<24} "
            f"{row.position:<3} "
            f"used="
            f"{str(row.used_historical_total_xg):<5} "
            f"xG="
            f"{str(row.source_total_xg):<8} "
            f"min="
            f"{row.source_minutes:.0f} "
            f"proxy="
            f"{row.goal_allocation_proxy_per90:.3f}"
        )


gate = all((
    artifact.current_player_count
    == 656,

    artifact.matched_count
    == 399,

    artifact.position_mismatch_count
    == 10,

    artifact.no_history_count
    == 247,

    artifact.unresolved_vaastav_rows
    == 1,

    evidence_sets_equal,

    not proxy_differences,
))


print()
print(
    "BUILDER GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "artifact:",
    OUT.relative_to(
        ROOT
    ),
)

print(
    "Production pipeline modified: NO"
)


if not gate:

    raise RuntimeError(
        "CAPTAIN-066A builder "
        "equivalence gate failed"
    )
