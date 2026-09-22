from __future__ import annotations

from dataclasses import asdict
from itertools import combinations, permutations
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
import json
import math
import unicodedata

from fpl_engine.decision.autosubs import (
    evaluate_autosub_lineup,
    optimize_autosub_lineup,
)

from fpl_engine.decision.captaincy_value import (
    best_captaincy_pair,
)

from fpl_engine.simulation.v22 import (
    FixtureSimulatorV22,
)


ROOT = Path(".").resolve()

BASE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
)

V1 = BASE / "v1"
V22 = BASE / "v22_real"

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "decision_impact.json"
)


# ============================================================
# Saved WC squad
# ============================================================

SQUAD_SPEC = (
    ("Sels", "GK"),
    ("Kelleher", "GK"),

    ("Maatsen", "DEF"),
    ("Justin", "DEF"),
    ("De Cuyper", "DEF"),
    ("Egan", "DEF"),
    ("Giles", "DEF"),

    ("Gross", "MID"),
    ("Tavernier", "MID"),
    ("B.Fernandes", "MID"),
    ("Szoboszlai", "MID"),
    ("Palmer", "MID"),

    ("Calvert-Lewin", "FWD"),
    ("Haaland", "FWD"),
    ("Evanilson", "FWD"),
)


ALL_CAPTAIN_POSITIONS = (
    "GK",
    "DEF",
    "MID",
    "FWD",
)


# ============================================================
# Helpers
# ============================================================

def load(path: Path):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


for path in (
    V1,
    V22,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing replay directory: {path}"
        )


def normalize(value):

    value = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(
            character
        )
    )

    value = value.casefold()

    #
    # casefold converts German ß -> ss.
    #
    return "".join(
        character
        for character in value
        if character.isalnum()
    )


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


    payload = row.get(
        "provider_payload"
    )

    if isinstance(
        payload,
        dict,
    ):

        for key in (
            "web_name",
            "second_name",
            "first_name",
        ):

            value = payload.get(
                key
            )

            if value:
                return str(
                    value
                )


    return str(
        row.get(
            "player_id",
            "",
        )
    )


def player_position(row):

    value = row.get(
        "position"
    )

    if value:
        return str(
            value
        ).upper()


    payload = row.get(
        "provider_payload"
    )

    if isinstance(
        payload,
        dict,
    ):

        code = payload.get(
            "element_type"
        )

        mapping = {
            1: "GK",
            2: "DEF",
            3: "MID",
            4: "FWD",
        }

        try:
            return mapping[
                int(code)
            ]
        except (
            TypeError,
            ValueError,
            KeyError,
        ):
            pass


    raise RuntimeError(
        "Could not determine player position: "
        f"{player_name(row)}"
    )


# ============================================================
# Resolve saved WC squad canonically
# ============================================================

players_json = load(
    V1
    / "current_players.json"
)


players_by_id = {
    str(
        row[
            "player_id"
        ]
    ):
    row
    for row in players_json
}


names = {
    player_id:
        player_name(
            row
        )
    for player_id, row
    in players_by_id.items()
}


positions = {
    player_id:
        player_position(
            row
        )
    for player_id, row
    in players_by_id.items()
}


def resolve_player(
    requested_name,
    expected_position,
):

    needle = normalize(
        requested_name
    )


    same_position = [
        player_id
        for player_id in players_by_id
        if positions[
            player_id
        ] == expected_position
    ]


    exact = [
        player_id
        for player_id in same_position
        if normalize(
            names[
                player_id
            ]
        )
        == needle
    ]


    if len(
        exact
    ) == 1:

        return exact[
            0
        ]


    partial = [
        player_id
        for player_id in same_position
        if (
            needle
            in normalize(
                names[
                    player_id
                ]
            )
            or normalize(
                names[
                    player_id
                ]
            )
            in needle
        )
    ]


    if len(
        partial
    ) == 1:

        return partial[
            0
        ]


    candidates = [
        (
            names[
                player_id
            ],
            player_id,
        )
        for player_id
        in same_position
        if (
            needle[:4]
            in normalize(
                names[
                    player_id
                ]
            )
        )
    ]


    raise RuntimeError(
        f"Could not uniquely resolve "
        f"{requested_name} ({expected_position}). "
        f"Candidates: {candidates}"
    )


