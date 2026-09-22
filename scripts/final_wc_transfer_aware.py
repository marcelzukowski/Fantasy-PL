from __future__ import annotations

import json
import statistics
import unicodedata

from collections import Counter
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)

from fpl_engine.decision.rolling_transfers import (
    optimize_rolling_free_transfers,
)

from fpl_engine.decision.transfers import (
    PlayerValue,
    SquadState,
)


ROOT = Path.cwd()

RUN_ROOT = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

LONG_RUN_IDS = (
    "20260912T091754Z",
    "20260912T092118Z",
)

PLAN_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_playing_plan.json"
)

SQUAD_STATE_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)

# We plan only GW5-GW9 now.
# Every decision itself sees six future GWs.
ROLLOUT_GWS = range(5, 10)

# Avoid rebuilding half the squad immediately after WC.
MAX_TRANSFERS_PER_GW = 3


# ============================================================
# HELPERS
# ============================================================

def norm(value):

    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        c
        for c in text
        if not unicodedata.combining(c)
    )

    return "".join(
        c.casefold()
        for c in text
        if c.isalnum()
    )


def object_dict(obj):

    if is_dataclass(obj):
        return asdict(obj)

    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "__dict__"):
        return vars(obj)

    return {}


def walk(value, path=""):

    if isinstance(value, dict):

        for key, child in value.items():

            child_path = (
                f"{path}.{key}"
                if path
                else str(key)
            )

            yield child_path, child

            yield from walk(
                child,
                child_path,
            )

    elif isinstance(
        value,
        (list, tuple),
    ):

        for i, child in enumerate(value):

            yield from walk(
                child,
                f"{path}[{i}]",
            )


def extract_objective(plan):

    data = object_dict(plan)

    for key in (
        "objective_value",
        "objective",
        "weighted_objective",
        "total_weighted_ev",
        "weighted_xi_ev",
    ):

        value = data.get(key)

        if isinstance(
            value,
            (int, float),
        ):

            return float(value)

    candidates = []

    for path, value in walk(data):

        if not isinstance(
            value,
            (int, float),
        ):
            continue

        key = path.casefold()

        score = 0

        if "objective" in key:
            score += 100

        if "weighted" in key:
            score += 50

        if "point" in key:
            score += 20

        if score:

            candidates.append(
                (
                    score,
                    path,
                    float(value),
                )
            )

    if not candidates:

        raise RuntimeError(
            "Cannot extract rolling objective"
        )

    candidates.sort(
        reverse=True
    )

    return candidates[0][2]


def extract_squad_now(
    plan,
    valid_ids,
):

    data = object_dict(plan)

    candidates = []

    for path, value in walk(data):

        if not isinstance(
            value,
            (
                list,
                tuple,
                set,
                frozenset,
            ),
        ):
            continue

        ids = frozenset(
            str(x)
            for x in value
            if str(x) in valid_ids
        )

        if len(ids) != 15:
            continue

        key = path.casefold()

        score = 0

        if "squad_now" in key:
            score = 100

        elif "now" in key:
            score = 80

        elif "x0" in key:
            score = 70

        elif "squad" in key:
            score = 50

        candidates.append(
            (
                score,
                path,
                ids,
            )
        )

    if not candidates:

        raise RuntimeError(
            "Cannot extract squad_now"
        )

    candidates.sort(
        reverse=True
    )

    return candidates[0][2]


def current_price_tenths(row):

    value = float(
        row["current_price"]
    )

    if value < 20:
        return int(round(value * 10))

    return int(round(value))


def gw_ev(projection, gw):

    for row in projection.gameweeks:

        if int(row.gameweek) == int(gw):

            return float(
                row.expected_points
            )

    return 0.0


# ============================================================
# LOAD LONG RUNS
# ============================================================

long_runs = []

