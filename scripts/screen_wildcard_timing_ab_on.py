from __future__ import annotations

import json
import math
import unicodedata

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fpl_engine.decision.projection_adapter import (
    HorizonValue,
    PlayerDecisionProjection,
    adapt_player_projections,
)

from fpl_engine.decision.value import (
    PlayerValue,
    build_player_values,
)

from fpl_engine.decision.transfers import (
    SquadState,
    build_team_counts,
)

from fpl_engine.decision.rolling_transfers import (
    evaluate_squad_with_captaincy,
    optimize_rolling_free_transfers,
)

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)

from fpl_engine.decision.appearance import (
    build_gameweek_appearance,
)


_CAPTAINCY_APPEARANCE_CACHE = {}


def _captaincy_artifact_rows(
    payload,
):

    if isinstance(
        payload,
        list,
    ):
        return payload

    if isinstance(
        payload,
        dict,
    ):

        for key in (
            "rows",
            "data",
            "records",
            "projections",
            "minutes",
        ):

            value = payload.get(
                key
            )

            if isinstance(
                value,
                list,
            ):
                return value

    raise RuntimeError(
        "cannot resolve decision "
        "artifact rows"
    )


def _captaincy_appearance_for_run(
    run_dir,
):

    run_dir = Path(
        run_dir
    )

    cache_key = str(
        run_dir.resolve()
    )


    cached = (
        _CAPTAINCY_APPEARANCE_CACHE
        .get(
            cache_key
        )
    )

    if cached is not None:
        return cached


    projection_payload = (
        json.loads(
            (
                run_dir
                / "player_projections.json"
            ).read_text(
                encoding="utf-8-sig"
            )
        )
    )


    minutes_payload = (
        json.loads(
            (
                run_dir
                / "minutes.json"
            ).read_text(
                encoding="utf-8-sig"
            )
        )
    )


    appearance = (
        build_gameweek_appearance(
            projection_rows=(
                _captaincy_artifact_rows(
                    projection_payload
                )
            ),
            minutes_rows=(
                _captaincy_artifact_rows(
                    minutes_payload
                )
            ),
        )
    )


    _CAPTAINCY_APPEARANCE_CACHE[
        cache_key
    ] = appearance


    return appearance



# ============================================================
# DECISION-006B
#
# Wildcard timing screen + selected full rollouts.
#
# Primary policy:
# - captaincy disabled
# - Haaland retained on Wildcard
# - no hits, free transfers only
# - current prices frozen
# - saved FTs preserved through Wildcard
#
# Projection data:
# GW4-GW24
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
    / "decision006_21gw_runs.txt"
)

SQUAD_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

OUTPUT_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "wildcard_timing_results.json"
)


FIRST_GW = 4
LAST_WC_GW = 19
LAST_EVAL_GW = 24

MAX_FT = 5
INITIAL_FT_FALLBACK = 3

HORIZON_WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)


# Long-range strategic discount.
#
# GW4  = 1.00
# GW5  = 0.95
# ...
# GW19 = 0.25
#
# GW20-GW24 remain at 0.25 because they are only
# included so late WC windows get a complete 6GW
# post-Wildcard evaluation.
def strategic_weight(gameweek: int) -> float:
    return max(
        0.25,
        1.0
        - 0.05
        * (
            gameweek
            - FIRST_GW
        ),
    )


# ============================================================
# TYPES
# ============================================================


@dataclass
class RunData:
    name: str
    run_dir: Path
    player_rows: list[dict]
    metadata_by_id: dict[str, dict]
    projections: tuple[PlayerDecisionProjection, ...]
    projections_by_id: dict[str, PlayerDecisionProjection]
    context_cache: dict


@dataclass
class BaselinePath:
    pre_state_by_gw: dict[int, SquadState]
    pre_ft_by_gw: dict[int, int]
    prefix_raw_by_gw: dict[int, float]
    prefix_discounted_by_gw: dict[int, float]
    gw_scores: dict[int, float]
    transfer_counts: dict[int, int]
    final_raw: float
    final_discounted: float


# ============================================================
# HELPERS
# ============================================================


def normalize_name(value: object) -> str:

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


def price_to_tenths(value: object) -> int | None:

    if value is None:
        return None

    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if number < 20:
        return int(
            round(
                number * 10
            )
        )

    return int(
        round(number)
    )