squad_ids = []

resolution = []


for requested_name, expected_position in SQUAD_SPEC:

    player_id = resolve_player(
        requested_name,
        expected_position,
    )

    squad_ids.append(
        player_id
    )

    resolution.append({
        "requested":
            requested_name,

        "resolved":
            names[
                player_id
            ],

        "position":
            positions[
                player_id
            ],

        "player_id":
            player_id,
    })


if len(
    set(
        squad_ids
    )
) != 15:

    raise RuntimeError(
        "Saved WC squad did not resolve "
        "to 15 unique players."
    )


position_counts = {
    position:
        sum(
            positions[
                player_id
            ]
            == position
            for player_id in squad_ids
        )
    for position in (
        "GK",
        "DEF",
        "MID",
        "FWD",
    )
}


squad_structure_gate = (
    position_counts
    == {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }
)


# ============================================================
# Projection extraction
# ============================================================

def collect_projection_rows(
    payload,
):

    output = {}


    def visit(value):

        if isinstance(
            value,
            dict,
        ):

            if all(
                key in value
                for key in (
                    "player_id",
                    "target_gameweek",
                    "expected_points",
                )
            ):

                key = (
                    str(
                        value[
                            "player_id"
                        ]
                    ),
                    int(
                        value[
                            "target_gameweek"
                        ]
                    ),
                )

                row = {
                    "expected_points":
                        float(
                            value[
                                "expected_points"
                            ]
                        ),

                    "expected_minutes":
                        (
                            float(
                                value[
                                    "expected_minutes"
                                ]
                            )
                            if value.get(
                                "expected_minutes"
                            )
                            is not None
                            else None
                        ),
                }


                if (
                    key in output
                    and output[
                        key
                    ] != row
                ):

                    raise RuntimeError(
                        "Conflicting projection rows "
                        f"for {key}"
                    )


                output[
                    key
                ] = row


            for item in value.values():

                visit(
                    item
                )


        elif isinstance(
            value,
            list,
        ):

            for item in value:

                visit(
                    item
                )


    visit(
        payload
    )

    return output


projection_v1 = collect_projection_rows(
    load(
        V1
        / "player_projections.json"
    )
)

projection_v22 = collect_projection_rows(
    load(
        V22
        / "player_projections.json"
    )
)


# ============================================================
# Fixture -> GW
# ============================================================

fixture_horizon = load(
    V1
    / "fixture_horizon.json"
)


fixture_to_gw = {
    str(
        row[
            "fixture_id"
        ]
    ):
    int(
        row[
            "target_gameweek"
        ]
    )
    for row in fixture_horizon
}


gameweeks = sorted(
    set(
        fixture_to_gw.values()
    )
)


if gameweeks != [
    4,
    5,
    6,
    7,
    8,
    9,
]:

    raise RuntimeError(
        f"Unexpected replay gameweeks: "
        f"{gameweeks}"
    )


# ============================================================
# V1 pAppearance
#
# Fixture-level probabilities are aggregated to a gameweek:
#
# P(appears in GW)
#   = 1 - product(1 - p_fixture)
#
# which also remains valid for future DGWs.
# ============================================================

minutes_json = load(
    V1
    / "minutes.json"
)


raw_fixture_papp = {}


for row in minutes_json:

    key = (
        str(
            row[
                "player_id"
            ]
        ),
        str(
            row[
                "fixture_id"
            ]
        ),
    )

    raw_fixture_papp[
        key
    ] = float(
        row[
            "p_appearance"
        ]
    )


def aggregate_fixture_probabilities(
    fixture_probabilities,
):

    grouped = {}


    for (
        player_id,
        fixture_id,
    ), probability in (
        fixture_probabilities.items()
    ):

        gameweek = fixture_to_gw.get(
            fixture_id
        )

        if gameweek is None:
            continue


        key = (
            player_id,
            gameweek,
        )


        if key not in grouped:

            grouped[
                key
            ] = []


        grouped[
            key
        ].append(
            probability
        )


    output = {}


    for key, probabilities in grouped.items():

        no_appearance = 1.0


        for probability in probabilities:

            no_appearance *= (
                1.0
                - min(
                    1.0,
                    max(
                        0.0,
                        probability,
                    ),
                )
            )


        output[
            key
        ] = (
            1.0
            - no_appearance
        )


    return output


