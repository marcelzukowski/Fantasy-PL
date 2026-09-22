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

OUTPUT_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "calafiori_konsa_rotation.json"
)

GWS = tuple(range(4, 10))

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
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


def rows(raw):

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
        "Unsupported JSON structure"
    )


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


def price_tenths(row):

    value = float(
        row["current_price"]
    )

    if value < 20:
        return int(round(value * 10))

    return int(round(value))


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

    for key in (
        "total_expected_points",
        "total_ev",
        "expected_total",
        "total",
    ):

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

    starters = None
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

                starters = tuple(ids)

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
        starters is None
        or bench_gk is None
        or bench_outfield is None
    ):

        raise RuntimeError(
            "Could not extract lineup "
            f"from result keys={list(data)}"
        )

    return {
        "starter_ids": starters,
        "bench_gk_id": bench_gk,
        "bench_outfield_ids": (
            bench_outfield
        ),
        "total": result_total(result),
    }


def optimize_lineup(
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
                "Unsupported optimizer parameter: "
                f"{name}"
            )

    result = optimize_autosub_lineup(
        **kwargs
    )

    return extract_lineup(
        result,
        set(squad_ids),
    )


# ============================================================
# LOAD RUNS
# ============================================================

run_ids = [
    line.split(
        "run=",
        1,
    )[1].strip()

    for line in RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    if "run=" in line
]

if len(run_ids) != 4:

    raise RuntimeError(
        f"Expected 4 runs, got {run_ids}"
    )


runs = []

for run_id in run_ids:

    path = RUN_ROOT / run_id

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

    runs.append(
        {
            "id": run_id,
            "path": path,
            "projections": {
                p.player_id: p
                for p in projections
            },
        }
    )


reference = runs[0]


