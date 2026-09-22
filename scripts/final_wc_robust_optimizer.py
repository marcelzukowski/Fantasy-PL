from __future__ import annotations

import inspect
import json
import math
import statistics
import unicodedata

from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass, replace
from itertools import combinations, permutations
from pathlib import Path

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)

from fpl_engine.decision.value import (
    build_player_values,
)

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)

from fpl_engine.decision import autosubs as autosub_module


# ============================================================
# FINAL WC ROBUST OPTIMIZER
#
# INPUT:
#   4 x 256 simulation runs
#
# CANDIDATES:
#   SEED 42
#   SEED 202627
#   SEED 606
#   SEED 91991
#   MEAN
#   PESSIMISTIC = mean - 0.75 * sigma
#
# RULES:
#   - Haaland REQUIRED
#   - captaincy ignored
#   - horizon GW4-GW9
#   - weighted GW EV
#   - real current liquidation budget
#   - max 3 players / club
#
# CROSS-SCORE:
#   - every candidate on every run
#   - bench-aware autosubs
# ============================================================


ROOT = Path.cwd()

RUN_ROOT = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

RUN_MAP = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_256_run_map.txt"
)

OUTPUT = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_robust_results.json"
)

GAMEWEEKS = tuple(
    range(4, 10)
)

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)

CURRENT_BANK = 0


CURRENT_SQUAD = (
    "Donnarumma",
    "D\u00fabravka",
    "Thomas",
    "Diop",
    "Virgil",
    "Gvardiol",
    "Shaw",
    "Ndiaye",
    "Szoboszlai",
    "B.Fernandes",
    "Mbeumo",
    "Xhaka",
    "Jo\u00e3o Pedro",
    "Kusi-Asare",
    "Haaland",
)


SELLING_BY_NAME = {
    "donnarumma": 55,
    "dubravka": 40,
    "thomas": 40,
    "diop": 40,
    "virgil": 65,
    "gvardiol": 55,
    "shaw": 44,
    "ndiaye": 59,
    "szoboszlai": 70,
    "bfernandes": 120,
    "mbeumo": 79,
    "xhaka": 55,
    "joaopedro": 76,
    "kusiasare": 45,
    "haaland": 155,
}


# ============================================================
# HELPERS
# ============================================================