papp_v1 = aggregate_fixture_probabilities(
    raw_fixture_papp
)


# ============================================================
# V22 effective pAppearance
#
# V22 normally preserves pAppearance. For the tiny number of
# rows where reconciled pStart > raw pAppearance, V22 raises
# pAppearance minimally because starter => appearance.
#
# Reconstruct the exact V22 plan from the shared event layer.
# ============================================================

events_json = load(
    V1
    / "event_projections.json"
)


def fake_team(
    payload,
):

    fake_players = []


    for player in payload[
        "players"
    ]:

        rates = player[
            "rates"
        ]


        fake_rates = SimpleNamespace(
            player_id=str(
                rates[
                    "player_id"
                ]
            ),

            position=str(
                rates[
                    "position"
                ]
            ).upper(),

            p_start=float(
                rates[
                    "p_start"
                ]
            ),

            p_appearance=float(
                rates[
                    "p_appearance"
                ]
            ),

            expected_minutes=float(
                rates[
                    "expected_minutes"
                ]
            ),

            minute_distribution=tuple(
                float(value)
                for value
                in rates[
                    "minute_distribution"
                ]
            ),

            starter_minutes_distribution=tuple(
                float(value)
                for value
                in rates[
                    "starter_minutes_distribution"
                ]
            ),

            bench_minutes_distribution=tuple(
                float(value)
                for value
                in rates[
                    "bench_minutes_distribution"
                ]
            ),
        )


        fake_players.append(
            SimpleNamespace(
                rates=fake_rates
            )
        )


    return SimpleNamespace(
        team_id=str(
            payload.get(
                "team_id",
                "",
            )
        ),

        players=tuple(
            fake_players
        ),
    )


v22_simulator = object.__new__(
    FixtureSimulatorV22
)

v22_simulator._v22_team_plan_cache = {}


v22_fixture_papp = {}

v22_fixture_pstart = {}

v22_adjustments = []


for fixture in events_json:

    fixture_id = str(
        fixture[
            "fixture_id"
        ]
    )


    for side in (
        "home",
        "away",
    ):

        team = fake_team(
            fixture[
                side
            ]
        )

        plan = (
            v22_simulator
            ._build_team_plan(
                team
            )
        )


        for player_id, row in plan.items():

            key = (
                player_id,
                fixture_id,
            )

            v22_fixture_papp[
                key
            ] = float(
                row.p_appearance
            )

            v22_fixture_pstart[
                key
            ] = float(
                row.p_start
            )


            raw = float(
                row.raw_p_appearance
            )

            delta = (
                row.p_appearance
                - raw
            )


            if delta > 1e-12:

                v22_adjustments.append({
                    "player_id":
                        player_id,

                    "name":
                        names.get(
                            player_id,
                            player_id,
                        ),

                    "fixture_id":
                        fixture_id,

                    "gameweek":
                        fixture_to_gw.get(
                            fixture_id
                        ),

                    "raw_p_appearance":
                        raw,

                    "v22_p_appearance":
                        row.p_appearance,

                    "delta":
                        delta,

                    "in_saved_squad":
                        (
                            player_id
                            in squad_ids
                        ),
                })


papp_v22 = aggregate_fixture_probabilities(
    v22_fixture_papp
)


# ============================================================
# Validate decision inputs for saved squad
# ============================================================

for world_name, projection, papp in (
    (
        "V1",
        projection_v1,
        papp_v1,
    ),
    (
        "V22",
        projection_v22,
        papp_v22,
    ),
):

    for gameweek in gameweeks:

        for player_id in squad_ids:

            key = (
                player_id,
                gameweek,
            )


            if key not in projection:

                raise RuntimeError(
                    f"{world_name}: missing projection "
                    f"{names[player_id]} GW{gameweek}"
                )


            if key not in papp:

                raise RuntimeError(
                    f"{world_name}: missing pAppearance "
                    f"{names[player_id]} GW{gameweek}"
                )