def load_run_ids() -> list[str]:

    lines = RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    output = []

    for line in lines:

        if "run=" not in line:
            continue

        output.append(
            line.split(
                "run=",
                1,
            )[1].strip()
        )

    if len(output) != 2:
        raise RuntimeError(
            "Expected exactly two "
            "DECISION-006 run IDs."
        )

    return output


def load_run(
    run_id: str,
) -> RunData:

    run_dir = (
        RUN_ROOT
        / run_id
    )

    player_rows = json.loads(
        (
            run_dir
            / "current_players.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    raw_projections = json.loads(
        (
            run_dir
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

    metadata_by_id = {
        str(
            row["player_id"]
        ): row
        for row in player_rows
    }

    return RunData(
        name=run_id,
        run_dir=run_dir,
        player_rows=player_rows,
        metadata_by_id=(
            metadata_by_id
        ),
        projections=projections,
        projections_by_id={
            row.player_id: row
            for row in projections
        },
        context_cache={},
    )


def horizon_value(
    projection: PlayerDecisionProjection,
    gameweeks,
    count: int,
) -> HorizonValue:

    rows = tuple(
        gameweeks[:count]
    )

    if not rows:
        return HorizonValue(
            player_id=projection.player_id,
            first_gameweek=(
                projection.current_gameweek
            ),
            last_gameweek=(
                projection.current_gameweek
            ),
            raw_expected_points=0.0,
            weighted_expected_points=0.0,
            gameweeks=0,
        )

    raw = sum(
        row.expected_points
        for row in rows
    )

    weighted = sum(
        row.expected_points
        * HORIZON_WEIGHTS[index]
        for index, row
        in enumerate(rows)
    )

    return HorizonValue(
        player_id=projection.player_id,
        first_gameweek=(
            rows[0].gameweek
        ),
        last_gameweek=(
            rows[-1].gameweek
        ),
        raw_expected_points=raw,
        weighted_expected_points=weighted,
        gameweeks=len(rows),
    )


def rebase_projection(
    projection: PlayerDecisionProjection,
    first_gameweek: int,
) -> PlayerDecisionProjection:

    rows = tuple(
        row
        for row
        in projection.gameweeks
        if (
            first_gameweek
            <= row.gameweek
            <= first_gameweek + 5
        )
    )

    return PlayerDecisionProjection(
        player_id=projection.player_id,
        current_gameweek=(
            first_gameweek
        ),
        horizon_3=horizon_value(
            projection,
            rows,
            3,
        ),
        horizon_6=horizon_value(
            projection,
            rows,
            6,
        ),

        # Minutes-by-GW are not exposed by the
        # decision projection adapter.
        #
        # Rolling MILP uses the per-GW points
        # and squad metadata, not these totals.
        expected_minutes_next_3=0.0,
        expected_minutes_next_6=0.0,

        projection_confidence=(
            projection
            .projection_confidence
        ),
        projection_uncertainty=(
            projection
            .projection_uncertainty
        ),
        gameweeks=rows,
    )


def context_for_gw(
    data: RunData,
    gameweek: int,
):

    if (
        gameweek
        in data.context_cache
    ):
        return (
            data.context_cache[
                gameweek
            ]
        )

    projections = tuple(
        rebase_projection(
            projection,
            gameweek,
        )
        for projection
        in data.projections
    )

    projections_by_id = {
        row.player_id: row
        for row in projections
    }

    players = (
        build_player_values(
            projections,
            data.metadata_by_id,
        )
    )

    players_by_id = {
        row.player_id: row
        for row in players
    }

    value = (
        projections_by_id,
        players,
        players_by_id,
    )

    data.context_cache[
        gameweek
    ] = value

    return value


def gw_points(
    projections_by_id:
        Mapping[
            str,
            PlayerDecisionProjection,
        ],
    player_ids,
    gameweek: int,
) -> float:

    total = 0.0

    for player_id in player_ids:

        projection = (
            projections_by_id[
                player_id
            ]
        )

        for row in (
            projection.gameweeks
        ):

            if (
                row.gameweek
                == gameweek
            ):
                total += (
                    row.expected_points
                )
                break

    return total


def make_next_state(
    *,
    previous_state: SquadState,
    new_squad,
    bank_tenths: int,
    players_by_id:
        Mapping[str, PlayerValue],
) -> SquadState:

    new_squad = frozenset(
        new_squad
    )

    selling = {}

    for player_id in new_squad:

        if (
            player_id
            in previous_state
            .selling_prices_tenths
        ):

            selling[player_id] = int(
                previous_state
                .selling_prices_tenths[
                    player_id
                ]
            )

        else:

            selling[player_id] = int(
                players_by_id[
                    player_id
                ].price_tenths
            )

    return SquadState(
        player_ids=new_squad,
        bank_tenths=int(
            bank_tenths
        ),
        selling_prices_tenths=(
            selling
        ),
        team_counts=build_team_counts(
            new_squad,
            players_by_id,
        ),
    )


# ============================================================
# INITIAL SQUAD
# ============================================================


KNOWN_SELLING = {
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


def extract_initial_state(
    data: RunData,
):

    raw = json.loads(
        SQUAD_PATH.read_text(
            encoding="utf-8"
        )
    )

    (
        projections_by_id,
        players,
        players_by_id,
    ) = context_for_gw(
        data,
        FIRST_GW,
    )

    by_normalized_name = {}

    for player in players:

        by_normalized_name[
            normalize_name(
                player.name
            )
        ] = player.player_id

    candidate = (
        raw.get(
            "state",
            raw,
        )
        if isinstance(
            raw,
            dict,
        )
        else raw
    )

    player_ids = set()
    selling = {}


    # --------------------------------------------
    # Direct canonical representation
    # --------------------------------------------

    if isinstance(
        candidate,
        dict,
    ):

        direct_ids = (
            candidate.get(
                "player_ids"
            )
        )

        if direct_ids:

            player_ids.update(
                str(value)
                for value
                in direct_ids
            )

        direct_selling = (
            candidate.get(
                "selling_prices_tenths"
            )
        )

        if isinstance(
            direct_selling,
            dict,
        ):

            for key, value in (
                direct_selling.items()
            ):

                selling[
                    str(key)
                ] = int(value)


    # --------------------------------------------
    # Player-list representation
    # --------------------------------------------

    items = None

    if isinstance(
        candidate,
        dict,
    ):

        for key in (
            "players",
            "squad",
            "picks",
        ):

            if isinstance(
                candidate.get(key),
                list,
            ):
                items = (
                    candidate[key]
                )
                break

    elif isinstance(
        candidate,
        list,
    ):
        items = candidate


    if items:

        for item in items:

            if isinstance(
                item,
                str,
            ):

                if (
                    item
                    in players_by_id
                ):
                    player_ids.add(
                        item
                    )
                    continue

                player_id = (
                    by_normalized_name
                    .get(
                        normalize_name(
                            item
                        )
                    )
                )

                if player_id:
                    player_ids.add(
                        player_id
                    )

                continue


            if not isinstance(
                item,
                dict,
            ):
                continue


            player_id = None

            for key in (
                "player_id",
                "canonical_player_id",
            ):

                value = (
                    item.get(key)
                )

                if (
                    value
                    and str(value)
                    in players_by_id
                ):

                    player_id = str(
                        value
                    )
                    break


            if player_id is None:

                for key in (
                    "display_name",
                    "name",
                    "web_name",
                ):

                    value = (
                        item.get(key)
                    )

                    if not value:
                        continue

                    player_id = (
                        by_normalized_name
                        .get(
                            normalize_name(
                                value
                            )
                        )
                    )

                    if player_id:
                        break


            if player_id is None:
                continue


            player_ids.add(
                player_id
            )


            for key in (
                "selling_price_tenths",
                "selling_price",
                "sell_price",
                "current_selling_price",
            ):

                if key not in item:
                    continue

                price = price_to_tenths(
                    item[key]
                )

                if price is not None:

                    selling[
                        player_id
                    ] = price

                    break


    # --------------------------------------------
    # Fallback by known current squad names
    # --------------------------------------------

    if len(player_ids) != 15:

        player_ids = set()

        for name in (
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
        ):

            normalized = (
                normalize_name(name)
            )

            player_id = (
                by_normalized_name.get(
                    normalized
                )
            )

            if player_id is None:
                raise RuntimeError(
                    "Cannot resolve current "
                    f"squad player: {name}"
                )

            player_ids.add(
                player_id
            )


    if len(player_ids) != 15:

        raise RuntimeError(
            "Initial squad does not "
            f"contain 15 players: "
            f"{len(player_ids)}"
        )


    # --------------------------------------------
    # Fill selling values from known real values
    # --------------------------------------------

    for player_id in player_ids:

        if player_id in selling:
            continue

        name = (
            players_by_id[
                player_id
            ].name
        )

        normalized = (
            normalize_name(name)
        )

        if (
            normalized
            in KNOWN_SELLING
        ):

            selling[
                player_id
            ] = (
                KNOWN_SELLING[
                    normalized
                ]
            )


    missing = (
        player_ids
        - set(selling)
    )

    if missing:

        names = [
            players_by_id[
                player_id
            ].name
            for player_id
            in missing
        ]

        raise RuntimeError(
            "Missing actual selling "
            "prices for: "
            + ", ".join(
                sorted(names)
            )
        )


    bank = 0

    if isinstance(
        candidate,
        dict,
    ):

        if (
            "bank_tenths"
            in candidate
        ):

            bank = int(
                candidate[
                    "bank_tenths"
                ]
            )

        elif (
            "bank"
            in candidate
        ):

            parsed = (
                price_to_tenths(
                    candidate["bank"]
                )
            )

            bank = (
                0
                if parsed is None
                else parsed
            )


    free_transfers = (
        INITIAL_FT_FALLBACK
    )

    if isinstance(
        candidate,
        dict,
    ):

        for key in (
            "free_transfers",
            "current_free_transfers",
            "ft",
        ):

            if key in candidate:

                free_transfers = int(
                    candidate[key]
                )

                break


    state = SquadState(
        player_ids=frozenset(
            player_ids
        ),
        bank_tenths=bank,
        selling_prices_tenths=(
            selling
        ),
        team_counts=(
            build_team_counts(
                player_ids,
                players_by_id,
            )
        ),
    )

    return (
        state,
        free_transfers,
    )


# ============================================================
# NORMAL WEEK POLICY
# ============================================================


def choose_normal_action(
    *,
    data: RunData,
    state: SquadState,
    free_transfers: int,
    gameweek: int,
):

    (
        projections_by_id,
        players,
        players_by_id,
    ) = context_for_gw(
        data,
        gameweek,
    )

    remaining_gameweeks = (
        LAST_EVAL_GW
        - gameweek
        + 1
    )

    # rolling_transfers currently supports
    # only 3GW or 6GW optimization horizons.
    #
    # Near the end of the evaluation window,
    # missing future GWs simply contribute
    # zero EV.
    horizon = (
        6
        if remaining_gameweeks >= 4
        else 3
    )

    candidates = []

    errors = []


    for transfer_count in range(
        0,
        free_transfers + 1,
    ):

        try:

            plan = (
                optimize_rolling_free_transfers(
                    players=players,
                    projections_by_id=(
                        projections_by_id
                    ),
                    state=state,
                    horizon=horizon,
                    transfers_now=(
                        transfer_count
                    ),
                    current_free_transfers=(
                        free_transfers
                    ),
                    max_free_transfers=(
                        MAX_FT
                    ),
                    captaincy_weight=1.0,
                    appearance_by_player_gameweek=_captaincy_appearance_for_run(data.run_dir),
                )
            )

        except Exception as exc:

            errors.append(
                (
                    transfer_count,
                    repr(exc),
                )
            )

            continue


        if plan is None:
            continue


        candidates.append(
            (
                plan.final_weighted_xi_ev,
                -transfer_count,
                transfer_count,
                plan,
            )
        )


    if not candidates:

        raise RuntimeError(
            "No legal normal-transfer "
            f"plan in GW{gameweek}. "
            f"errors={errors[:3]}"
        )


    candidates.sort(
        reverse=True,
        key=lambda item: (
            item[0],
            item[1],
        ),
    )


    (
        _,
        _,
        transfer_count,
        plan,
    ) = candidates[0]


    starters = dict(
        plan.starting_xi_by_gameweek
    ).get(
        gameweek
    )

    if starters is None:

        raise RuntimeError(
            "Missing starting XI "
            f"for GW{gameweek}"
        )


    score = gw_points(
        projections_by_id,
        starters,
        gameweek,
    )


    new_state = make_next_state(
        previous_state=state,
        new_squad=(
            plan.squad_now_player_ids
        ),
        bank_tenths=(
            plan.bank_after_now_tenths
        ),
        players_by_id=(
            players_by_id
        ),
    )


    next_ft = min(
        MAX_FT,
        (
            free_transfers
            - transfer_count
            + 1
        ),
    )


    return {
        "score": score,
        "state": new_state,
        "next_ft": next_ft,
        "transfers": transfer_count,
        "plan": plan,
    }


# ============================================================
# BASELINE NO-WC PATH
# ============================================================


def build_baseline(
    data: RunData,
) -> BaselinePath:

    (
        state,
        free_transfers,
    ) = extract_initial_state(
        data
    )

    pre_state_by_gw = {}
    pre_ft_by_gw = {}
    prefix_raw_by_gw = {}
    prefix_discounted_by_gw = {}
    gw_scores = {}
    transfer_counts = {}

    raw_total = 0.0
    discounted_total = 0.0


    print()
    print(
        f"[{data.name}] "
        "building NO_WC baseline"
    )


    for gameweek in range(
        FIRST_GW,
        LAST_EVAL_GW + 1,
    ):

        pre_state_by_gw[
            gameweek
        ] = state

        pre_ft_by_gw[
            gameweek
        ] = free_transfers

        prefix_raw_by_gw[
            gameweek
        ] = raw_total

        prefix_discounted_by_gw[
            gameweek
        ] = discounted_total


        action = (
            choose_normal_action(
                data=data,
                state=state,
                free_transfers=(
                    free_transfers
                ),
                gameweek=gameweek,
            )
        )


        score = float(
            action["score"]
        )

        gw_scores[
            gameweek
        ] = score

        transfer_counts[
            gameweek
        ] = int(
            action["transfers"]
        )


        raw_total += score

        discounted_total += (
            score
            * strategic_weight(
                gameweek
            )
        )


        state = action[
            "state"
        ]

        free_transfers = int(
            action["next_ft"]
        )


        print(
            f"  GW{gameweek}: "
            f"EV={score:.2f} "
            f"FTused="
            f"{transfer_counts[gameweek]} "
            f"FTnext="
            f"{free_transfers}"
        )


    return BaselinePath(
        pre_state_by_gw=(
            pre_state_by_gw
        ),
        pre_ft_by_gw=(
            pre_ft_by_gw
        ),
        prefix_raw_by_gw=(
            prefix_raw_by_gw
        ),
        prefix_discounted_by_gw=(
            prefix_discounted_by_gw
        ),
        gw_scores=gw_scores,
        transfer_counts=(
            transfer_counts
        ),
        final_raw=raw_total,
        final_discounted=(
            discounted_total
        ),
    )


# ============================================================
# WILDCARD
# ============================================================


def find_haaland_id(
    data: RunData,
) -> str:

    (
        _,
        _,
        players_by_id,
    ) = context_for_gw(
        data,
        FIRST_GW,
    )

    matches = [
        player_id
        for player_id, player
        in players_by_id.items()
        if normalize_name(
            player.name
        ) == "haaland"
    ]

    if len(matches) != 1:

        raise RuntimeError(
            "Could not uniquely "
            "resolve Haaland."
        )

    return matches[0]


def wildcard_plan(
    *,
    data: RunData,
    state: SquadState,
    gameweek: int,
    require_haaland: bool,
):

    (
        projections_by_id,
        _,
        _,
    ) = context_for_gw(
        data,
        gameweek,
    )

    horizon = min(
        6,
        LAST_EVAL_GW
        - gameweek
        + 1,
    )

    required = ()

    if require_haaland:

        required = (
            find_haaland_id(
                data
            ),
        )


    return optimize_unlimited_squad(
        player_rows=(
            data.player_rows
        ),
        projections_by_id=(
            projections_by_id
        ),
        current_player_ids=(
            state.player_ids
        ),
        selling_prices_tenths=(
            state
            .selling_prices_tenths
        ),
        bank_tenths=(
            state.bank_tenths
        ),
        first_gameweek=(
            gameweek
        ),
        horizon=horizon,
        weights=(
            HORIZON_WEIGHTS[
                :horizon
            ]
        ),
        required_player_ids=(
            required
        ),
        captaincy_weight=1.0,
        appearance_by_player_gameweek=_captaincy_appearance_for_run(data.run_dir),
    )


# ============================================================
# STAGE 1:
# LOCAL 6GW WC WINDOW SCREEN
# ============================================================


def screen_wildcards(
    *,
    data: RunData,
    baseline: BaselinePath,
):

    output = {}

    print()
    print(
        f"[{data.name}] "
        "Wildcard local-window screen"
    )


    for gameweek in range(
        FIRST_GW,
        LAST_WC_GW + 1,
    ):

        state = (
            baseline
            .pre_state_by_gw[
                gameweek
            ]
        )

        (
            projections_by_id,
            players,
            players_by_id,
        ) = context_for_gw(
            data,
            gameweek,
        )


        static_eval = (
            evaluate_squad_with_captaincy(
                squad_player_ids=(
                    state.player_ids
                ),
                players_by_id=(
                    players_by_id
                ),
                projections_by_id=(
                    projections_by_id
                ),
                horizon=6,
            )
        )


        raw_wc = wildcard_plan(
            data=data,
            state=state,
            gameweek=gameweek,
            require_haaland=False,
        )


        safe_wc = wildcard_plan(
            data=data,
            state=state,
            gameweek=gameweek,
            require_haaland=True,
        )


        raw_gain = (
            raw_wc.weighted_xi_ev
            - static_eval.weighted_xi_ev
        )

        safe_gain = (
            safe_wc.weighted_xi_ev
            - static_eval.weighted_xi_ev
        )


        output[
            gameweek
        ] = {
            "static_base": (
                static_eval
                .weighted_xi_ev
            ),
            "wc_raw": (
                raw_wc
                .weighted_xi_ev
            ),
            "wc_haaland": (
                safe_wc
                .weighted_xi_ev
            ),
            "gain_raw": raw_gain,
            "gain_haaland": (
                safe_gain
            ),
        }


        print(
            f"  GW{gameweek}: "
            f"raw={raw_gain:+.2f} "
            f"Haaland={safe_gain:+.2f}"
        )


    return output


# ============================================================
# STAGE 2:
# FULL ROLLOUT FROM NOW TO GW24
# ============================================================


def rollout_wildcard(
    *,
    data: RunData,
    baseline: BaselinePath,
    wildcard_gameweek: int,
):

    state = (
        baseline
        .pre_state_by_gw[
            wildcard_gameweek
        ]
    )

    free_transfers = (
        baseline
        .pre_ft_by_gw[
            wildcard_gameweek
        ]
    )

    raw_total = (
        baseline
        .prefix_raw_by_gw[
            wildcard_gameweek
        ]
    )

    discounted_total = (
        baseline
        .prefix_discounted_by_gw[
            wildcard_gameweek
        ]
    )


    (
        projections_by_id,
        players,
        players_by_id,
    ) = context_for_gw(
        data,
        wildcard_gameweek,
    )


    wc = wildcard_plan(
        data=data,
        state=state,
        gameweek=(
            wildcard_gameweek
        ),
        require_haaland=True,
    )


    starters = dict(
        wc.starting_xi_by_gameweek
    ).get(
        wildcard_gameweek
    )

    if starters is None:

        raise RuntimeError(
            "Wildcard plan has no "
            "starting XI for "
            f"GW{wildcard_gameweek}"
        )


    score = gw_points(
        projections_by_id,
        starters,
        wildcard_gameweek,
    )


    raw_total += score

    discounted_total += (
        score
        * strategic_weight(
            wildcard_gameweek
        )
    )


    new_state = make_next_state(
        previous_state=state,
        new_squad=wc.player_ids,
        bank_tenths=(
            wc.remaining_budget_tenths
        ),
        players_by_id=(
            players_by_id
        ),
    )


    old_ids = set(
        state.player_ids
    )

    new_ids = set(
        wc.player_ids
    )

    incoming = sorted(
        players_by_id[
            player_id
        ].name
        for player_id
        in (
            new_ids
            - old_ids
        )
    )

    outgoing = sorted(
        players_by_id[
            player_id
        ].name
        for player_id
        in (
            old_ids
            - new_ids
        )
    )


    # Official FPL rule:
    # saved FTs are retained after WC.
    #
    # No +1 is added for the WC Gameweek.
    state = new_state


    print()
    print(
        f"[{data.name}] "
        f"FULL WC GW{wildcard_gameweek}"
    )

    print(
        f"  WC GW EV={score:.2f} "
        f"FT retained="
        f"{free_transfers}"
    )


    for gameweek in range(
        wildcard_gameweek + 1,
        LAST_EVAL_GW + 1,
    ):

        action = (
            choose_normal_action(
                data=data,
                state=state,
                free_transfers=(
                    free_transfers
                ),
                gameweek=gameweek,
            )
        )


        week_score = float(
            action["score"]
        )

        raw_total += (
            week_score
        )

        discounted_total += (
            week_score
            * strategic_weight(
                gameweek
            )
        )


        state = action[
            "state"
        ]

        free_transfers = int(
            action["next_ft"]
        )


        print(
            f"  GW{gameweek}: "
            f"EV={week_score:.2f} "
            f"FTused="
            f"{action['transfers']} "
            f"FTnext="
            f"{free_transfers}"
        )


    return {
        "wildcard_gameweek": (
            wildcard_gameweek
        ),
        "raw_total": raw_total,
        "discounted_total": (
            discounted_total
        ),
        "incoming": incoming,
        "outgoing": outgoing,
        "remaining_budget_tenths": (
            wc.remaining_budget_tenths
        ),
    }


# ============================================================
# RUN
# ============================================================


print()
print(
    "========================================"
)
print(
    "DECISION-006B WILDCARD TIMING"
)
print(
    "========================================"
)
print(
    "Primary model: Haaland-safe, "
    "captaincy OFF"
)
print(
    "Prices: frozen at current values"
)
print(
    "Evaluation: GW4-GW24"
)
print(
    "Wildcard candidates: GW4-GW19"
)
print()


run_ids = load_run_ids()

runs = [
    load_run(
        run_id
    )
    for run_id
    in run_ids
]


baselines = {}
screens = {}


for data in runs:

    baseline = (
        build_baseline(
            data
        )
    )

    baselines[
        data.name
    ] = baseline

    screens[
        data.name
    ] = (
        screen_wildcards(
            data=data,
            baseline=baseline,
        )
    )


# ============================================================
# STAGE 1 CONSENSUS
# ============================================================


print()
print(
    "========================================"
)
print(
    "STAGE 1 CONSENSUS - LOCAL 6GW WC VALUE"
)
print(
    "========================================"
)

print(
    "GW   RUN1     RUN2     MEAN     WORST"
)


screen_consensus = {}


for gameweek in range(
    FIRST_GW,
    LAST_WC_GW + 1,
):

    values = [
        screens[
            data.name
        ][
            gameweek
        ][
            "gain_haaland"
        ]
        for data in runs
    ]

    mean_value = (
        sum(values)
        / len(values)
    )

    worst_value = min(
        values
    )

    screen_consensus[
        gameweek
    ] = {
        "values": values,
        "mean": mean_value,
        "worst": worst_value,
    }

    print(
        f"{gameweek:>2}  "
        f"{values[0]:>+7.2f}  "
        f"{values[1]:>+7.2f}  "
        f"{mean_value:>+7.2f}  "
        f"{worst_value:>+7.2f}"
    )


later_ranked = sorted(
    range(
        FIRST_GW + 1,
        LAST_WC_GW + 1,
    ),
    key=lambda gw: (
        screen_consensus[
            gw
        ]["mean"],
        screen_consensus[
            gw
        ]["worst"],
    ),
    reverse=True,
)


selected_timings = [
    FIRST_GW,
    *later_ranked[:3],
]


print()
print(
    "Selected for full rollout:",
    ", ".join(
        f"GW{gw}"
        for gw
        in selected_timings
    ),
)


# ============================================================
# STAGE 2 FULL ROLLOUT
# ============================================================


full_results = {}


for data in runs:

    baseline = (
        baselines[
            data.name
        ]
    )

    full_results[
        data.name
    ] = {
        "NO_WC": {
            "raw_total": (
                baseline.final_raw
            ),
            "discounted_total": (
                baseline
                .final_discounted
            ),
        }
    }


    for gameweek in (
        selected_timings
    ):

        full_results[
            data.name
        ][
            f"WC_GW{gameweek}"
        ] = rollout_wildcard(
            data=data,
            baseline=baseline,
            wildcard_gameweek=(
                gameweek
            ),
        )


# ============================================================
# FULL CONSENSUS
# ============================================================


print()
print(
    "========================================"
)
print(
    "STAGE 2 FULL ROLLOUT CONSENSUS"
)
print(
    "GW4-GW24 | captaincy OFF | Haaland-safe"
)
print(
    "========================================"
)

print(
    "SCENARIO      MEAN_DISC  WORST_DISC  "
    "DELTA_NO_WC  VS_WC4"
)


scenario_names = [
    "NO_WC",
    *[
        f"WC_GW{gw}"
        for gw
        in selected_timings
    ],
]


summary = {}


no_wc_mean = sum(
    full_results[
        data.name
    ][
        "NO_WC"
    ][
        "discounted_total"
    ]
    for data in runs
) / len(runs)


wc4_values = [
    full_results[
        data.name
    ][
        "WC_GW4"
    ][
        "discounted_total"
    ]
    for data in runs
]

wc4_mean = (
    sum(wc4_values)
    / len(wc4_values)
)


for scenario in (
    scenario_names
):

    values = [
        full_results[
            data.name
        ][
            scenario
        ][
            "discounted_total"
        ]
        for data in runs
    ]

    raw_values = [
        full_results[
            data.name
        ][
            scenario
        ][
            "raw_total"
        ]
        for data in runs
    ]


    mean_value = (
        sum(values)
        / len(values)
    )

    worst_value = min(
        values
    )

    mean_raw = (
        sum(raw_values)
        / len(raw_values)
    )


    summary[
        scenario
    ] = {
        "discounted_values": (
            values
        ),
        "mean_discounted": (
            mean_value
        ),
        "worst_discounted": (
            worst_value
        ),
        "mean_raw": mean_raw,
        "delta_no_wc": (
            mean_value
            - no_wc_mean
        ),
        "vs_wc4": (
            mean_value
            - wc4_mean
        ),
    }


    print(
        f"{scenario:<12} "
        f"{mean_value:>9.2f}  "
        f"{worst_value:>10.2f}  "
        f"{mean_value-no_wc_mean:>+11.2f}  "
        f"{mean_value-wc4_mean:>+7.2f}"
    )


wc_scenarios = [
    scenario
    for scenario
    in scenario_names
    if scenario.startswith(
        "WC_"
    )
]


best_mean = max(
    wc_scenarios,
    key=lambda scenario: (
        summary[
            scenario
        ][
            "mean_discounted"
        ]
    ),
)


best_worst = max(
    wc_scenarios,
    key=lambda scenario: (
        summary[
            scenario
        ][
            "worst_discounted"
        ]
    ),
)


print()
print(
    "BEST MEAN:",
    best_mean,
    f"{summary[best_mean]['mean_discounted']:.2f}",
)

print(
    "BEST WORST-CASE:",
    best_worst,
    f"{summary[best_worst]['worst_discounted']:.2f}",
)


best_later = max(
    (
        scenario
        for scenario
        in wc_scenarios
        if scenario
        != "WC_GW4"
    ),
    key=lambda scenario: (
        summary[
            scenario
        ][
            "mean_discounted"
        ]
    ),
)


gap = (
    summary[
        best_later
    ][
        "mean_discounted"
    ]
    - summary[
        "WC_GW4"
    ][
        "mean_discounted"
    ]
)


print()
print(
    "BEST LATER WINDOW:",
    best_later,
)

print(
    "BEST LATER vs WC_GW4:",
    f"{gap:+.2f} discounted EV",
)


# ============================================================
# SAVE RESULT
# ============================================================


payload = {
    "runs": run_ids,
    "policy": {
        "captaincy_weight": 0.0,
        "haaland_required": True,
        "price_model": (
            "frozen_current_prices"
        ),
        "initial_free_transfers": (
            INITIAL_FT_FALLBACK
        ),
        "max_free_transfers": (
            MAX_FT
        ),
        "wildcard_ft_rule": (
            "saved_ft_retained_no_plus_one"
        ),
        "projection_window": [
            FIRST_GW,
            LAST_EVAL_GW,
        ],
        "wildcard_window": [
            FIRST_GW,
            LAST_WC_GW,
        ],
    },
    "stage1": (
        screen_consensus
    ),
    "selected_timings": (
        selected_timings
    ),
    "full_results": (
        full_results
    ),
    "summary": summary,
    "best_mean": best_mean,
    "best_worst": best_worst,
    "best_later": best_later,
    "best_later_vs_wc4": gap,
}


OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_PATH.write_text(
    json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


print()
print(
    "Saved:",
    OUTPUT_PATH,
)

print()
print(
    "=== DECISION-006B COMPLETE ==="
)