for run_id in LONG_RUN_IDS:

    path = RUN_ROOT / run_id

    rows = json.loads(
        (
            path
            / "current_players.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    projections = (
        adapt_player_projections(
            json.loads(
                (
                    path
                    / "player_projections.json"
                ).read_text(
                    encoding="utf-8"
                )
            )
        )
    )

    long_runs.append(
        {
            "id": run_id,
            "player_rows": rows,
            "projections": {
                p.player_id: p
                for p in projections
            },
        }
    )


reference = long_runs[0]

metadata = {
    str(row["player_id"]): row
    for row
    in reference["player_rows"]
}

names = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}

positions = {
    pid: row["position"]
    for pid, row
    in metadata.items()
}

prices = {
    pid: current_price_tenths(row)
    for pid, row
    in metadata.items()
}

valid_ids = set(metadata)


# ============================================================
# RESOLVE NAMES
# ============================================================

def resolve(
    display_name,
    *,
    position=None,
):

    matches = [
        pid
        for pid, display
        in names.items()
        if norm(display)
        == norm(display_name)
    ]

    if position is not None:

        matches = [
            pid
            for pid in matches
            if positions[pid]
            == position
        ]

    if len(matches) != 1:

        raise RuntimeError(
            f"Cannot resolve "
            f"{display_name}: "
            f"{matches}"
        )

    return matches[0]


HAALAND = resolve(
    "Haaland",
    position="FWD",
)

DCL = resolve(
    "Calvert-Lewin",
    position="FWD",
)

EVANILSON = resolve(
    "Evanilson",
    position="FWD",
)

TAVERNIER = resolve(
    "Tavernier",
    position="MID",
)

JOAO = resolve(
    "João Pedro",
    position="FWD",
)

ROGERS = resolve(
    "Rogers",
    position="MID",
)

FURO = resolve(
    "Furo",
    position="FWD",
)

OBI = resolve(
    "Obi",
    position="FWD",
)


# ============================================================
# STARTING WC SQUADS
# ============================================================

plan_data = json.loads(
    PLAN_PATH.read_text(
        encoding="utf-8"
    )
)

base = next(
    row
    for row in plan_data["candidates"]
    if "BASE_CAND5"
    in row["labels"]
)

BASE_IDS = frozenset(
    base["player_ids"]
)

JOAO_IDS = frozenset(
    (
        BASE_IDS
        - {
            DCL,
            EVANILSON,
        }
    )
    | {
        FURO,
        JOAO,
    }
)

ROGERS_IDS = frozenset(
    (
        BASE_IDS
        - {
            DCL,
            TAVERNIER,
        }
    )
    | {
        OBI,
        ROGERS,
    }
)


candidates = [
    {
        "label": "BASE",
        "player_ids": BASE_IDS,
        "bank": 1,
        "static_mean": 226.15,
        "static_worst": 224.55,
    },
    {
        "label": "JOAO",
        "player_ids": JOAO_IDS,
        "bank": 0,
        "static_mean": 224.84,
        "static_worst": 223.41,
    },
    {
        "label": "ROGERS",
        "player_ids": ROGERS_IDS,
        "bank": 0,
        "static_mean": 224.67,
        "static_worst": 223.45,
    },
]


# ============================================================
# ORIGINAL SELLING VALUES
# ============================================================

known_ids = set(metadata)


def collect_ids(value):

    result = set()

    if isinstance(value, str):

        if value in known_ids:
            result.add(value)

    elif isinstance(value, dict):

        for child in value.values():

            result |= collect_ids(
                child
            )

    elif isinstance(value, list):

        for child in value:

            result |= collect_ids(
                child
            )

    return result


original_ids = collect_ids(
    json.loads(
        SQUAD_STATE_PATH.read_text(
            encoding="utf-8"
        )
    )
)