# ============================================================
# Exact fixed-squad joint optimization
#
# Enumerate:
#
# - every legal starting XI,
# - every ordering of the 3 outfield substitutes,
# - exact autosub expectation,
# - every captain/vice pair inside that XI, all positions.
#
# At this scale this is small:
# only hundreds of legal XI and <= 6 bench orders each.
# ============================================================

def legal_xi(
    starter_ids,
):

    counts = {
        position:
            sum(
                positions[
                    player_id
                ]
                == position
                for player_id
                in starter_ids
            )
        for position in (
            "GK",
            "DEF",
            "MID",
            "FWD",
        )
    }


    return all((
        len(
            starter_ids
        )
        == 11,

        counts[
            "GK"
        ]
        == 1,

        3
        <= counts[
            "DEF"
        ]
        <= 5,

        2
        <= counts[
            "MID"
        ]
        <= 5,

        1
        <= counts[
            "FWD"
        ]
        <= 3,
    ))


def formation(
    starter_ids,
):

    return (
        f"{sum(positions[p] == 'DEF' for p in starter_ids)}-"
        f"{sum(positions[p] == 'MID' for p in starter_ids)}-"
        f"{sum(positions[p] == 'FWD' for p in starter_ids)}"
    )


def decision_key(
    result,
):

    #
    # Stable deterministic tie-break after EV.
    #
    return (
        tuple(
            sorted(
                result[
                    "starter_ids"
                ]
            )
        ),
        result[
            "bench_gk_id"
        ],
        tuple(
            result[
                "bench_outfield_ids"
            ]
        ),
        result[
            "captain_id"
        ],
        result[
            "vice_id"
        ],
    )


