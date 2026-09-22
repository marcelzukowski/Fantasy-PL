from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    optimize_rolling_free_transfers,
)

from fpl_engine.decision.availability_adapter import (
    build_gameweek_availability,
)

from fpl_engine.decision.autosubs import (
    optimize_autosub_lineup,
)

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)


RUNS = (
    "20260912T082141Z",
    "20260912T082424Z",
)

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)

ROOT = Path.cwd()

BASE = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

SQUAD = json.loads(
    (
        ROOT
        / "scratch"
        / "decision"
        / "my_squad_gw4.json"
    ).read_text(
        encoding="utf-8"
    )
)

CURRENT = frozenset(
    row["player_id"]
    for row in SQUAD["players"]
)

SELLING = {
    row["player_id"]:
    int(row["selling_price_tenths"])
    for row in SQUAD["players"]
}


def msg(*args):
    print(*args, flush=True)


def load(directory, name):
    return json.loads(
        (
            directory
            / name
        ).read_text(
            encoding="utf-8"
        )
    )


def gw_ev(
    projection,
    gameweek,
):
    for row in projection.gameweeks:
        if row.gameweek == gameweek:
            return float(
                row.expected_points
            )

    raise RuntimeError(
        f"missing GW{gameweek} "
        f"for {projection.player_id}"
    )


def score_squad(
    squad_ids,
    data,
):
    total = 0.0
    xi_total = 0.0
    autosub_total = 0.0

    for index, gameweek in enumerate(
        range(4, 10)
    ):
        points = {
            player_id:
            gw_ev(
                data["projections"][
                    player_id
                ],
                gameweek,
            )
            for player_id
            in squad_ids
        }

        positions = {
            player_id:
            data["metadata"][
                player_id
            ]["position"]
            for player_id
            in squad_ids
        }

        appearance = {
            player_id:
            data["availability"][
                (
                    player_id,
                    gameweek,
                )
            ].p_appearance
            for player_id
            in squad_ids
        }

        lineup = (
            optimize_autosub_lineup(
                gameweek=gameweek,
                squad_ids=squad_ids,
                positions=positions,
                expected_points=points,
                p_appearance=appearance,
            )
        )

        autosub = (
            lineup.expected_gk_autosub_ev
            + lineup.expected_outfield_autosub_ev
        )

        weight = WEIGHTS[index]

        xi_total += (
            weight
            * lineup.base_xi_ev
        )

        autosub_total += (
            weight
            * autosub
        )

        total += (
            weight
            * (
                lineup.base_xi_ev
                + autosub
            )
        )

    return {
        "total": total,
        "xi": xi_total,
        "autosub": autosub_total,
    }


def score_normal_2ft(
    data,
):
    plan = (
        optimize_rolling_free_transfers(
            players=data["values"],
            projections_by_id=(
                data["projections"]
            ),
            state=data["state"],
            horizon=6,
            transfers_now=2,
            current_free_transfers=int(
                SQUAD["free_transfers"]
            ),
            captaincy_weight=0.0,
        )
    )

    if plan is None:
        raise RuntimeError(
            "normal 2FT plan missing"
        )

    total = 0.0

    for index, gameweek in enumerate(
        range(4, 10)
    ):
        squad_ids = (
            plan.squad_now_player_ids
            if gameweek == 4
            else plan.squad_next_player_ids
        )

        points = {
            player_id:
            gw_ev(
                data["projections"][
                    player_id
                ],
                gameweek,
            )
            for player_id
            in squad_ids
        }

        positions = {
            player_id:
            data["metadata"][
                player_id
            ]["position"]
            for player_id
            in squad_ids
        }

        appearance = {
            player_id:
            data["availability"][
                (
                    player_id,
                    gameweek,
                )
            ].p_appearance
            for player_id
            in squad_ids
        }

        lineup = (
            optimize_autosub_lineup(
                gameweek=gameweek,
                squad_ids=squad_ids,
                positions=positions,
                expected_points=points,
                p_appearance=appearance,
            )
        )

        autosub = (
            lineup.expected_gk_autosub_ev
            + lineup.expected_outfield_autosub_ev
        )

        total += (
            WEIGHTS[index]
            * (
                lineup.base_xi_ev
                + autosub
            )
        )

    return total


msg()
msg(
    "=== FAST HAALAND "
    "WILDCARD SENSITIVITY ==="
)


prepared = {}