selling_by_name = {
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

original_sell = {
    pid:
        selling_by_name[
            norm(names[pid])
        ]
    for pid in original_ids
}


# ============================================================
# PROJECTION REBASE
# ============================================================

def rebuild_projection(
    projection,
    first_gw,
):

    row_map = {
        int(row.gameweek): row
        for row in projection.gameweeks
    }

    selected = []

    for gw in range(
        first_gw,
        first_gw + 6,
    ):

        row = row_map.get(gw)

        if row is None:

            template = (
                projection.gameweeks[0]
            )

            row = replace(
                template,
                gameweek=gw,
                expected_points=0.0,
            )

        selected.append(row)

    raw3 = sum(
        row.expected_points
        for row in selected[:3]
    )

    weighted3 = sum(
        WEIGHTS[i]
        * row.expected_points
        for i, row
        in enumerate(
            selected[:3]
        )
    )

    raw6 = sum(
        row.expected_points
        for row in selected
    )

    weighted6 = sum(
        WEIGHTS[i]
        * row.expected_points
        for i, row
        in enumerate(selected)
    )

    return replace(
        projection,
        current_gameweek=first_gw,
        gameweeks=tuple(selected),
        horizon_3=replace(
            projection.horizon_3,
            first_gameweek=first_gw,
            last_gameweek=(
                first_gw + 2
            ),
            raw_expected_points=raw3,
            weighted_expected_points=(
                weighted3
            ),
            gameweeks=3,
        ),
        horizon_6=replace(
            projection.horizon_6,
            first_gameweek=first_gw,
            last_gameweek=(
                first_gw + 5
            ),
            raw_expected_points=raw6,
            weighted_expected_points=(
                weighted6
            ),
            gameweeks=6,
        ),
    )


def mean_projection_map(
    first_gw,
):

    output = {}

    for pid, base in (
        long_runs[0][
            "projections"
        ].items()
    ):

        base = rebuild_projection(
            base,
            first_gw,
        )

        seed_maps = [
            rebuild_projection(
                run["projections"][pid],
                first_gw,
            )
            for run in long_runs
        ]

        new_rows = []

        for index, base_row in enumerate(
            base.gameweeks
        ):

            mean_ev = statistics.mean(
                seed_map.gameweeks[
                    index
                ].expected_points
                for seed_map
                in seed_maps
            )

            new_rows.append(
                replace(
                    base_row,
                    expected_points=mean_ev,
                )
            )

        raw3 = sum(
            row.expected_points
            for row in new_rows[:3]
        )

        weighted3 = sum(
            WEIGHTS[i]
            * row.expected_points
            for i, row
            in enumerate(
                new_rows[:3]
            )
        )

        raw6 = sum(
            row.expected_points
            for row in new_rows
        )

        weighted6 = sum(
            WEIGHTS[i]
            * row.expected_points
            for i, row
            in enumerate(new_rows)
        )

        output[pid] = replace(
            base,
            gameweeks=tuple(
                new_rows
            ),
            horizon_3=replace(
                base.horizon_3,
                raw_expected_points=raw3,
                weighted_expected_points=(
                    weighted3
                ),
            ),
            horizon_6=replace(
                base.horizon_6,
                raw_expected_points=raw6,
                weighted_expected_points=(
                    weighted6
                ),
            ),
        )

    return output


def seed_projection_map(
    run,
    first_gw,
):

    return {
        pid:
            rebuild_projection(
                projection,
                first_gw,
            )
        for pid, projection
        in run["projections"].items()
    }


# ============================================================
# PLAYER VALUES
# ============================================================

def make_players(
    projection_map,
):

    players = []

    for pid, projection in (
        projection_map.items()
    ):

        row = metadata[pid]

        price = prices[pid]
        price_m = price / 10.0

        ev3 = float(
            projection
            .horizon_3
            .weighted_expected_points
        )

        ev6 = float(
            projection
            .horizon_6
            .weighted_expected_points
        )

        players.append(
            PlayerValue(
                player_id=pid,
                name=names[pid],
                position=(
                    row["position"]
                ),
                team_id=str(
                    row["team_id"]
                ),
                provider_team_id=(
                    row.get(
                        "provider_team_id"
                    )
                ),
                price_tenths=price,
                price_m=price_m,
                ev_3=ev3,
                ev_6=ev6,
                value_3=(
                    ev3 / price_m
                    if price_m
                    else 0.0
                ),
                value_6=(
                    ev6 / price_m
                    if price_m
                    else 0.0
                ),
                minutes_3=float(
                    getattr(
                        projection,
                        "expected_minutes_next_3",
                        0.0,
                    )
                ),
                minutes_6=float(
                    getattr(
                        projection,
                        "expected_minutes_next_6",
                        0.0,
                    )
                ),
                confidence=float(
                    getattr(
                        projection,
                        "projection_confidence",
                        0.0,
                    )
                ),
                uncertainty=float(
                    getattr(
                        projection,
                        "projection_uncertainty",
                        0.0,
                    )
                ),
            )
        )

    return players


# ============================================================
# ROLLING PLAN
# ============================================================

def make_state(
    squad,
    bank,
    sell,
):

    team_counts = dict(
        Counter(
            str(
                metadata[pid][
                    "team_id"
                ]
            )
            for pid in squad
        )
    )

    return SquadState(
        player_ids=frozenset(
            squad
        ),
        bank_tenths=int(bank),
        selling_prices_tenths=(
            dict(sell)
        ),
        team_counts=team_counts,
    )


def run_plan(
    *,
    players,
    projections,
    state,
    ft,
    transfers_now,
    fixed_squad=None,
):

    kwargs = dict(
        players=players,
        projections_by_id=(
            projections
        ),
        state=state,
        horizon=6,
        transfers_now=(
            transfers_now
        ),
        current_free_transfers=ft,
        max_free_transfers=5,
        captaincy_weight=0.0,
    )

    if fixed_squad is not None:

        kwargs[
            "fixed_squad_now_player_ids"
        ] = frozenset(
            fixed_squad
        )

    return (
        optimize_rolling_free_transfers(
            **kwargs
        )
    )


def initial_sell_map(
    squad,
):

    result = {}

    for pid in squad:

        if pid in original_ids:

            result[pid] = (
                original_sell[pid]
            )

        else:

            result[pid] = prices[pid]

    return result


def update_state_after_transfer(
    *,
    old_squad,
    new_squad,
    bank,
    sell,
):

    outs = (
        old_squad
        - new_squad
    )

    ins = (
        new_squad
        - old_squad
    )

    sale = sum(
        sell[pid]
        for pid in outs
    )

    buy = sum(
        prices[pid]
        for pid in ins
    )

    new_bank = (
        bank
        + sale
        - buy
    )

    new_sell = {}

    for pid in new_squad:

        if pid in old_squad:

            new_sell[pid] = (
                sell[pid]
            )

        else:

            # Frozen-price approximation.
            new_sell[pid] = (
                prices[pid]
            )

    return (
        new_bank,
        new_sell,
        outs,
        ins,
    )


# ============================================================
# ROBUST ROLLOUT
# ============================================================

for candidate in candidates:

    squad = frozenset(
        candidate["player_ids"]
    )

    bank = int(
        candidate["bank"]
    )

    sell = initial_sell_map(
        squad
    )

    # WC preserves the 3 saved FTs.
    ft = 3

    candidate["roadmap"] = []

    print()
    print(
        "========================================="
    )
    print(
        candidate["label"],
        "| static",
        f"{candidate['static_mean']:.2f}",
        "/",
        f"{candidate['static_worst']:.2f}",
    )
    print(
        "========================================="
    )

    for gw in ROLLOUT_GWS:

        mean_proj = (
            mean_projection_map(
                gw
            )
        )

        mean_players = (
            make_players(
                mean_proj
            )
        )

        seed_maps = [
            seed_projection_map(
                run,
                gw,
            )
            for run in long_runs
        ]

        seed_players = [
            make_players(
                projection_map
            )
            for projection_map
            in seed_maps
        ]

        state = make_state(
            squad,
            bank,
            sell,
        )

        # ------------------------------------
        # HOLD baselines
        # ------------------------------------

        hold_mean_plan = run_plan(
            players=mean_players,
            projections=mean_proj,
            state=state,
            ft=ft,
            transfers_now=0,
        )

        hold_mean_obj = (
            extract_objective(
                hold_mean_plan
            )
        )

        hold_seed_obj = []

        for index in range(
            len(long_runs)
        ):

            plan = run_plan(
                players=(
                    seed_players[index]
                ),
                projections=(
                    seed_maps[index]
                ),
                state=state,
                ft=ft,
                transfers_now=0,
            )

            hold_seed_obj.append(
                extract_objective(
                    plan
                )
            )

        # ------------------------------------
        # TRANSFER OPTIONS
        # ------------------------------------

        options = []

        max_n = min(
            ft,
            MAX_TRANSFERS_PER_GW,
        )

        for n in range(
            1,
            max_n + 1,
        ):

            try:

                mean_plan = run_plan(
                    players=mean_players,
                    projections=mean_proj,
                    state=state,
                    ft=ft,
                    transfers_now=n,
                )

                proposed_squad = (
                    extract_squad_now(
                        mean_plan,
                        valid_ids,
                    )
                )

                # Haaland is protected in the transfer rollout.
                # Captaincy is deliberately disabled in this model,
                # so allowing the optimizer to sell a premium captain
                # systematically undervalues his real FPL utility.
                if HAALAND not in proposed_squad:
                    continue

                outs = squad - proposed_squad
                ins = proposed_squad - squad

                if (
                    len(outs) != n
                    or len(ins) != n
                ):
                    continue

                mean_obj = (
                    extract_objective(
                        mean_plan
                    )
                )

                deltas = []

                seed_objs = []

                valid = True

                for index in range(
                    len(long_runs)
                ):

                    try:

                        fixed_plan = (
                            run_plan(
                                players=(
                                    seed_players[
                                        index
                                    ]
                                ),
                                projections=(
                                    seed_maps[
                                        index
                                    ]
                                ),
                                state=state,
                                ft=ft,
                                transfers_now=n,
                                fixed_squad=(
                                    proposed_squad
                                ),
                            )
                        )

                        obj = (
                            extract_objective(
                                fixed_plan
                            )
                        )

                        seed_objs.append(
                            obj
                        )

                        deltas.append(
                            obj
                            - hold_seed_obj[
                                index
                            ]
                        )

                    except Exception:

                        valid = False
                        break

                if not valid:
                    continue

                options.append(
                    {
                        "n": n,
                        "squad": (
                            proposed_squad
                        ),
                        "outs": outs,
                        "ins": ins,
                        "mean_model_delta": (
                            mean_obj
                            - hold_mean_obj
                        ),
                        "seed_deltas": (
                            deltas
                        ),
                        "mean_delta": (
                            statistics.mean(
                                deltas
                            )
                        ),
                        "worst_delta": (
                            min(deltas)
                        ),
                    }
                )

            except Exception:
                continue

        # ------------------------------------
        # DECISION GUARD
        # ------------------------------------

        accepted = []

        for option in options:

            n = option["n"]

            normal_pass = (
                option["mean_delta"]
                >= 0.75
                and option[
                    "worst_delta"
                ]
                >= 0.25
            )

            cap_pass = (
                ft == 5
                and n == 1
                and option[
                    "mean_delta"
                ]
                >= 0.30
                and option[
                    "worst_delta"
                ]
                >= 0.00
            )

            if normal_pass or cap_pass:

                accepted.append(
                    option
                )

        accepted.sort(
            key=lambda x: (
                x["worst_delta"],
                x["mean_delta"],
                -x["n"],
            ),
            reverse=True,
        )

        chosen = (
            accepted[0]
            if accepted
            else None
        )

        # Best rejected option = watchlist.
        options.sort(
            key=lambda x: (
                x["worst_delta"],
                x["mean_delta"],
            ),
            reverse=True,
        )

        watch = (
            options[0]
            if options
            else None
        )

        if chosen is None:

            action = "HOLD"

            ft_next = min(
                5,
                ft + 1,
            )

            print()
            print(
                f"GW{gw} | FT {ft} | HOLD "
                f"-> FT {ft_next}"
            )

            if watch is not None:

                print(
                    "  best alternative:",
                    ", ".join(
                        names[pid]
                        for pid in sorted(
                            watch["outs"],
                            key=lambda x:
                                names[x],
                        )
                    ),
                    "->",
                    ", ".join(
                        names[pid]
                        for pid in sorted(
                            watch["ins"],
                            key=lambda x:
                                names[x],
                        )
                    ),
                )

                print(
                    "  gain mean/worst:",
                    f"{watch['mean_delta']:+.2f}",
                    "/",
                    f"{watch['worst_delta']:+.2f}",
                    "|",
                    f"{watch['n']} FT",
                )

            candidate[
                "roadmap"
            ].append(
                {
                    "gw": gw,
                    "action": "HOLD",
                    "ft_before": ft,
                    "ft_after": (
                        ft_next
                    ),
                }
            )

            ft = ft_next

        else:

            (
                new_bank,
                new_sell,
                outs,
                ins,
            ) = (
                update_state_after_transfer(
                    old_squad=squad,
                    new_squad=(
                        chosen["squad"]
                    ),
                    bank=bank,
                    sell=sell,
                )
            )

            ft_next = min(
                5,
                ft
                - chosen["n"]
                + 1,
            )

            print()
            print(
                f"GW{gw} | FT {ft} | "
                f"TAKE {chosen['n']} FT"
            )

            print(
                "  OUT:",
                ", ".join(
                    names[pid]
                    for pid in sorted(
                        outs,
                        key=lambda x:
                            names[x],
                    )
                ),
            )

            print(
                "  IN :",
                ", ".join(
                    names[pid]
                    for pid in sorted(
                        ins,
                        key=lambda x:
                            names[x],
                    )
                ),
            )

            print(
                "  gain mean/worst:",
                f"{chosen['mean_delta']:+.2f}",
                "/",
                f"{chosen['worst_delta']:+.2f}",
            )

            print(
                f"  bank: "
                f"{bank/10:.1f} -> "
                f"{new_bank/10:.1f} | "
                f"FT -> {ft_next}"
            )

            candidate[
                "roadmap"
            ].append(
                {
                    "gw": gw,
                    "action": "TRANSFER",
                    "ft_before": ft,
                    "ft_after": ft_next,
                    "outs": [
                        names[pid]
                        for pid in outs
                    ],
                    "ins": [
                        names[pid]
                        for pid in ins
                    ],
                    "mean_gain": (
                        chosen[
                            "mean_delta"
                        ]
                    ),
                    "worst_gain": (
                        chosen[
                            "worst_delta"
                        ]
                    ),
                }
            )

            squad = frozenset(
                chosen["squad"]
            )

            bank = new_bank
            sell = new_sell
            ft = ft_next

    candidate[
        "final_squad"
    ] = squad

    candidate[
        "final_bank"
    ] = bank

    candidate[
        "final_ft"
    ] = ft


# ============================================================
# COMPACT SUMMARY
# ============================================================

print()
print()
print(
    "========================================="
)
print(
    "TRANSFER-AWARE FINAL SUMMARY"
)
print(
    "========================================="
)

for candidate in candidates:

    transfers = [
        row
        for row in candidate[
            "roadmap"
        ]
        if row["action"]
        == "TRANSFER"
    ]

    print()
    print(
        f"{candidate['label']:<8} "
        f"initial="
        f"{candidate['static_mean']:.2f}/"
        f"{candidate['static_worst']:.2f} "
        f"| moves={len(transfers)} "
        f"| final FT="
        f"{candidate['final_ft']} "
        f"| bank="
        f"{candidate['final_bank']/10:.1f}"
    )

    if not transfers:

        print(
            "  GW5-GW9: HOLD throughout"
        )

    else:

        for move in transfers:

            print(
                f"  GW{move['gw']}: "
                + ", ".join(
                    move["outs"]
                )
                + " -> "
                + ", ".join(
                    move["ins"]
                )
                + " | gain "
                + f"{move['mean_gain']:+.2f}"
                + "/"
                + f"{move['worst_gain']:+.2f}"
            )

print()
print(
    "NOTE: gains are six-GW rolling "
    "fixture-adjusted objective gains."
)
print(
    "Captaincy disabled; frozen-price "
    "approximation; 2 long-horizon seeds."
)
print(
    "=== END ==="
)