def exact_decision(
    *,
    gameweek,
    projection,
    papp,
):

    expected_points = {
        player_id:
            projection[
                (
                    player_id,
                    gameweek,
                )
            ][
                "expected_points"
            ]
        for player_id in squad_ids
    }


    appearance = {
        player_id:
            papp[
                (
                    player_id,
                    gameweek,
                )
            ]
        for player_id in squad_ids
    }


    squad_positions = {
        player_id:
            positions[
                player_id
            ]
        for player_id in squad_ids
    }


    goalkeepers = [
        player_id
        for player_id in squad_ids
        if positions[
            player_id
        ]
        == "GK"
    ]


    outfield = [
        player_id
        for player_id in squad_ids
        if positions[
            player_id
        ]
        != "GK"
    ]


    best = None

    legal_lineups = 0
    evaluated_orders = 0


    #
    # Exactly one starting goalkeeper.
    #
    for starting_gk in goalkeepers:

        bench_gk = next(
            player_id
            for player_id
            in goalkeepers
            if player_id
            != starting_gk
        )


        #
        # Need 10 outfield starters from 13.
        #
        for starting_outfield in combinations(
            outfield,
            10,
        ):

            starters = (
                starting_gk,
                *starting_outfield,
            )


            if not legal_xi(
                starters
            ):

                continue


            legal_lineups += 1


            bench_outfield = [
                player_id
                for player_id
                in outfield
                if player_id
                not in starting_outfield
            ]


            if len(
                bench_outfield
            ) != 3:

                raise RuntimeError(
                    "Expected exactly three "
                    "outfield substitutes."
                )


            for bench_order in permutations(
                bench_outfield
            ):

                evaluated_orders += 1


                autosub = (
                    evaluate_autosub_lineup(
                        gameweek=gameweek,

                        starter_ids=starters,

                        bench_gk_id=bench_gk,

                        bench_outfield_ids=(
                            bench_order
                        ),

                        positions=(
                            squad_positions
                        ),

                        expected_points=(
                            expected_points
                        ),

                        p_appearance=(
                            appearance
                        ),
                    )
                )


                captaincy = (
                    best_captaincy_pair(
                        player_ids=(
                            autosub.starter_ids
                        ),

                        expected_points=(
                            expected_points
                        ),

                        p_appearance=(
                            appearance
                        ),

                        positions=(
                            squad_positions
                        ),

                        allowed_positions=(
                            ALL_CAPTAIN_POSITIONS
                        ),
                    )
                )


                total = (
                    float(
                        autosub.total_ev
                    )
                    + float(
                        captaincy.captain_bonus
                    )
                )


                candidate = {
                    "gameweek":
                        gameweek,

                    "starter_ids":
                        tuple(
                            autosub.starter_ids
                        ),

                    "bench_gk_id":
                        autosub.bench_gk_id,

                    "bench_outfield_ids":
                        tuple(
                            autosub
                            .bench_outfield_ids
                        ),

                    "formation":
                        formation(
                            autosub.starter_ids
                        ),

                    "captain_id":
                        captaincy.captain_id,

                    "vice_id":
                        captaincy.vice_id,

                    "base_xi_ev":
                        float(
                            autosub.base_xi_ev
                        ),

                    "gk_autosub_ev":
                        float(
                            autosub
                            .expected_gk_autosub_ev
                        ),

                    "outfield_autosub_ev":
                        float(
                            autosub
                            .expected_outfield_autosub_ev
                        ),

                    "autosub_total_ev":
                        float(
                            autosub.total_ev
                        ),

                    "captain_bonus_ev":
                        float(
                            captaincy.captain_bonus
                        ),

                    "total_ev":
                        total,

                    "captain_ev":
                        float(
                            captaincy.captain_ev
                        ),

                    "vice_ev":
                        float(
                            captaincy.vice_ev
                        ),

                    "captain_p_appearance":
                        float(
                            captaincy
                            .captain_p_appearance
                        ),

                    "vice_p_appearance":
                        float(
                            captaincy
                            .vice_p_appearance
                        ),
                }


                if best is None:

                    best = candidate

                    continue


                delta = (
                    candidate[
                        "total_ev"
                    ]
                    - best[
                        "total_ev"
                    ]
                )


                if (
                    delta > 1e-12
                    or (
                        abs(
                            delta
                        )
                        <= 1e-12
                        and decision_key(
                            candidate
                        )
                        < decision_key(
                            best
                        )
                    )
                ):

                    best = candidate


    if best is None:

        raise RuntimeError(
            f"No legal decision for GW"
            f"{gameweek}"
        )


    best[
        "legal_lineups"
    ] = legal_lineups

    best[
        "evaluated_bench_orders"
    ] = evaluated_orders


    #
    # Cross-check against standalone autosub optimizer.
    #
    autosub_only = (
        optimize_autosub_lineup(
            gameweek=gameweek,

            squad_ids=squad_ids,

            positions=(
                squad_positions
            ),

            expected_points=(
                expected_points
            ),

            p_appearance=(
                appearance
            ),
        )
    )


    best[
        "autosub_only_optimizer_ev"
    ] = float(
        autosub_only.total_ev
    )


    best[
        "joint_vs_autosub_only_lineup_changed"
    ] = (
        set(
            best[
                "starter_ids"
            ]
        )
        != set(
            autosub_only.starter_ids
        )
        or best[
            "bench_gk_id"
        ]
        != autosub_only.bench_gk_id
        or tuple(
            best[
                "bench_outfield_ids"
            ]
        )
        != tuple(
            autosub_only
            .bench_outfield_ids
        )
    )


    return best


# ============================================================
# Run V1 and V22 decisions
# ============================================================

decisions = {
    "v1": {},
    "v22": {},
}


for gameweek in gameweeks:

    decisions[
        "v1"
    ][
        gameweek
    ] = exact_decision(
        gameweek=gameweek,
        projection=projection_v1,
        papp=papp_v1,
    )


    decisions[
        "v22"
    ][
        gameweek
    ] = exact_decision(
        gameweek=gameweek,
        projection=projection_v22,
        papp=papp_v22,
    )


# ============================================================
# Comparison
# ============================================================

comparisons = []


