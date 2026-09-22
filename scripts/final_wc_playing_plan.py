from __future__ import annotations

import inspect
import json
import math
import statistics
import unicodedata

from collections import Counter
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from fpl_engine.decision.autosubs import (
    evaluate_autosub_lineup,
    optimize_autosub_lineup,
)
from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)
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

FINAL_RUN_MAP = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_256_run_map.txt"
)

FINAL_RESULTS = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_robust_results.json"
)

SQUAD_STATE_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

OUTPUT_JSON = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_playing_plan.json"
)

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)

GWS = tuple(range(4, 10))

LONG_RUN_IDS = (
    "20260912T091754Z",
    "20260912T092118Z",
)


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


def rows_from_json(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        for key in (
            "rows",
            "data",
            "records",
            "minutes",
            "fixtures",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    raise RuntimeError(
        "Unsupported JSON row structure"
    )


def price_tenths(row):

    value = float(
        row["current_price"]
    )

    if value < 20:
        return int(round(value * 10))

    return int(round(value))


def load_run(run_id):

    path = RUN_ROOT / run_id

    player_rows = json.loads(
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

    return {
        "id": run_id,
        "path": path,
        "player_rows": player_rows,
        "projections": {
            p.player_id: p
            for p in projections
        },
    }


def gw_ev(
    projection,
    gw,
):

    for row in projection.gameweeks:

        if int(row.gameweek) == int(gw):

            return float(
                row.expected_points
            )

    return 0.0


def load_availability(run):

    path = run["path"]

    minute_rows = rows_from_json(
        json.loads(
            (
                path
                / "minutes.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_rows = rows_from_json(
        json.loads(
            (
                path
                / "fixture_horizon.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_to_gw = {}

    for row in fixture_rows:

        if not isinstance(row, dict):
            continue

        gw = (
            row.get("gameweek")
            or row.get("target_gameweek")
            or row.get("event")
        )

        if gw is None:
            continue

        for key in (
            "fixture_id",
            "canonical_fixture_id",
            "id",
        ):

            fixture_id = row.get(key)

            if fixture_id is not None:

                fixture_to_gw[
                    str(fixture_id)
                ] = int(gw)

    grouped = {}

    for row in minute_rows:

        if not isinstance(row, dict):
            continue

        player_id = row.get(
            "player_id"
        )

        p = row.get(
            "p_appearance"
        )

        if player_id is None or p is None:
            continue

        gw = (
            row.get("gameweek")
            or row.get("target_gameweek")
        )

        if gw is None:

            fixture_id = row.get(
                "fixture_id"
            )

            if fixture_id is not None:

                gw = fixture_to_gw.get(
                    str(fixture_id)
                )

        if gw is None:
            continue

        key = (
            str(player_id),
            int(gw),
        )

        grouped.setdefault(
            key,
            [],
        ).append(
            float(p)
        )

    result = {}

    for key, values in grouped.items():

        result[key] = (
            1.0
            - math.prod(
                1.0 - max(
                    0.0,
                    min(1.0, p),
                )
                for p in values
            )
        )

    return result


def mean_projection_map(
    runs,
):

    base_map = runs[0]["projections"]

    result = {}

    for player_id, base in base_map.items():

        new_gameweeks = []

        for base_gw in base.gameweeks:

            gw = int(
                base_gw.gameweek
            )

            values = []

            for run in runs:

                projection = (
                    run["projections"].get(
                        player_id
                    )
                )

                if projection is not None:

                    values.append(
                        gw_ev(
                            projection,
                            gw,
                        )
                    )

            mean_ev = (
                statistics.mean(values)
                if values
                else 0.0
            )

            new_gameweeks.append(
                replace(
                    base_gw,
                    expected_points=mean_ev,
                )
            )

        result[player_id] = replace(
            base,
            gameweeks=tuple(
                new_gameweeks
            ),
        )

    return result


def rebuild_horizons(
    projection,
    first_gw,
):

    rows_by_gw = {
        int(row.gameweek): row
        for row in projection.gameweeks
    }

    gameweeks = []

    for gw in range(
        first_gw,
        first_gw + 6,
    ):

        row = rows_by_gw.get(gw)

        if row is None:

            template = (
                projection.gameweeks[0]
            )

            row = replace(
                template,
                gameweek=gw,
                expected_points=0.0,
            )

        gameweeks.append(row)

    raw3 = sum(
        row.expected_points
        for row in gameweeks[:3]
    )

    weighted3 = sum(
        row.expected_points
        * WEIGHTS[i]
        for i, row
        in enumerate(
            gameweeks[:3]
        )
    )

    raw6 = sum(
        row.expected_points
        for row in gameweeks
    )

    weighted6 = sum(
        row.expected_points
        * WEIGHTS[i]
        for i, row
        in enumerate(
            gameweeks
        )
    )

    return replace(
        projection,
        current_gameweek=first_gw,
        gameweeks=tuple(
            gameweeks
        ),
        horizon_3=replace(
            projection.horizon_3,
            first_gameweek=first_gw,
            last_gameweek=first_gw + 2,
            raw_expected_points=raw3,
            weighted_expected_points=weighted3,
            gameweeks=3,
        ),
        horizon_6=replace(
            projection.horizon_6,
            first_gameweek=first_gw,
            last_gameweek=first_gw + 5,
            raw_expected_points=raw6,
            weighted_expected_points=weighted6,
            gameweeks=6,
        ),
    )


def object_dict(obj):

    if is_dataclass(obj):
        return asdict(obj)

    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "__dict__"):
        return vars(obj)

    return {}


def walk_values(
    value,
    path="",
):

    if isinstance(value, dict):

        for key, child in value.items():

            child_path = (
                f"{path}.{key}"
                if path
                else str(key)
            )

            yield (
                child_path,
                child,
            )

            yield from walk_values(
                child,
                child_path,
            )

    elif isinstance(
        value,
        (list, tuple),
    ):

        for i, child in enumerate(value):

            yield from walk_values(
                child,
                f"{path}[{i}]",
            )


def result_total(result):

    data = object_dict(result)

    preferred = (
        "total_expected_points",
        "total_ev",
        "expected_total",
        "total",
    )

    for key in preferred:

        value = data.get(key)

        if isinstance(
            value,
            (int, float),
        ):

            return float(value)

    for path, value in walk_values(data):

        if (
            isinstance(
                value,
                (int, float),
            )
            and "total" in path.casefold()
            and "point" in path.casefold()
        ):

            return float(value)

    raise RuntimeError(
        "Could not extract autosub total"
    )


def extract_lineup(
    result,
    valid_ids,
):

    data = object_dict(result)

    starter_ids = None
    bench_gk = None
    bench_outfield = None

    for path, value in walk_values(data):

        key = path.casefold()

        if isinstance(
            value,
            (list, tuple, set, frozenset),
        ):

            ids = [
                str(x)
                for x in value
                if str(x) in valid_ids
            ]

            if (
                len(ids) == 11
                and (
                    "starter" in key
                    or "starting" in key
                    or "xi" in key
                )
            ):

                starter_ids = tuple(ids)

            if (
                len(ids) == 3
                and "bench" in key
                and "outfield" in key
            ):

                bench_outfield = tuple(ids)

        if (
            isinstance(value, str)
            and value in valid_ids
            and "bench" in key
            and (
                "gk" in key
                or "goalkeeper" in key
            )
        ):

            bench_gk = value

    if (
        starter_ids is None
        or bench_gk is None
        or bench_outfield is None
    ):

        raise RuntimeError(
            "Could not extract lineup from "
            "optimize_autosub_lineup result. "
            f"Top-level keys={list(data)}"
        )

    return (
        starter_ids,
        bench_gk,
        bench_outfield,
    )


def call_lineup_optimizer(
    *,
    gw,
    squad_ids,
    positions,
    expected_points,
    p_appearance,
):

    signature = inspect.signature(
        optimize_autosub_lineup
    )

    kwargs = {}

    for name, parameter in (
        signature.parameters.items()
    ):

        if name == "gameweek":

            kwargs[name] = gw

        elif name in (
            "squad_ids",
            "player_ids",
            "squad_player_ids",
        ):

            kwargs[name] = tuple(
                squad_ids
            )

        elif name == "positions":

            kwargs[name] = positions

        elif name == "expected_points":

            kwargs[name] = expected_points

        elif name == "p_appearance":

            kwargs[name] = p_appearance

        elif parameter.default is inspect._empty:

            raise RuntimeError(
                "Unsupported required parameter in "
                "optimize_autosub_lineup: "
                f"{name}"
            )

    result = optimize_autosub_lineup(
        **kwargs
    )

    starters, bench_gk, bench_outfield = (
        extract_lineup(
            result,
            set(squad_ids),
        )
    )

    return {
        "starter_ids": starters,
        "bench_gk_id": bench_gk,
        "bench_outfield_ids": (
            bench_outfield
        ),
        "total": result_total(result),
    }


def evaluate_fixed_lineup(
    *,
    gw,
    lineup,
    positions,
    expected_points,
    p_appearance,
):

    result = evaluate_autosub_lineup(
        gameweek=gw,
        starter_ids=(
            lineup["starter_ids"]
        ),
        bench_gk_id=(
            lineup["bench_gk_id"]
        ),
        bench_outfield_ids=(
            lineup[
                "bench_outfield_ids"
            ]
        ),
        positions=positions,
        expected_points=expected_points,
        p_appearance=p_appearance,
    )

    return result_total(result)


# ============================================================
# LOAD FINAL 4 x 256 RUNS
# ============================================================

run_lines = FINAL_RUN_MAP.read_text(
    encoding="utf-8-sig"
).splitlines()

final_run_ids = [
    line.split("run=", 1)[1].strip()
    for line in run_lines
    if "run=" in line
]

if len(final_run_ids) != 4:

    raise RuntimeError(
        f"Expected four final runs, "
        f"got {final_run_ids}"
    )

runs = [
    load_run(run_id)
    for run_id in final_run_ids
]

reference = runs[0]

metadata = {
    str(row["player_id"]): row
    for row
    in reference["player_rows"]
}

positions = {
    pid: row["position"]
    for pid, row
    in metadata.items()
}

names = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}

prices = {
    pid: price_tenths(row)
    for pid, row
    in metadata.items()
}

mean_projections = (
    mean_projection_map(runs)
)

availability_by_run = [
    load_availability(run)
    for run in runs
]


# ============================================================
# MEAN AVAILABILITY
# ============================================================

mean_papp = {}

for player_id in metadata:

    for gw in GWS:

        values = []

        for availability in (
            availability_by_run
        ):

            key = (
                player_id,
                gw,
            )

            if key in availability:

                values.append(
                    availability[key]
                )

        if values:

            mean_papp[
                (
                    player_id,
                    gw,
                )
            ] = statistics.mean(
                values
            )


# ============================================================
# IDS
# ============================================================

def resolve_name(
    name,
    *,
    position=None,
    expected_price_tenths=None,
):

    matches = [
        pid
        for pid, display
        in names.items()
        if norm(display)
        == norm(name)
    ]

    if position is not None:

        matches = [
            pid
            for pid in matches
            if positions.get(pid)
            == position
        ]

    if expected_price_tenths is not None:

        matches = [
            pid
            for pid in matches
            if prices.get(pid)
            == expected_price_tenths
        ]

    if len(matches) != 1:

        details = [
            {
                "id": pid,
                "name": names.get(pid),
                "position": positions.get(pid),
                "price": prices.get(pid),
                "team_id": metadata.get(
                    pid,
                    {},
                ).get("team_id"),
            }
            for pid in matches
        ]

        raise RuntimeError(
            f"Cannot uniquely resolve "
            f"{name}: {details}"
        )

    return matches[0]


HAALAND = resolve_name(
    "Haaland"
)

BRUNO = resolve_name(
    "B.Fernandes"
)

GROSS = resolve_name(
    "Groß"
)

SZOBOSZLAI = resolve_name(
    "Szoboszlai"
)

PALMER = resolve_name(
    "Palmer",
    position="MID",
    expected_price_tenths=97,
)

JOAO = resolve_name(
    "João Pedro"
)

GABRIEL = resolve_name(
    "Gabriel"
)

CORE = {
    HAALAND,
    BRUNO,
    GROSS,
    SZOBOSZLAI,
}


# ============================================================
# CURRENT SQUAD + SELLING PRICES
# ============================================================

known_ids = set(metadata)


def collect_known_ids(value):

    found = set()

    if isinstance(value, str):

        if value in known_ids:
            found.add(value)

    elif isinstance(value, dict):

        for child in value.values():

            found.update(
                collect_known_ids(
                    child
                )
            )

    elif isinstance(value, list):

        for child in value:

            found.update(
                collect_known_ids(
                    child
                )
            )

    return found


current_ids = collect_known_ids(
    json.loads(
        SQUAD_STATE_PATH.read_text(
            encoding="utf-8"
        )
    )
)

if len(current_ids) != 15:

    raise RuntimeError(
        f"Current squad resolved "
        f"{len(current_ids)}/15"
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

selling_prices = {
    pid: selling_by_name[
        norm(names[pid])
    ]
    for pid in current_ids
}


# ============================================================
# REBUILD MEAN 6GW PROJECTIONS
# ============================================================

mean6 = {
    pid: rebuild_horizons(
        projection,
        4,
    )
    for pid, projection
    in mean_projections.items()
}


# ============================================================
# CANDIDATES
# ============================================================

final_result = json.loads(
    FINAL_RESULTS.read_text(
        encoding="utf-8"
    )
)

base_winner = final_result[
    "winner"
]

base_ids = frozenset(
    base_winner[
        "player_ids"
    ]
)

candidate_rows = []


def add_candidate(
    label,
    player_ids,
    bank,
    source_xi_ev=None,
):

    key = frozenset(
        player_ids
    )

    for row in candidate_rows:

        if row["player_ids"] == key:

            row["labels"].append(label)
            return

    candidate_rows.append(
        {
            "labels": [label],
            "player_ids": key,
            "bank": int(bank),
            "source_xi_ev": (
                source_xi_ev
            ),
        }
    )


add_candidate(
    "BASE_CAND5",
    base_ids,
    base_winner[
        "remaining_budget_tenths"
    ],
)


def generate_variant(
    label,
    required,
):

    plan = optimize_unlimited_squad(
        player_rows=(
            reference[
                "player_rows"
            ]
        ),
        projections_by_id=mean6,
        current_player_ids=(
            current_ids
        ),
        selling_prices_tenths=(
            selling_prices
        ),
        bank_tenths=0,
        first_gameweek=4,
        horizon=6,
        weights=WEIGHTS,
        required_player_ids=tuple(
            required
        ),
    )

    add_candidate(
        label,
        plan.player_ids,
        plan.remaining_budget_tenths,
        plan.weighted_xi_ev,
    )


generate_variant(
    "JOAO_CORE",
    CORE | {
        JOAO,
    },
)

generate_variant(
    "GABRIEL_CORE",
    CORE | {
        GABRIEL,
    },
)

generate_variant(
    "JOAO_GABRIEL_CORE",
    CORE | {
        JOAO,
        GABRIEL,
    },
)

generate_variant(
    "JOAO_GABRIEL_PALMER",
    CORE | {
        JOAO,
        GABRIEL,
        PALMER,
    },
)


print()
print(
    "Candidates:",
    len(candidate_rows),
)
print(
    "Lineup optimization can take "
    "a few minutes."
)
print()


# ============================================================
# LINEUP + ROBUST CROSS-SCORE
# ============================================================

for index, candidate in enumerate(
    candidate_rows,
    start=1,
):

    squad = candidate[
        "player_ids"
    ]

    weekly = []
    world_totals = [
        0.0
        for _ in runs
    ]

    print(
        f"[{index}/{len(candidate_rows)}] "
        f"{'+'.join(candidate['labels'])}"
    )

    for offset, gw in enumerate(GWS):

        expected_points = {
            pid: gw_ev(
                mean6[pid],
                gw,
            )
            for pid in squad
        }

        papp = {}

        for pid in squad:

            key = (
                pid,
                gw,
            )

            if key in mean_papp:

                papp[pid] = (
                    mean_papp[key]
                )

            elif abs(
                expected_points[pid]
            ) < 1e-9:

                papp[pid] = 0.0

            else:

                raise RuntimeError(
                    "Missing p_appearance: "
                    f"{names[pid]} GW{gw}"
                )

        lineup = call_lineup_optimizer(
            gw=gw,
            squad_ids=squad,
            positions=positions,
            expected_points=(
                expected_points
            ),
            p_appearance=papp,
        )

        world_scores = []

        for run_index, run in enumerate(
            runs
        ):

            run_ev = {
                pid: gw_ev(
                    run[
                        "projections"
                    ][pid],
                    gw,
                )
                for pid in squad
            }

            run_papp = {}

            availability = (
                availability_by_run[
                    run_index
                ]
            )

            for pid in squad:

                key = (
                    pid,
                    gw,
                )

                if key in availability:

                    run_papp[pid] = (
                        availability[key]
                    )

                elif abs(
                    run_ev[pid]
                ) < 1e-9:

                    run_papp[pid] = 0.0

                else:

                    raise RuntimeError(
                        "World missing "
                        "p_appearance: "
                        f"{names[pid]} "
                        f"GW{gw}"
                    )

            score = (
                evaluate_fixed_lineup(
                    gw=gw,
                    lineup=lineup,
                    positions=positions,
                    expected_points=run_ev,
                    p_appearance=run_papp,
                )
            )

            world_scores.append(
                score
            )

            world_totals[
                run_index
            ] += (
                WEIGHTS[offset]
                * score
            )

        weekly.append(
            {
                "gameweek": gw,
                "starter_ids": list(
                    lineup[
                        "starter_ids"
                    ]
                ),
                "bench_gk_id": (
                    lineup[
                        "bench_gk_id"
                    ]
                ),
                "bench_outfield_ids": list(
                    lineup[
                        "bench_outfield_ids"
                    ]
                ),
                "ensemble_score": (
                    lineup["total"]
                ),
                "world_scores": (
                    world_scores
                ),
            }
        )

    candidate[
        "weekly"
    ] = weekly

    candidate[
        "world_totals"
    ] = world_totals

    candidate[
        "mean"
    ] = statistics.mean(
        world_totals
    )

    candidate[
        "worst"
    ] = min(
        world_totals
    )

    candidate[
        "spread"
    ] = (
        max(world_totals)
        - min(world_totals)
    )


candidate_rows.sort(
    key=lambda x: (
        x["worst"],
        x["mean"],
    ),
    reverse=True,
)


best = candidate_rows[0]

preferred_candidates = [
    row
    for row in candidate_rows
    if JOAO in row["player_ids"]
    and GABRIEL in row["player_ids"]
]

best_preferred = (
    preferred_candidates[0]
    if preferred_candidates
    else None
)


# ============================================================
# LONG-HORIZON MEAN FOR TRANSFER ROADMAP
# ============================================================

long_runs = [
    load_run(run_id)
    for run_id in LONG_RUN_IDS
]

long_mean = mean_projection_map(
    long_runs
)


def player_values_for_gw(
    projection_map,
    gw,
):

    rebased = {
        pid: rebuild_horizons(
            projection,
            gw,
        )
        for pid, projection
        in projection_map.items()
    }

    players = []

    for pid, projection in (
        rebased.items()
    ):

        row = metadata[pid]

        price = prices[pid]

        price_m = (
            price / 10.0
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
                ev_3=(
                    projection
                    .horizon_3
                    .weighted_expected_points
                ),
                ev_6=(
                    projection
                    .horizon_6
                    .weighted_expected_points
                ),
                value_3=(
                    projection
                    .horizon_3
                    .weighted_expected_points
                    / price_m
                    if price_m
                    else 0.0
                ),
                value_6=(
                    projection
                    .horizon_6
                    .weighted_expected_points
                    / price_m
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

    return (
        rebased,
        players,
    )


def extract_objective(plan):

    data = object_dict(plan)

    priority = (
        "objective_value",
        "objective",
        "weighted_objective",
        "total_weighted_ev",
        "weighted_xi_ev",
    )

    for key in priority:

        value = data.get(key)

        if isinstance(
            value,
            (int, float),
        ):

            return float(value)

    for path, value in walk_values(data):

        key = path.casefold()

        if (
            isinstance(
                value,
                (int, float),
            )
            and (
                "objective" in key
                or "weighted" in key
            )
        ):

            return float(value)

    return None


def ids_from_value(
    value,
    valid_ids,
):

    if not isinstance(
        value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):

        return None

    ids = [
        str(x)
        for x in value
        if str(x) in valid_ids
    ]

    if len(ids) == 15:
        return frozenset(ids)

    return None


def extract_squad_now(
    plan,
    valid_ids,
):

    data = object_dict(plan)

    candidates = []

    for path, value in walk_values(data):

        ids = ids_from_value(
            value,
            valid_ids,
        )

        if ids is None:
            continue

        key = path.casefold()

        rank = 0

        if "squad_now" in key:
            rank = 100

        elif "now" in key:
            rank = 80

        elif "x0" in key:
            rank = 70

        elif "squad" in key:
            rank = 50

        candidates.append(
            (
                rank,
                path,
                ids,
            )
        )

    if not candidates:

        raise RuntimeError(
            "Could not extract squad_now. "
            f"Plan keys={list(data)}"
        )

    candidates.sort(
        reverse=True
    )

    return candidates[0][2]


def transfer_rollout(
    candidate,
):

    squad = frozenset(
        candidate[
            "player_ids"
        ]
    )

    bank = int(
        candidate[
            "bank"
        ]
    )

    # WC in GW4 preserves the three saved FTs.
    ft = 3

    # Retained pre-WC players keep their known
    # selling value; new WC buys use current price.
    sell = {}

    for pid in squad:

        if pid in current_ids:

            sell[pid] = (
                selling_prices[pid]
            )

        else:

            sell[pid] = prices[pid]

    actions = []

    valid_ids = set(metadata)

    for gw in range(5, 10):

        projection_map, players = (
            player_values_for_gw(
                long_mean,
                gw,
            )
        )

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

        state = SquadState(
            player_ids=squad,
            bank_tenths=bank,
            selling_prices_tenths=(
                dict(sell)
            ),
            team_counts=team_counts,
        )

        options = []

        for transfers_now in range(
            0,
            ft + 1,
        ):

            try:

                plan = (
                    optimize_rolling_free_transfers(
                        players=players,
                        projections_by_id=(
                            projection_map
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
                )

                squad_now = (
                    extract_squad_now(
                        plan,
                        valid_ids,
                    )
                )

                objective = (
                    extract_objective(
                        plan
                    )
                )

                if objective is None:

                    raise RuntimeError(
                        "No rolling objective "
                        "found"
                    )

                options.append(
                    (
                        objective,
                        transfers_now,
                        squad_now,
                    )
                )

            except Exception:
                continue

        if not options:

            raise RuntimeError(
                f"No valid rolling plan GW{gw}"
            )

        options.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        objective, n, new_squad = (
            options[0]
        )

        transfers_out = sorted(
            squad - new_squad,
            key=lambda pid: names[pid],
        )

        transfers_in = sorted(
            new_squad - squad,
            key=lambda pid: names[pid],
        )

        sale_value = sum(
            sell[pid]
            for pid in transfers_out
        )

        buy_value = sum(
            prices[pid]
            for pid in transfers_in
        )

        bank = (
            bank
            + sale_value
            - buy_value
        )

        new_sell = {}

        for pid in new_squad:

            if pid in squad:

                new_sell[pid] = (
                    sell[pid]
                )

            else:

                new_sell[pid] = (
                    prices[pid]
                )

        ft_next = min(
            5,
            ft - n + 1,
        )

        actions.append(
            {
                "gameweek": gw,
                "ft_before": ft,
                "transfers": n,
                "out_ids": (
                    transfers_out
                ),
                "in_ids": (
                    transfers_in
                ),
                "bank_after": bank,
                "ft_next": ft_next,
                "objective": objective,
            }
        )

        squad = new_squad
        sell = new_sell
        ft = ft_next

    return actions


# ============================================================
# TRANSFER ROADMAP
# ============================================================

for candidate in {
    id(best): best,
    **(
        {
            id(best_preferred):
                best_preferred
        }
        if best_preferred
        else {}
    ),
}.values():

    try:

        candidate[
            "transfer_rollout"
        ] = transfer_rollout(
            candidate
        )

    except Exception as exc:

        candidate[
            "transfer_rollout_error"
        ] = str(exc)


# ============================================================
# SAVE
# ============================================================

payload = {
    "method": (
        "4x256 robust GW4-GW9 lineup "
        "+ 2-run long-horizon transfer roadmap"
    ),
    "candidates": candidate_rows,
}

def json_default(value):

    if isinstance(
        value,
        (set, frozenset),
    ):
        return sorted(value)

    if is_dataclass(value):
        return asdict(value)

    raise TypeError(
        f"Object of type "
        f"{value.__class__.__name__} "
        f"is not JSON serializable"
    )


OUTPUT_JSON.write_text(
    json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        default=json_default,
    ),
    encoding="utf-8",
)


# ============================================================
# COMPACT REPORT
# ============================================================

def label(candidate):

    return "+".join(
        candidate["labels"]
    )


def names_for(ids):

    return [
        names[pid]
        for pid in ids
    ]


print()
print(
    "========================================"
)
print(
    "FINAL WC ROTATION - ROBUST SUMMARY"
)
print(
    "========================================"
)

for rank, candidate in enumerate(
    candidate_rows,
    start=1,
):

    flags = []

    if JOAO in candidate[
        "player_ids"
    ]:
        flags.append("JP")

    if GABRIEL in candidate[
        "player_ids"
    ]:
        flags.append("GAB")

    if PALMER in candidate[
        "player_ids"
    ]:
        flags.append("PAL")

    print(
        f"{rank}. "
        f"{label(candidate):<28} "
        f"mean={candidate['mean']:.2f} "
        f"worst={candidate['worst']:.2f} "
        f"spread={candidate['spread']:.2f} "
        f"bank={candidate['bank']/10:.1f} "
        f"[{','.join(flags)}]"
    )


def print_candidate_plan(
    title,
    candidate,
):

    print()
    print(
        "========================================"
    )
    print(title)
    print(
        label(candidate)
    )
    print(
        f"mean={candidate['mean']:.2f} "
        f"worst={candidate['worst']:.2f} "
        f"bank={candidate['bank']/10:.1f}"
    )
    print(
        "========================================"
    )

    for weekly in candidate[
        "weekly"
    ]:

        gw = weekly[
            "gameweek"
        ]

        starters = (
            weekly[
                "starter_ids"
            ]
        )

        by_position = {
            pos: []
            for pos in (
                "GK",
                "DEF",
                "MID",
                "FWD",
            )
        }

        for pid in starters:

            by_position[
                positions[pid]
            ].append(
                names[pid]
            )

        print()
        print(
            f"GW{gw} | "
            f"ensemble={weekly['ensemble_score']:.2f}"
        )

        print(
            "  GK : "
            + ", ".join(
                by_position["GK"]
            )
        )

        print(
            "  DEF: "
            + ", ".join(
                by_position["DEF"]
            )
        )

        print(
            "  MID: "
            + ", ".join(
                by_position["MID"]
            )
        )

        print(
            "  FWD: "
            + ", ".join(
                by_position["FWD"]
            )
        )

        print(
            "  BENCH GK: "
            + names[
                weekly[
                    "bench_gk_id"
                ]
            ]
        )

        print(
            "  BENCH 1-3: "
            + " | ".join(
                names[pid]
                for pid in weekly[
                    "bench_outfield_ids"
                ]
            )
        )

    start_counts = Counter()

    for weekly in candidate[
        "weekly"
    ]:

        start_counts.update(
            weekly[
                "starter_ids"
            ]
        )

    print()
    print(
        "START COUNTS GW4-GW9"
    )

    for pid in sorted(
        candidate[
            "player_ids"
        ],
        key=lambda x: (
            positions[x],
            -start_counts[x],
            names[x],
        ),
    ):

        print(
            f"  {positions[pid]:<3} "
            f"{names[pid]:<20} "
            f"{start_counts[pid]}/6"
        )

    print()
    print(
        "FT ROADMAP "
        "(secondary / long-horizon)"
    )

    if candidate.get(
        "transfer_rollout"
    ):

        for action in candidate[
            "transfer_rollout"
        ]:

            gw = action[
                "gameweek"
            ]

            outs = [
                names[pid]
                for pid in action[
                    "out_ids"
                ]
            ]

            ins = [
                names[pid]
                for pid in action[
                    "in_ids"
                ]
            ]

            if not outs:

                move = "HOLD"

            else:

                move = (
                    ", ".join(outs)
                    + " -> "
                    + ", ".join(ins)
                )

            print(
                f"  GW{gw}: "
                f"FT {action['ft_before']} | "
                f"{move} | "
                f"next FT={action['ft_next']} | "
                f"bank={action['bank_after']/10:.1f}"
            )

    else:

        print(
            "  unavailable: "
            + candidate.get(
                "transfer_rollout_error",
                "unknown error",
            )
        )


print_candidate_plan(
    "BEST OVERALL",
    best,
)


if (
    best_preferred is not None
    and best_preferred is not best
):

    print_candidate_plan(
        "BEST WITH JOAO + GABRIEL",
        best_preferred,
    )


print()
print(
    "Full JSON:",
    OUTPUT_JSON,
)
print(
    "=== END ==="
)