for run_index, run_name in enumerate(
    RUNS,
    start=1,
):
    started = time.perf_counter()

    msg()
    msg(
        f"[{run_index}/2] "
        f"Loading {run_name}..."
    )

    directory = (
        BASE
        / run_name
    )

    projection_rows = load(
        directory,
        "player_projections.json",
    )

    player_rows = load(
        directory,
        "current_players.json",
    )

    minute_rows = load(
        directory,
        "minutes.json",
    )

    metadata = {
        row["player_id"]:
        row
        for row in player_rows
    }

    adapted = (
        adapt_player_projections(
            projection_rows
        )
    )

    projections = {
        row.player_id:
        row
        for row in adapted
    }

    values = build_player_values(
        adapted,
        metadata,
    )

    by_id = {
        row.player_id:
        row
        for row in values
    }

    availability = (
        build_gameweek_availability(
            projection_rows,
            minute_rows,
        )
    )

    state = SquadState(
        player_ids=CURRENT,
        bank_tenths=int(
            SQUAD["bank_tenths"]
        ),
        selling_prices_tenths=(
            SELLING
        ),
        team_counts=(
            build_team_counts(
                CURRENT,
                by_id,
            )
        ),
    )

    haaland = next(
        player_id
        for player_id, row
        in metadata.items()
        if row["display_name"]
        == "Haaland"
    )

    data = {
        "player_rows":
        player_rows,
        "metadata":
        metadata,
        "projections":
        projections,
        "values":
        values,
        "availability":
        availability,
        "state":
        state,
        "haaland":
        haaland,
    }

    prepared[
        run_name
    ] = data

    msg(
        "    computing normal 2FT..."
    )

    data["normal"] = (
        score_normal_2ft(
            data
        )
    )

    msg(
        "    computing raw WC..."
    )

    data["raw_wc"] = (
        optimize_unlimited_squad(
            player_rows=player_rows,
            projections_by_id=(
                projections
            ),
            current_player_ids=(
                CURRENT
            ),
            selling_prices_tenths=(
                SELLING
            ),
            bank_tenths=int(
                SQUAD["bank_tenths"]
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
        )
    )

    msg(
        "    scoring raw WC..."
    )

    data["raw_score"] = (
        score_squad(
            data[
                "raw_wc"
            ].player_ids,
            data,
        )
    )

    msg(
        "    computing WC "
        "with Haaland forced..."
    )

    data["haaland_wc"] = (
        optimize_unlimited_squad(
            player_rows=player_rows,
            projections_by_id=(
                projections
            ),
            current_player_ids=(
                CURRENT
            ),
            selling_prices_tenths=(
                SELLING
            ),
            bank_tenths=int(
                SQUAD["bank_tenths"]
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
            required_player_ids=(
                haaland,
            ),
        )
    )

    msg(
        "    scoring WC+H..."
    )

    data["haaland_score"] = (
        score_squad(
            data[
                "haaland_wc"
            ].player_ids,
            data,
        )
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    msg(
        f"    done in "
        f"{elapsed:.1f}s"
    )


msg()
msg(
    "=== PER-RUN RESULTS ==="
)


for run_name, data in (
    prepared.items()
):
    normal = data[
        "normal"
    ]

    raw = data[
        "raw_score"
    ]["total"]

    forced = data[
        "haaland_score"
    ]["total"]

    haaland_projection = (
        data["projections"][
            data["haaland"]
        ]
    )

    haaland_wev = sum(
        WEIGHTS[index]
        * gw_ev(
            haaland_projection,
            gameweek,
        )
        for index, gameweek
        in enumerate(
            range(4, 10)
        )
    )

    msg()
    msg(
        "RUN:",
        run_name
    )

    msg(
        "Haaland raw WEV6:",
        f"{haaland_wev:.2f}",
    )

    msg(
        "normal 2FT:",
        f"{normal:.2f}",
    )

    msg(
        "WC unconstrained:",
        f"{raw:.2f}",
        "| delta:",
        f"{raw-normal:+.2f}",
    )

    msg(
        "WC + Haaland:",
        f"{forced:.2f}",
        "| delta:",
        f"{forced-normal:+.2f}",
    )

    msg(
        "forcing Haaland effect:",
        f"{forced-raw:+.2f}",
    )

    msg(
        "WC+H unused budget:",
        f"GBP "
        f"{data['haaland_wc'].remaining_budget_tenths/10:.1f}m",
    )


#
# Unique forced-Haaland squads.
#

forced_candidates = []

for data in prepared.values():
    candidate = (
        data[
            "haaland_wc"
        ].player_ids
    )

    if candidate not in (
        forced_candidates
    ):
        forced_candidates.append(
            candidate
        )


msg()
msg(
    "=== FORCED-HAALAND "
    "CROSS-RUN STABILITY ==="
)

msg(
    "unique candidates:",
    len(
        forced_candidates
    ),
)


reference = prepared[
    RUNS[0]
]

names = {
    player_id:
    row["display_name"]
    for player_id, row
    in reference[
        "metadata"
    ].items()
}


for candidate_index, candidate in enumerate(
    forced_candidates,
    start=1,
):
    msg()
    msg(
        "-----------------------------"
    )

    msg(
        "CANDIDATE",
        candidate_index,
    )

    deltas = []
    raw_differences = []

    for run_name, data in (
        prepared.items()
    ):
        #
        # Re-score fixed candidate only.
        # No new MILP optimization.
        #

        candidate_score = (
            score_squad(
                candidate,
                data,
            )["total"]
        )

        normal = data[
            "normal"
        ]

        raw = data[
            "raw_score"
        ]["total"]

        delta = (
            candidate_score
            - normal
        )

        vs_raw = (
            candidate_score
            - raw
        )

        deltas.append(
            delta
        )

        raw_differences.append(
            vs_raw
        )

        msg(
            run_name,
            "| WC+H:",
            f"{candidate_score:.2f}",
            "| vs 2FT:",
            f"{delta:+.2f}",
            "| vs raw WC:",
            f"{vs_raw:+.2f}",
        )

    outgoing = (
        CURRENT
        - candidate
    )

    incoming = (
        candidate
        - CURRENT
    )

    msg(
        "mean delta vs 2FT:",
        f"{statistics.mean(deltas):+.2f}",
    )

    msg(
        "worst delta vs 2FT:",
        f"{min(deltas):+.2f}",
    )

    msg(
        "mean effect vs raw WC:",
        f"{statistics.mean(raw_differences):+.2f}",
    )

    msg(
        "Haaland retained:",
        reference[
            "haaland"
        ] in candidate,
    )

    msg(
        "OUT:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in outgoing
            )
        ),
    )

    msg(
        "IN:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in incoming
            )
        ),
    )


msg()
msg(
    "=== FAST AUDIT COMPLETE ==="
)