for gameweek in gameweeks:

    old = decisions[
        "v1"
    ][
        gameweek
    ]

    new = decisions[
        "v22"
    ][
        gameweek
    ]


    old_starters = set(
        old[
            "starter_ids"
        ]
    )

    new_starters = set(
        new[
            "starter_ids"
        ]
    )


    comparisons.append({
        "gameweek":
            gameweek,

        "v1_total_ev":
            old[
                "total_ev"
            ],

        "v22_total_ev":
            new[
                "total_ev"
            ],

        "delta_total_ev":
            (
                new[
                    "total_ev"
                ]
                - old[
                    "total_ev"
                ]
            ),

        "xi_changed":
            (
                old_starters
                != new_starters
            ),

        "xi_out":
            sorted(
                old_starters
                - new_starters
            ),

        "xi_in":
            sorted(
                new_starters
                - old_starters
            ),

        "bench_changed":
            (
                old[
                    "bench_gk_id"
                ]
                != new[
                    "bench_gk_id"
                ]
                or tuple(
                    old[
                        "bench_outfield_ids"
                    ]
                )
                != tuple(
                    new[
                        "bench_outfield_ids"
                    ]
                )
            ),

        "captain_changed":
            (
                old[
                    "captain_id"
                ]
                != new[
                    "captain_id"
                ]
            ),

        "vice_changed":
            (
                old[
                    "vice_id"
                ]
                != new[
                    "vice_id"
                ]
            ),
    })


# ============================================================
# Structural validation
# ============================================================

def decision_is_valid(
    result,
):

    starter_ids = tuple(
        result[
            "starter_ids"
        ]
    )


    bench = (
        result[
            "bench_gk_id"
        ],
        *result[
            "bench_outfield_ids"
        ],
    )


    return all((
        legal_xi(
            starter_ids
        ),

        len(
            starter_ids
        )
        == 11,

        len(
            bench
        )
        == 4,

        len(
            set(
                starter_ids
            )
            | set(
                bench
            )
        )
        == 15,

        set(
            starter_ids
        ).isdisjoint(
            bench
        ),

        result[
            "captain_id"
        ]
        in starter_ids,

        result[
            "vice_id"
        ]
        in starter_ids,

        result[
            "captain_id"
        ]
        != result[
            "vice_id"
        ],

        math.isclose(
            result[
                "total_ev"
            ],
            result[
                "autosub_total_ev"
            ]
            + result[
                "captain_bonus_ev"
            ],
            abs_tol=1e-10,
            rel_tol=0.0,
        ),
    ))


decision_structure_gate = all(
    decision_is_valid(
        decisions[
            world
        ][
            gameweek
        ]
    )
    for world in (
        "v1",
        "v22",
    )
    for gameweek
    in gameweeks
)


projection_input_gate = all(
    (
        player_id,
        gameweek,
    )
    in projection_v1
    and (
        player_id,
        gameweek,
    )
    in projection_v22
    and (
        player_id,
        gameweek,
    )
    in papp_v1
    and (
        player_id,
        gameweek,
    )
    in papp_v22
    for player_id
    in squad_ids
    for gameweek
    in gameweeks
)


joint_search_gate = all(
    (
        decisions[
            world
        ][
            gameweek
        ][
            "legal_lineups"
        ]
        > 0
        and decisions[
            world
        ][
            gameweek
        ][
            "evaluated_bench_orders"
        ]
        > 0
    )
    for world in (
        "v1",
        "v22",
    )
    for gameweek
    in gameweeks
)


gate = all((
    squad_structure_gate,
    projection_input_gate,
    decision_structure_gate,
    joint_search_gate,
))


# ============================================================
# Human-readable serialization
# ============================================================

def readable_decision(
    result,
):

    return {
        **{
            key:
                value
            for key, value
            in result.items()
            if key
            not in {
                "starter_ids",
                "bench_gk_id",
                "bench_outfield_ids",
                "captain_id",
                "vice_id",
            }
        },

        "starters": [
            {
                "player_id":
                    player_id,

                "name":
                    names[
                        player_id
                    ],

                "position":
                    positions[
                        player_id
                    ],
            }
            for player_id
            in result[
                "starter_ids"
            ]
        ],

        "bench_gk": {
            "player_id":
                result[
                    "bench_gk_id"
                ],

            "name":
                names[
                    result[
                        "bench_gk_id"
                    ]
                ],
        },

        "bench_outfield": [
            {
                "player_id":
                    player_id,

                "name":
                    names[
                        player_id
                    ],

                "position":
                    positions[
                        player_id
                    ],
            }
            for player_id
            in result[
                "bench_outfield_ids"
            ]
        ],

        "captain": {
            "player_id":
                result[
                    "captain_id"
                ],

            "name":
                names[
                    result[
                        "captain_id"
                    ]
                ],
        },

        "vice": {
            "player_id":
                result[
                    "vice_id"
                ],

            "name":
                names[
                    result[
                        "vice_id"
                    ]
                ],
        },
    }