def normalize(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    return "".join(
        char.casefold()
        for char in text
        if char.isalnum()
    )


def run_ids():

    lines = RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    output = []

    for line in lines:

        if "run=" not in line:
            continue

        seed_part = (
            line.split(
                "run=",
                1,
            )[0]
        )

        run_id = (
            line.split(
                "run=",
                1,
            )[1].strip()
        )

        seed = (
            seed_part
            .split("seed=", 1)[1]
            .strip()
        )

        output.append(
            (
                seed,
                run_id,
            )
        )

    if len(output) != 4:
        raise RuntimeError(
            "Expected exactly 4 final runs"
        )

    return output


def load_minutes(path):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(raw, dict):
        for key in (
            "minutes",
            "rows",
            "data",
            "records",
        ):
            if isinstance(
                raw.get(key),
                list,
            ):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise RuntimeError(
            "Unsupported minutes.json structure"
        )


    # minutes.json is fixture-level and does not
    # necessarily contain a direct gameweek field.
    # Resolve fixture_id -> GW from fixture_horizon.json.

    fixture_path = (
        path.parent
        / "fixture_horizon.json"
    )

    fixture_rows = json.loads(
        fixture_path.read_text(
            encoding="utf-8"
        )
    )

    fixture_to_gw = {}

    for row in fixture_rows:

        if not isinstance(row, dict):
            continue

        gw = (
            row.get("target_gameweek")
            or row.get("gameweek")
            or row.get("event")
        )

        if gw is None:
            continue

        for key in (
            "fixture_id",
            "canonical_fixture_id",
            "id",
        ):
            value = row.get(key)

            if value is not None:
                fixture_to_gw[
                    str(value)
                ] = int(gw)


    grouped = defaultdict(list)
    unresolved_fixture_ids = set()


    for row in raw:

        if not isinstance(row, dict):
            continue

        player_id = row.get(
            "player_id"
        )

        gameweek = (
            row.get("gameweek")
            or row.get(
                "target_gameweek"
            )
        )

        if gameweek is None:

            fixture_id = row.get(
                "fixture_id"
            )

            if fixture_id is not None:

                gameweek = (
                    fixture_to_gw.get(
                        str(fixture_id)
                    )
                )

                if gameweek is None:
                    unresolved_fixture_ids.add(
                        str(fixture_id)
                    )


        probability = row.get(
            "p_appearance"
        )

        if probability is None:
            probability = row.get(
                "appearance_probability"
            )


        if (
            not player_id
            or gameweek is None
            or probability is None
        ):
            continue


        grouped[
            (
                str(player_id),
                int(gameweek),
            )
        ].append(
            float(probability)
        )


    output = {}

    for key, values in grouped.items():

        output[key] = (
            1.0
            - math.prod(
                1.0
                - max(
                    0.0,
                    min(
                        1.0,
                        value,
                    ),
                )
                for value in values
            )
        )


    if not output:
        raise RuntimeError(
            "No availability rows could be "
            "mapped to Gameweeks"
        )


    return output

def load_run(
    seed,
    run_id,
):

    path = (
        RUN_ROOT
        / run_id
    )

    player_rows = json.loads(
        (
            path
            / "current_players.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    raw_projections = json.loads(
        (
            path
            / "player_projections.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    projections = (
        adapt_player_projections(
            raw_projections
        )
    )

    metadata = {
        str(row["player_id"]): row
        for row in player_rows
    }

    projections_by_id = {
        row.player_id: row
        for row in projections
    }

    players = (
        build_player_values(
            projections,
            metadata,
        )
    )

    players_by_id = {
        row.player_id: row
        for row in players
    }

    minutes = load_minutes(
        path
        / "minutes.json"
    )

    return {
        "seed": seed,
        "run_id": run_id,
        "path": path,
        "player_rows": player_rows,
        "metadata": metadata,
        "projections": projections,
        "projections_by_id": (
            projections_by_id
        ),
        "players": players,
        "players_by_id": (
            players_by_id
        ),
        "p_appearance": minutes,
    }


def points_for(
    projection,
    gameweek,
):

    for row in projection.gameweeks:

        if row.gameweek == gameweek:
            return float(
                row.expected_points
            )

    return 0.0


# ============================================================
# LOAD RUNS
# ============================================================


runs = [
    load_run(
        seed,
        run_id,
    )
    for seed, run_id
    in run_ids()
]


print()
print(
    "=========================================="
)
print(
    "FINAL WC ROBUST OPTIMIZER"
)
print(
    "=========================================="
)

print(
    "runs:",
    ", ".join(
        run["run_id"]
        for run in runs
    ),
)

print(
    "simulation worlds:",
    len(runs),
)

print(
    "GW:",
    list(GAMEWEEKS),
)


# ============================================================
# RESOLVE CURRENT SQUAD
# ============================================================


reference = runs[0]

name_index = defaultdict(list)

for player in reference["players"]:

    name_index[
        normalize(
            player.name
        )
    ].append(
        player.player_id
    )


current_ids = set()
selling_prices = {}


# ============================================================
# CURRENT SQUAD RESOLUTION
#
# Prefer canonical IDs already stored in the validated
# my_squad_gw4.json artifact.
#
# Only fall back to name + position + price matching.
# ============================================================


SQUAD_STATE_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)


def collect_known_player_ids(
    value,
    known_ids,
):

    found = set()

    if isinstance(
        value,
        str,
    ):

        if value in known_ids:
            found.add(
                value
            )

        return found


    if isinstance(
        value,
        dict,
    ):

        for child in value.values():

            found.update(
                collect_known_player_ids(
                    child,
                    known_ids,
                )
            )

        return found


    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):

        for child in value:

            found.update(
                collect_known_player_ids(
                    child,
                    known_ids,
                )
            )

        return found


    return found


known_player_ids = set(
    reference[
        "players_by_id"
    ]
)


resolver_source = None


if SQUAD_STATE_PATH.exists():

    squad_state_raw = json.loads(
        SQUAD_STATE_PATH.read_text(
            encoding="utf-8"
        )
    )

    canonical_ids = (
        collect_known_player_ids(
            squad_state_raw,
            known_player_ids,
        )
    )

    if len(canonical_ids) == 15:

        current_ids = set(
            canonical_ids
        )

        resolver_source = (
            "my_squad_gw4.json canonical IDs"
        )


# ------------------------------------------------------------
# Fallback only if canonical squad IDs were not available.
# ------------------------------------------------------------

if len(current_ids) != 15:

    current_ids = set()

    expected_positions = {
        "donnarumma": "GK",
        "dubravka": "GK",
        "thomas": "DEF",
        "diop": "DEF",
        "virgil": "DEF",
        "gvardiol": "DEF",
        "shaw": "DEF",
        "ndiaye": "MID",
        "szoboszlai": "MID",
        "bfernandes": "MID",
        "mbeumo": "MID",
        "xhaka": "MID",
        "joaopedro": "FWD",
        "kusiasare": "FWD",
        "haaland": "FWD",
    }


    for name in CURRENT_SQUAD:

        key = normalize(
            name
        )

        matches = list(
            name_index.get(
                key,
                [],
            )
        )


        expected_position = (
            expected_positions[
                key
            ]
        )


        matches = [
            player_id
            for player_id
            in matches
            if (
                reference[
                    "players_by_id"
                ][
                    player_id
                ].position
                == expected_position
            )
        ]


        # If duplicate display names still remain,
        # use the known current selling/current-price
        # level as an additional disambiguator.
        if (
            len(matches) > 1
            and key
            in SELLING_BY_NAME
        ):

            expected_price = (
                SELLING_BY_NAME[
                    key
                ]
            )

            price_matches = [
                player_id
                for player_id
                in matches
                if (
                    reference[
                        "players_by_id"
                    ][
                        player_id
                    ].price_tenths
                    == expected_price
                )
            ]

            if len(
                price_matches
            ) == 1:

                matches = (
                    price_matches
                )


        if len(matches) != 1:

            details = []

            for player_id in matches:

                player = (
                    reference[
                        "players_by_id"
                    ][
                        player_id
                    ]
                )

                details.append(
                    {
                        "id": player_id,
                        "name": player.name,
                        "position": player.position,
                        "price": player.price_tenths,
                        "team": player.team_id,
                    }
                )

            raise RuntimeError(
                "Cannot uniquely resolve "
                f"{name}: {details}"
            )


        current_ids.add(
            matches[0]
        )


    resolver_source = (
        "name + position + price fallback"
    )


if len(current_ids) != 15:

    raise RuntimeError(
        "Current squad != 15 players: "
        f"{len(current_ids)}"
    )


# ------------------------------------------------------------
# Selling prices
# ------------------------------------------------------------

for player_id in current_ids:

    player = (
        reference[
            "players_by_id"
        ][
            player_id
        ]
    )

    key = normalize(
        player.name
    )

    if key not in SELLING_BY_NAME:

        raise RuntimeError(
            "Missing selling price for "
            f"{player.name} "
            f"({player_id})"
        )

    selling_prices[
        player_id
    ] = (
        SELLING_BY_NAME[
            key
        ]
    )


print(
    "current squad resolved: 15/15"
)

print(
    "resolver:",
    resolver_source,
)




haaland_ids = [
    player.player_id
    for player
    in reference["players"]
    if normalize(
        player.name
    ) == "haaland"
]

if len(haaland_ids) != 1:
    raise RuntimeError(
        "Haaland resolution failed"
    )

HAALAND_ID = (
    haaland_ids[0]
)


print(
    "current squad resolved: 15/15"
)

print(
    "Haaland:",
    reference[
        "players_by_id"
    ][
        HAALAND_ID
    ].name,
)


# ============================================================
# SYNTHETIC PROJECTIONS
# ============================================================


def synthetic_projection_map(
    mode,
):

    output = {}

    ids = (
        reference[
            "projections_by_id"
        ].keys()
    )


    for player_id in ids:

        base = (
            reference[
                "projections_by_id"
            ][player_id]
        )

        new_gameweeks = []


        for gameweek in GAMEWEEKS:

            values = [
                points_for(
                    run[
                        "projections_by_id"
                    ][player_id],
                    gameweek,
                )
                for run in runs
            ]


            if mode == "MEAN":

                value = (
                    statistics.mean(
                        values
                    )
                )


            elif mode == "PESS":

                mu = (
                    statistics.mean(
                        values
                    )
                )

                sigma = (
                    statistics.pstdev(
                        values
                    )
                )

                value = max(
                    0.0,
                    mu
                    - 0.75
                    * sigma,
                )


            else:

                raise ValueError(
                    mode
                )


            template = next(
                row
                for row
                in base.gameweeks
                if (
                    row.gameweek
                    == gameweek
                )
            )


            new_gameweeks.append(
                replace(
                    template,
                    expected_points=(
                        value
                    ),
                )
            )


        def aggregate(count):

            rows = (
                new_gameweeks[
                    :count
                ]
            )

            raw = sum(
                row.expected_points
                for row in rows
            )

            weighted = sum(
                row.expected_points
                * WEIGHTS[index]
                for index, row
                in enumerate(rows)
            )

            return (
                raw,
                weighted,
            )


        raw3, weighted3 = (
            aggregate(3)
        )

        raw6, weighted6 = (
            aggregate(6)
        )


        h3 = replace(
            base.horizon_3,
            first_gameweek=4,
            last_gameweek=6,
            raw_expected_points=raw3,
            weighted_expected_points=(
                weighted3
            ),
            gameweeks=3,
        )


        h6 = replace(
            base.horizon_6,
            first_gameweek=4,
            last_gameweek=9,
            raw_expected_points=raw6,
            weighted_expected_points=(
                weighted6
            ),
            gameweeks=6,
        )


        output[player_id] = replace(
            base,
            current_gameweek=4,
            gameweeks=tuple(
                new_gameweeks
            ),
            horizon_3=h3,
            horizon_6=h6,
            expected_minutes_next_3=(
                statistics.mean(
                    run[
                        "projections_by_id"
                    ][player_id]
                    .expected_minutes_next_3
                    for run in runs
                )
            ),
            expected_minutes_next_6=(
                statistics.mean(
                    run[
                        "projections_by_id"
                    ][player_id]
                    .expected_minutes_next_6
                    for run in runs
                )
            ),
            projection_confidence=(
                statistics.mean(
                    run[
                        "projections_by_id"
                    ][player_id]
                    .projection_confidence
                    for run in runs
                )
            ),
            projection_uncertainty=(
                statistics.mean(
                    run[
                        "projections_by_id"
                    ][player_id]
                    .projection_uncertainty
                    for run in runs
                )
            ),
        )


    return output


mean_projection_map = (
    synthetic_projection_map(
        "MEAN"
    )
)

pess_projection_map = (
    synthetic_projection_map(
        "PESS"
    )
)


# ============================================================
# CREATE WC CANDIDATES
# ============================================================


source_candidates = []


def optimize_candidate(
    label,
    projections_by_id,
):

    plan = (
        optimize_unlimited_squad(
            player_rows=(
                reference[
                    "player_rows"
                ]
            ),
            projections_by_id=(
                projections_by_id
            ),
            current_player_ids=(
                current_ids
            ),
            selling_prices_tenths=(
                selling_prices
            ),
            bank_tenths=(
                CURRENT_BANK
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
            required_player_ids=(
                HAALAND_ID,
            ),
        )
    )

    source_candidates.append(
        {
            "label": label,
            "ids": frozenset(
                plan.player_ids
            ),
            "remaining_budget": (
                plan
                .remaining_budget_tenths
            ),
            "optimizer_xi_ev": (
                plan.weighted_xi_ev
            ),
        }
    )

    print(
        f"{label:<14} "
        f"optimizer XI EV="
        f"{plan.weighted_xi_ev:.2f} "
        f"bank="
        f"£{plan.remaining_budget_tenths/10:.1f}m"
    )


print()
print(
    "=========================================="
)
print(
    "GENERATING WC CANDIDATES"
)
print(
    "=========================================="
)


for run in runs:

    optimize_candidate(
        "SEED_"
        + run["seed"],
        run[
            "projections_by_id"
        ],
    )


optimize_candidate(
    "MEAN",
    mean_projection_map,
)

optimize_candidate(
    "PESS_075SD",
    pess_projection_map,
)


# ============================================================
# PLAYER CONSENSUS
# ============================================================


selection_count = Counter()

for candidate in source_candidates:

    selection_count.update(
        candidate["ids"]
    )


print()
print(
    "=========================================="
)
print(
    "PLAYER CONSENSUS"
)
print(
    "=========================================="
)


for position in (
    "GK",
    "DEF",
    "MID",
    "FWD",
):

    print()
    print(position)

    rows = []

    for player_id, count in (
        selection_count.items()
    ):

        player = (
            reference[
                "players_by_id"
            ][player_id]
        )

        if (
            player.position
            != position
        ):
            continue

        rows.append(
            (
                -count,
                player.name,
                player.price_m,
                count,
            )
        )


    for (
        _,
        name,
        price,
        count,
    ) in sorted(rows):

        print(
            f"  {name:<22} "
            f"{count}/6   "
            f"£{price:.1f}"
        )


# ============================================================
# DEDUP CANDIDATES
# ============================================================


dedup = {}


for candidate in source_candidates:

    key = (
        candidate["ids"]
    )

    if key not in dedup:

        dedup[key] = {
            **candidate,
            "sources": [
                candidate[
                    "label"
                ]
            ],
        }

    else:

        dedup[key][
            "sources"
        ].append(
            candidate[
                "label"
            ]
        )


candidates = list(
    dedup.values()
)


print()
print(
    "unique candidate squads:",
    len(candidates),
)


# ============================================================
# BENCH-AWARE SCORING
# ============================================================


optimize_autosub = getattr(
    autosub_module,
    "optimize_autosub_lineup",
    None,
)

evaluate_autosub = getattr(
    autosub_module,
    "evaluate_autosub_lineup",
    None,
)


def result_total(result):

    preferred = (
        "total_ev",
        "total_expected_points",
        "expected_total_points",
        "total_expected_value",
        "expected_points",
    )


    for name in preferred:

        if hasattr(
            result,
            name,
        ):

            value = getattr(
                result,
                name,
            )

            if isinstance(
                value,
                (
                    int,
                    float,
                ),
            ):

                return float(value)


    if is_dataclass(result):

        values = asdict(
            result
        )

        for key, value in (
            values.items()
        ):

            key_lower = (
                key.casefold()
            )

            if (
                "total"
                in key_lower
                and (
                    "ev"
                    in key_lower
                    or "point"
                    in key_lower
                )
                and isinstance(
                    value,
                    (
                        int,
                        float,
                    ),
                )
            ):
                return float(value)


    raise RuntimeError(
        "Cannot extract autosub total "
        f"from {result!r}"
    )


def call_optimize_autosub(
    *,
    squad_ids,
    gameweek,
    positions,
    expected_points,
    p_appearance,
):

    if (
        optimize_autosub
        is None
    ):
        return None


    signature = (
        inspect.signature(
            optimize_autosub
        )
    )


    aliases = {
        "gameweek": gameweek,
        "squad_player_ids": (
            squad_ids
        ),
        "squad_ids": squad_ids,
        "player_ids": squad_ids,
        "positions": positions,
        "expected_points": (
            expected_points
        ),
        "p_appearance": (
            p_appearance
        ),
    }


    kwargs = {}


    for name, parameter in (
        signature
        .parameters
        .items()
    ):

        if name in aliases:

            kwargs[
                name
            ] = aliases[
                name
            ]

        elif (
            parameter.default
            is inspect._empty
        ):

            return None


    return optimize_autosub(
        **kwargs
    )


def exhaustive_autosub(
    *,
    squad_ids,
    gameweek,
    positions,
    expected_points,
    p_appearance,
):

    if evaluate_autosub is None:

        raise RuntimeError(
            "No autosub evaluator available"
        )


    gks = [
        player_id
        for player_id
        in squad_ids
        if positions[
            player_id
        ] == "GK"
    ]

    outfield = [
        player_id
        for player_id
        in squad_ids
        if positions[
            player_id
        ] != "GK"
    ]


    if (
        len(gks) != 2
        or len(outfield) != 13
    ):

        raise RuntimeError(
            "Invalid FPL squad shape"
        )


    best = None


    for starting_gk in gks:

        bench_gk = next(
            player_id
            for player_id
            in gks
            if (
                player_id
                != starting_gk
            )
        )


        for starters_out in combinations(
            outfield,
            10,
        ):

            counts = Counter(
                positions[
                    player_id
                ]
                for player_id
                in starters_out
            )


            if not (
                3
                <= counts["DEF"]
                <= 5
            ):
                continue

            if not (
                2
                <= counts["MID"]
                <= 5
            ):
                continue

            if not (
                1
                <= counts["FWD"]
                <= 3
            ):
                continue


            bench_out = [
                player_id
                for player_id
                in outfield
                if (
                    player_id
                    not in starters_out
                )
            ]


            starter_ids = (
                (
                    starting_gk,
                )
                + tuple(
                    starters_out
                )
            )


            for order in permutations(
                bench_out
            ):

                result = (
                    evaluate_autosub(
                        gameweek=gameweek,
                        starter_ids=(
                            starter_ids
                        ),
                        bench_gk_id=(
                            bench_gk
                        ),
                        bench_outfield_ids=(
                            order
                        ),
                        positions=(
                            positions
                        ),
                        expected_points=(
                            expected_points
                        ),
                        p_appearance=(
                            p_appearance
                        ),
                    )
                )


                score = result_total(
                    result
                )


                if (
                    best is None
                    or score
                    > best[0]
                ):

                    best = (
                        score,
                        result,
                    )


    if best is None:

        raise RuntimeError(
            "No legal autosub lineup"
        )


    return best[1]


def score_one_gameweek(
    *,
    run,
    squad_ids,
    gameweek,
):

    players_by_id = (
        run[
            "players_by_id"
        ]
    )

    positions = {
        player_id: (
            players_by_id[
                player_id
            ].position
        )
        for player_id
        in squad_ids
    }


    expected_points = {
        player_id: points_for(
            run[
                "projections_by_id"
            ][player_id],
            gameweek,
        )
        for player_id
        in squad_ids
    }


    p_appearance = {}


    for player_id in squad_ids:

        key = (
            player_id,
            gameweek,
        )

        if (
            key
            not in run[
                "p_appearance"
            ]
        ):

            raise RuntimeError(
                "Missing p_appearance "
                f"for {player_id} "
                f"GW{gameweek}"
            )

        p_appearance[
            player_id
        ] = run[
            "p_appearance"
        ][key]


    result = (
        call_optimize_autosub(
            squad_ids=(
                squad_ids
            ),
            gameweek=gameweek,
            positions=positions,
            expected_points=(
                expected_points
            ),
            p_appearance=(
                p_appearance
            ),
        )
    )


    if result is None:

        result = (
            exhaustive_autosub(
                squad_ids=(
                    squad_ids
                ),
                gameweek=gameweek,
                positions=positions,
                expected_points=(
                    expected_points
                ),
                p_appearance=(
                    p_appearance
                ),
            )
        )


    return result_total(
        result
    )


def score_candidate(
    run,
    squad_ids,
):

    by_gw = {}

    total = 0.0


    for index, gameweek in (
        enumerate(
            GAMEWEEKS
        )
    ):

        score = (
            score_one_gameweek(
                run=run,
                squad_ids=(
                    squad_ids
                ),
                gameweek=(
                    gameweek
                ),
            )
        )


        by_gw[
            gameweek
        ] = score


        total += (
            WEIGHTS[index]
            * score
        )


    return (
        total,
        by_gw,
    )


# ============================================================
# CROSS-SCORE MATRIX
# ============================================================


print()
print(
    "=========================================="
)
print(
    "CROSS-SCORING ALL UNIQUE SQUADS"
)
print(
    "bench-aware | GW4-GW9"
)
print(
    "=========================================="
)


results = []


for index, candidate in enumerate(
    candidates,
    start=1,
):

    label = (
        "CAND_"
        + str(index)
    )

    candidate[
        "candidate_id"
    ] = label


    scores = []

    per_run = {}


    for run in runs:

        score, by_gw = (
            score_candidate(
                run,
                candidate[
                    "ids"
                ],
            )
        )

        scores.append(
            score
        )

        per_run[
            run["seed"]
        ] = {
            "score": score,
            "gameweeks": by_gw,
        }


    mean_score = (
        statistics.mean(
            scores
        )
    )

    worst_score = min(
        scores
    )

    best_score = max(
        scores
    )

    spread = (
        best_score
        - worst_score
    )


    results.append(
        {
            "candidate": candidate,
            "scores": scores,
            "per_run": per_run,
            "mean": mean_score,
            "worst": worst_score,
            "spread": spread,
        }
    )


# Regret relative to best candidate
# inside each simulation world.

world_best = []


for world_index in range(
    len(runs)
):

    world_best.append(
        max(
            row[
                "scores"
            ][world_index]
            for row in results
        )
    )


for row in results:

    regrets = [
        world_best[index]
        - row["scores"][index]
        for index
        in range(
            len(runs)
        )
    ]

    row[
        "max_regret"
    ] = max(
        regrets
    )

    row[
        "mean_regret"
    ] = statistics.mean(
        regrets
    )


print()

header = (
    "CANDIDATE       "
    "RUN42    "
    "RUN202627 "
    "RUN606   "
    "RUN91991 "
    "MEAN     "
    "WORST    "
    "SPREAD   "
    "MAX_REG"
)

print(header)


for row in sorted(
    results,
    key=lambda item: (
        item["worst"],
        item["mean"],
    ),
    reverse=True,
):

    candidate = (
        row["candidate"]
    )

    sources = (
        "+"
        .join(
            candidate[
                "sources"
            ]
        )
    )


    print(
        f"{candidate['candidate_id']:<8} "
        f"{sources[:18]:<18} "
        f"{row['scores'][0]:>7.2f} "
        f"{row['scores'][1]:>9.2f} "
        f"{row['scores'][2]:>7.2f} "
        f"{row['scores'][3]:>8.2f} "
        f"{row['mean']:>7.2f} "
        f"{row['worst']:>7.2f} "
        f"{row['spread']:>7.2f} "
        f"{row['max_regret']:>7.2f}"
    )


# ============================================================
# WINNERS
# ============================================================


mean_winner = max(
    results,
    key=lambda row: (
        row["mean"]
    ),
)

worst_winner = max(
    results,
    key=lambda row: (
        row["worst"],
        row["mean"],
    ),
)

regret_winner = min(
    results,
    key=lambda row: (
        row["max_regret"],
        -row["mean"],
    ),
)


print()
print(
    "=========================================="
)
print(
    "ROBUST WINNERS"
)
print(
    "=========================================="
)

print(
    "BEST MEAN:       ",
    mean_winner[
        "candidate"
    ][
        "candidate_id"
    ],
    f"{mean_winner['mean']:.2f}",
)

print(
    "BEST WORST-CASE: ",
    worst_winner[
        "candidate"
    ][
        "candidate_id"
    ],
    f"{worst_winner['worst']:.2f}",
)

print(
    "MINIMAX REGRET:  ",
    regret_winner[
        "candidate"
    ][
        "candidate_id"
    ],
    f"{regret_winner['max_regret']:.2f}",
)


# Primary robust choice:
# maximise worst case,
# use mean as tie-break.

winner = worst_winner

winner_ids = (
    winner[
        "candidate"
    ][
        "ids"
    ]
)


print()
print(
    "=========================================="
)
print(
    "PRIMARY ROBUST WC SQUAD"
)
print(
    "=========================================="
)


for position in (
    "GK",
    "DEF",
    "MID",
    "FWD",
):

    names = sorted(
        (
            reference[
                "players_by_id"
            ][player_id].name,
            reference[
                "players_by_id"
            ][player_id].price_m,
        )
        for player_id
        in winner_ids
        if (
            reference[
                "players_by_id"
            ][player_id].position
            == position
        )
    )


    rendered = ", ".join(
        f"{name} "
        f"(£{price:.1f})"
        for name, price
        in names
    )


    print(
        f"{position}: "
        f"{rendered}"
    )


print(
    "remaining budget:",
    f"£{winner['candidate']['remaining_budget']/10:.1f}m",
)


# ============================================================
# MIDFIELD ALTERNATIVES
# ============================================================


print()
print(
    "=========================================="
)
print(
    "MIDFIELD CONSENSUS / ALTERNATIVES"
)
print(
    "=========================================="
)


mid_rows = []


for player_id, count in (
    selection_count.items()
):

    player = (
        reference[
            "players_by_id"
        ][player_id]
    )

    if (
        player.position
        != "MID"
    ):
        continue


    six_world_values = [
        sum(
            WEIGHTS[index]
            * points_for(
                run[
                    "projections_by_id"
                ][player_id],
                gameweek,
            )
            for index, gameweek
            in enumerate(
                GAMEWEEKS
            )
        )
        for run in runs
    ]


    mid_rows.append(
        {
            "name": player.name,
            "price": player.price_m,
            "selected": count,
            "mean6": (
                statistics.mean(
                    six_world_values
                )
            ),
            "worst6": min(
                six_world_values
            ),
            "spread6": (
                max(
                    six_world_values
                )
                - min(
                    six_world_values
                )
            ),
        }
    )


mid_rows.sort(
    key=lambda row: (
        -row["selected"],
        -row["mean6"],
    )
)


print(
    "NAME                   "
    "SEL   PRICE   "
    "MEAN6   WORST6  SPREAD"
)


for row in mid_rows:

    print(
        f"{row['name']:<22} "
        f"{row['selected']}/6   "
        f"£{row['price']:<5.1f} "
        f"{row['mean6']:>6.2f} "
        f"{row['worst6']:>7.2f} "
        f"{row['spread6']:>7.2f}"
    )


# ============================================================
# SAVE
# ============================================================


payload = {
    "runs": [
        {
            "seed": run["seed"],
            "run_id": run["run_id"],
        }
        for run in runs
    ],
    "source_candidates": [
        {
            "label": row["label"],
            "player_ids": sorted(
                row["ids"]
            ),
            "remaining_budget_tenths": (
                row[
                    "remaining_budget"
                ]
            ),
            "optimizer_xi_ev": (
                row[
                    "optimizer_xi_ev"
                ]
            ),
        }
        for row
        in source_candidates
    ],
    "cross_scores": [
        {
            "candidate_id": (
                row[
                    "candidate"
                ][
                    "candidate_id"
                ]
            ),
            "sources": (
                row[
                    "candidate"
                ][
                    "sources"
                ]
            ),
            "player_ids": sorted(
                row[
                    "candidate"
                ][
                    "ids"
                ]
            ),
            "scores": (
                row["scores"]
            ),
            "mean": row["mean"],
            "worst": row["worst"],
            "spread": row["spread"],
            "max_regret": (
                row[
                    "max_regret"
                ]
            ),
            "mean_regret": (
                row[
                    "mean_regret"
                ]
            ),
        }
        for row
        in results
    ],
    "winner": {
        "candidate_id": (
            winner[
                "candidate"
            ][
                "candidate_id"
            ]
        ),
        "sources": (
            winner[
                "candidate"
            ][
                "sources"
            ]
        ),
        "player_ids": sorted(
            winner_ids
        ),
        "mean": (
            winner["mean"]
        ),
        "worst": (
            winner["worst"]
        ),
        "spread": (
            winner["spread"]
        ),
        "max_regret": (
            winner[
                "max_regret"
            ]
        ),
        "remaining_budget_tenths": (
            winner[
                "candidate"
            ][
                "remaining_budget"
            ]
        ),
    },
    "midfield_consensus": (
        mid_rows
    ),
}


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


print()
print(
    "saved:",
    OUTPUT,
)

print()
print(
    "=== FINAL WC ROBUST OPTIMIZER COMPLETE ==="
)