player_rows = json.loads(
    (
        reference["path"]
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)


metadata = {
    str(row["player_id"]): row
    for row in player_rows
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
    pid: price_tenths(row)
    for pid, row
    in metadata.items()
}


# ============================================================
# AVAILABILITY
# ============================================================

def load_availability(run):

    path = run["path"]

    minute_rows = rows(
        json.loads(
            (
                path
                / "minutes.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_rows = rows(
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

            value = row.get(key)

            if value is not None:

                fixture_to_gw[
                    str(value)
                ] = int(gw)

    grouped = {}

    for row in minute_rows:

        pid = row.get(
            "player_id"
        )

        p = row.get(
            "p_appearance"
        )

        if pid is None or p is None:
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

        grouped.setdefault(
            (
                str(pid),
                int(gw),
            ),
            [],
        ).append(
            float(p)
        )

    return {
        key:
            1.0
            - math.prod(
                1.0 - p
                for p in values
            )

        for key, values
        in grouped.items()
    }


availability_by_run = [
    load_availability(run)
    for run in runs
]


def mean_papp(
    pid,
    gw,
):

    values = [
        availability[
            (pid, gw)
        ]

        for availability
        in availability_by_run

        if (
            pid,
            gw,
        ) in availability
    ]

    if values:

        return statistics.mean(
            values
        )

    ev = statistics.mean(
        gw_ev(
            run["projections"][pid],
            gw,
        )
        for run in runs
    )

    if abs(ev) < 1e-9:
        return 0.0

    raise RuntimeError(
        f"Missing availability "
        f"{names[pid]} GW{gw}"
    )


# ============================================================
# ENSEMBLE PROJECTIONS
# ============================================================

def mean_projection_map():

    output = {}

    for pid, base in (
        reference[
            "projections"
        ].items()
    ):

        new_gameweeks = []

        for base_row in (
            base.gameweeks
        ):

            gw = int(
                base_row.gameweek
            )

            values = [
                gw_ev(
                    run[
                        "projections"
                    ][pid],
                    gw,
                )

                for run in runs
            ]

            new_gameweeks.append(
                replace(
                    base_row,
                    expected_points=(
                        statistics.mean(
                            values
                        )
                    ),
                )
            )

        output[pid] = replace(
            base,
            gameweeks=tuple(
                new_gameweeks
            ),
        )

    return output


mean_map = mean_projection_map()


def rebuild_horizon(
    projection,
):

    selected = []

    rows_by_gw = {
        int(row.gameweek): row
        for row in projection.gameweeks
    }

    for gw in GWS:

        selected.append(
            rows_by_gw[gw]
        )

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
        in enumerate(
            selected
        )
    )

    return replace(
        projection,
        current_gameweek=4,
        gameweeks=tuple(
            selected
        ),
        horizon_3=replace(
            projection.horizon_3,
            first_gameweek=4,
            last_gameweek=6,
            raw_expected_points=raw3,
            weighted_expected_points=(
                weighted3
            ),
            gameweeks=3,
        ),
        horizon_6=replace(
            projection.horizon_6,
            first_gameweek=4,
            last_gameweek=9,
            raw_expected_points=raw6,
            weighted_expected_points=(
                weighted6
            ),
            gameweeks=6,
        ),
    )


mean6 = {
    pid: rebuild_horizon(
        projection
    )

    for pid, projection
    in mean_map.items()
}


# ============================================================
# RESOLVE PLAYERS
# ============================================================

def resolve(
    display_name,
    *,
    position=None,
    price=None,
):

    matches = [
        pid
        for pid, name
        in names.items()
        if norm(name)
        == norm(display_name)
    ]

    if position is not None:

        matches = [
            pid
            for pid in matches
            if positions[pid]
            == position
        ]

    if price is not None:

        matches = [
            pid
            for pid in matches
            if prices[pid]
            == price
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
)

BRUNO = resolve(
    "B.Fernandes",
    position="MID",
)

GROSS = resolve(
    "Groß",
    position="MID",
)

SZOBOSZLAI = resolve(
    "Szoboszlai",
    position="MID",
)

CALAFIORI = resolve(
    "Calafiori",
    position="DEF",
    price=58,
)

KONSA = resolve(
    "Konsa",
    position="DEF",
    price=45,
)


CORE = {
    HAALAND,
    BRUNO,
    GROSS,
    SZOBOSZLAI,
}


# ============================================================
# CURRENT SQUAD / SELLING VALUES
# ============================================================

known_ids = set(
    metadata
)


def collect_ids(value):

    output = set()

    if isinstance(value, str):

        if value in known_ids:
            output.add(value)

    elif isinstance(value, dict):

        for child in value.values():

            output.update(
                collect_ids(
                    child
                )
            )

    elif isinstance(value, list):

        for child in value:

            output.update(
                collect_ids(
                    child
                )
            )

    return output


current_ids = collect_ids(
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


selling_prices = {
    pid:
        selling_by_name[
            norm(
                names[pid]
            )
        ]

    for pid in current_ids
}


# ============================================================
# BASE CAND5
# ============================================================

plan_data = json.loads(
    PLAN_PATH.read_text(
        encoding="utf-8"
    )
)


base = next(
    candidate
    for candidate
    in plan_data["candidates"]
    if "BASE_CAND5"
    in candidate["labels"]
)


base_ids = frozenset(
    base["player_ids"]
)


base_weekly = {
    int(row["gameweek"]): row
    for row in base["weekly"]
}


base_world_totals = list(
    base["world_totals"]
)


base_mean = statistics.mean(
    base_world_totals
)


base_worst = min(
    base_world_totals
)


# ============================================================
# CREATE FORCED VARIANTS
# ============================================================

def build_variant(
    label,
    target_id,
):

    plan = optimize_unlimited_squad(
        player_rows=player_rows,
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
            CORE
            | {
                target_id,
            }
        ),
    )

    return {
        "label": label,
        "target_id": target_id,
        "player_ids": frozenset(
            plan.player_ids
        ),
        "bank": int(
            plan.remaining_budget_tenths
        ),
        "optimizer_xi_ev": float(
            plan.weighted_xi_ev
        ),
    }


variants = [
    build_variant(
        "CALAFIORI_CORE",
        CALAFIORI,
    ),
    build_variant(
        "KONSA_CORE",
        KONSA,
    ),
]


# ============================================================
# SCORE EACH VARIANT
# ============================================================

for variant in variants:

    squad = variant[
        "player_ids"
    ]

    weekly = []

    world_totals = [
        0.0
        for _ in runs
    ]

    for offset, gw in enumerate(
        GWS
    ):

        expected_points = {
            pid:
                gw_ev(
                    mean6[pid],
                    gw,
                )

            for pid in squad
        }

        papp = {
            pid:
                mean_papp(
                    pid,
                    gw,
                )

            for pid in squad
        }

        lineup = optimize_lineup(
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
                pid:
                    gw_ev(
                        run[
                            "projections"
                        ][pid],
                        gw,
                    )

                for pid in squad
            }

            availability = (
                availability_by_run[
                    run_index
                ]
            )

            run_papp = {}

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
                        "Missing world "
                        "availability: "
                        f"{names[pid]} "
                        f"GW{gw}"
                    )

            result = (
                evaluate_autosub_lineup(
                    gameweek=gw,
                    starter_ids=(
                        lineup[
                            "starter_ids"
                        ]
                    ),
                    bench_gk_id=(
                        lineup[
                            "bench_gk_id"
                        ]
                    ),
                    bench_outfield_ids=(
                        lineup[
                            "bench_outfield_ids"
                        ]
                    ),
                    positions=positions,
                    expected_points=run_ev,
                    p_appearance=run_papp,
                )
            )

            score = result_total(
                result
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

    variant[
        "weekly"
    ] = weekly

    variant[
        "world_totals"
    ] = (
        world_totals
    )

    variant[
        "mean"
    ] = statistics.mean(
        world_totals
    )

    variant[
        "worst"
    ] = min(
        world_totals
    )

    variant[
        "spread"
    ] = (
        max(world_totals)
        - min(world_totals)
    )


# ============================================================
# REPORT
# ============================================================

print()
print(
    "============================================"
)
print(
    "CALAFIORI / KONSA ROTATION TEST"
)
print(
    "same 4 x 256 worlds | GW4-GW9"
)
print(
    "============================================"
)

print()
print(
    f"BASE_CAND5      "
    f"mean={base_mean:.2f} "
    f"worst={base_worst:.2f} "
    f"bank={base['bank']/10:.1f}"
)


for variant in variants:

    target = (
        variant[
            "target_id"
        ]
    )

    print()
    print(
        "--------------------------------------------"
    )

    print(
        variant[
            "label"
        ]
    )

    print(
        f"mean={variant['mean']:.2f} "
        f"({variant['mean']-base_mean:+.2f}) | "
        f"worst={variant['worst']:.2f} "
        f"({variant['worst']-base_worst:+.2f}) | "
        f"spread={variant['spread']:.2f} | "
        f"bank={variant['bank']/10:.1f}"
    )

    squad_out = sorted(
        base_ids
        - variant[
            "player_ids"
        ],
        key=lambda pid: names[pid],
    )

    squad_in = sorted(
        variant[
            "player_ids"
        ]
        - base_ids,
        key=lambda pid: names[pid],
    )

    print(
        "SQUAD OUT:",
        ", ".join(
            names[pid]
            for pid in squad_out
        )
        or "-"
    )

    print(
        "SQUAD IN :",
        ", ".join(
            names[pid]
            for pid in squad_in
        )
        or "-"
    )

    target_start_count = 0

    print()
    print(
        "GW ROTATION"
    )

    weekly_map = {
        int(row["gameweek"]): row
        for row in variant[
            "weekly"
        ]
    }

    for gw in GWS:

        row = weekly_map[gw]

        starter_ids = set(
            row[
                "starter_ids"
            ]
        )

        base_starters = set(
            base_weekly[
                gw
            ][
                "starter_ids"
            ]
        )

        if target in starter_ids:

            target_role = "START"
            target_start_count += 1

        elif (
            target
            == row[
                "bench_gk_id"
            ]
        ):

            target_role = "BGK"

        else:

            bench = row[
                "bench_outfield_ids"
            ]

            target_role = (
                "B"
                + str(
                    bench.index(
                        target
                    )
                    + 1
                )
            )

        xi_in = sorted(
            starter_ids
            - base_starters,
            key=lambda pid: names[pid],
        )

        xi_out = sorted(
            base_starters
            - starter_ids,
            key=lambda pid: names[pid],
        )

        base_score = (
            base_weekly[
                gw
            ][
                "ensemble_score"
            ]
        )

        target_ev = gw_ev(
            mean6[target],
            gw,
        )

        print(
            f"GW{gw} "
            f"{names[target]:<12} "
            f"{target_role:<5} "
            f"EV={target_ev:.2f} | "
            f"score={row['ensemble_score']:.2f} "
            f"vs base "
            f"{row['ensemble_score']-base_score:+.2f}"
        )

        if xi_in or xi_out:

            print(
                "    XI +:",
                ", ".join(
                    names[pid]
                    for pid in xi_in
                )
                or "-"
            )

            print(
                "    XI -:",
                ", ".join(
                    names[pid]
                    for pid in xi_out
                )
                or "-"
            )

    print()
    print(
        f"{names[target]} starts: "
        f"{target_start_count}/6"
    )

    defender_starts = Counter()

    for row in variant[
        "weekly"
    ]:

        defender_starts.update(
            pid
            for pid
            in row[
                "starter_ids"
            ]
            if positions[pid]
            == "DEF"
        )

    print(
        "DEF START COUNTS:"
    )

    for pid in sorted(
        (
            pid
            for pid in variant[
                "player_ids"
            ]
            if positions[pid]
            == "DEF"
        ),
        key=lambda pid: (
            -defender_starts[pid],
            names[pid],
        ),
    ):

        print(
            f"  {names[pid]:<18} "
            f"{defender_starts[pid]}/6"
        )


# ============================================================
# SIMPLE RANKING
# ============================================================

ranking = [
    {
        "label": "BASE_CAND5",
        "mean": base_mean,
        "worst": base_worst,
    }
]

ranking.extend(
    {
        "label": v["label"],
        "mean": v["mean"],
        "worst": v["worst"],
    }
    for v in variants
)

ranking.sort(
    key=lambda row: (
        row["worst"],
        row["mean"],
    ),
    reverse=True,
)

print()
print(
    "============================================"
)
print(
    "ROBUST RANKING"
)
print(
    "============================================"
)

for i, row in enumerate(
    ranking,
    start=1,
):

    print(
        f"{i}. "
        f"{row['label']:<18} "
        f"mean={row['mean']:.2f} "
        f"worst={row['worst']:.2f}"
    )


# ============================================================
# SAVE
# ============================================================

def json_default(value):

    if isinstance(
        value,
        (set, frozenset),
    ):

        return sorted(value)

    if is_dataclass(value):
        return asdict(value)

    raise TypeError(
        str(
            type(value)
        )
    )


OUTPUT_PATH.write_text(
    json.dumps(
        {
            "base_mean": (
                base_mean
            ),
            "base_worst": (
                base_worst
            ),
            "variants": (
                variants
            ),
        },
        indent=2,
        ensure_ascii=False,
        default=json_default,
    ),
    encoding="utf-8",
)

print()
print(
    "Full JSON:",
    OUTPUT_PATH,
)

print(
    "=== END ==="
)