readable_comparisons = []


for item in comparisons:

    readable_comparisons.append({
        **{
            key:
                value
            for key, value
            in item.items()
            if key
            not in {
                "xi_out",
                "xi_in",
            }
        },

        "xi_out": [
            names[
                player_id
            ]
            for player_id
            in item[
                "xi_out"
            ]
        ],

        "xi_in": [
            names[
                player_id
            ]
            for player_id
            in item[
                "xi_in"
            ]
        ],
    })


report = {
    "status":
        "CAPTAIN_068G_C_"
        "DECISION_IMPACT",

    "source_runs": {
        "v1":
            str(
                V1.relative_to(
                    ROOT
                )
            ),

        "v22":
            str(
                V22.relative_to(
                    ROOT
                )
            ),
    },

    "network_refresh":
        False,

    "current_2026_27_outcomes_used":
        False,

    "production_default_changed":
        False,

    "transfer_optimization":
        False,

    "chips":
        False,

    "captaincy_allowed_positions":
        list(
            ALL_CAPTAIN_POSITIONS
        ),

    "saved_wc_resolution":
        resolution,

    "position_counts":
        position_counts,

    "v22_pappearance_adjustments": {
        "all_rows":
            len(
                v22_adjustments
            ),

        "saved_squad_rows":
            sum(
                row[
                    "in_saved_squad"
                ]
                for row in v22_adjustments
            ),

        "saved_squad":
            [
                row
                for row
                in v22_adjustments
                if row[
                    "in_saved_squad"
                ]
            ],
    },

    "decisions": {
        world: {
            str(
                gameweek
            ):
                readable_decision(
                    decisions[
                        world
                    ][
                        gameweek
                    ]
                )
            for gameweek
            in gameweeks
        }
        for world
        in (
            "v1",
            "v22",
        )
    },

    "comparison":
        readable_comparisons,

    "summary": {
        "xi_changed_gameweeks":
            sum(
                row[
                    "xi_changed"
                ]
                for row
                in comparisons
            ),

        "bench_changed_gameweeks":
            sum(
                row[
                    "bench_changed"
                ]
                for row
                in comparisons
            ),

        "captain_changed_gameweeks":
            sum(
                row[
                    "captain_changed"
                ]
                for row
                in comparisons
            ),

        "vice_changed_gameweeks":
            sum(
                row[
                    "vice_changed"
                ]
                for row
                in comparisons
            ),

        "mean_total_ev_delta":
            mean(
                row[
                    "delta_total_ev"
                ]
                for row
                in comparisons
            ),
    },

    "gates": {
        "saved_squad_structure":
            squad_structure_gate,

        "projection_inputs":
            projection_input_gate,

        "decision_structure":
            decision_structure_gate,

        "joint_exact_search":
            joint_search_gate,

        "overall":
            gate,
    },
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)


# ============================================================
# Console report
# ============================================================

print(
    "=== CAPTAIN-068G-C DECISION IMPACT ==="
)

print(
    "network refresh:",
    "NO",
)

print(
    "2026/27 outcomes used:",
    "NO",
)

print(
    "production default changed:",
    "NO",
)

print(
    "transfers optimized:",
    "NO",
)

print(
    "chips:",
    "NO",
)

print(
    "captain positions:",
    ",".join(
        ALL_CAPTAIN_POSITIONS
    ),
)


print()
print(
    "=== SAVED WC SQUAD ==="
)

for row in resolution:

    print(
        f"{row['position']:<3} "
        f"{row['requested']:<18} "
        f"-> {row['resolved']}"
    )


print()
print(
    "position counts:",
    position_counts,
)

print(
    "V22 pAppearance raises in saved squad:",
    sum(
        row[
            "in_saved_squad"
        ]
        for row
        in v22_adjustments
    ),
)


def print_decision(
    label,
    result,
):

    starters_by_position = []


    for position in (
        "GK",
        "DEF",
        "MID",
        "FWD",
    ):

        selected = [
            names[
                player_id
            ]
            for player_id
            in result[
                "starter_ids"
            ]
            if positions[
                player_id
            ]
            == position
        ]

        starters_by_position.append(
            (
                position,
                selected,
            )
        )


    print(
        f"{label}: "
        f"EV={result['total_ev']:.3f} "
        f"autosub={result['autosub_total_ev']:.3f} "
        f"Cbonus={result['captain_bonus_ev']:.3f} "
        f"formation={result['formation']}"
    )


    for position, selected in starters_by_position:

        print(
            f"    {position:<3}: "
            + ", ".join(
                selected
            )
        )


    print(
        "    BENCH GK:",
        names[
            result[
                "bench_gk_id"
            ]
        ],
    )

    print(
        "    BENCH 1-3:",
        " | ".join(
            names[
                player_id
            ]
            for player_id
            in result[
                "bench_outfield_ids"
            ]
        ),
    )

    print(
        "    C / VC:",
        names[
            result[
                "captain_id"
            ]
        ],
        "/",
        names[
            result[
                "vice_id"
            ]
        ],
    )


for gameweek in gameweeks:

    old = decisions[
        "v1"
    ][
        gameweek
    ]

    new = decisions[
        "v22"
    ][
        gameweek
    ]

    comparison = next(
        row
        for row in comparisons
        if row[
            "gameweek"
        ]
        == gameweek
    )


    print()
    print(
        "=" * 72
    )

    print(
        f"GW{gameweek}"
    )

    print(
        "=" * 72
    )


    print_decision(
        "V1 ",
        old,
    )

    print()

    print_decision(
        "V22",
        new,
    )


    print()

    print(
        "delta total EV:",
        f"{comparison['delta_total_ev']:+.3f}",
    )

    print(
        "XI changed:",
        (
            "YES"
            if comparison[
                "xi_changed"
            ]
            else "NO"
        ),
    )


    if comparison[
        "xi_changed"
    ]:

        print(
            "    OUT:",
            ", ".join(
                names[
                    player_id
                ]
                for player_id
                in comparison[
                    "xi_out"
                ]
            )
            or "-",
        )

        print(
            "    IN :",
            ", ".join(
                names[
                    player_id
                ]
                for player_id
                in comparison[
                    "xi_in"
                ]
            )
            or "-",
        )


    print(
        "bench changed:",
        (
            "YES"
            if comparison[
                "bench_changed"
            ]
            else "NO"
        ),
    )

    print(
        "captain changed:",
        (
            "YES"
            if comparison[
                "captain_changed"
            ]
            else "NO"
        ),
    )

    print(
        "vice changed:",
        (
            "YES"
            if comparison[
                "vice_changed"
            ]
            else "NO"
        ),
    )


print()
print(
    "=== SUMMARY ==="
)

print(
    "XI changed:",
    report[
        "summary"
    ][
        "xi_changed_gameweeks"
    ],
    "/ 6 GWs",
)

print(
    "bench changed:",
    report[
        "summary"
    ][
        "bench_changed_gameweeks"
    ],
    "/ 6 GWs",
)

print(
    "captain changed:",
    report[
        "summary"
    ][
        "captain_changed_gameweeks"
    ],
    "/ 6 GWs",
)

print(
    "vice changed:",
    report[
        "summary"
    ][
        "vice_changed_gameweeks"
    ],
    "/ 6 GWs",
)

print(
    "mean total EV delta:",
    f"{report['summary']['mean_total_ev_delta']:+.3f}",
)


print()
print(
    "=== GATES ==="
)

for name, value in report[
    "gates"
].items():

    print(
        f"{name:<28}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "DECISION IMPACT GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not gate:

    raise RuntimeError(
        "CAPTAIN-068G-C decision "
        "impact gate failed."
    )
