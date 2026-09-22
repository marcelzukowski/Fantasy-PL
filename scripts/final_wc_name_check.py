from __future__ import annotations

import inspect
import json
import math
import statistics
import unicodedata

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

GWS = tuple(range(4, 10))

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)


def norm(value):

    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        c for c in text
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


def gw_ev(projection, gw):

    for row in projection.gameweeks:

        if int(row.gameweek) == gw:
            return float(row.expected_points)

    return 0.0


def price_tenths(row):

    value = float(
        row["current_price"]
    )

    return (
        int(round(value * 10))
        if value < 20
        else int(round(value))
    )


def object_dict(obj):

    if is_dataclass(obj):
        return asdict(obj)

    if isinstance(obj, dict):
        return obj

    return vars(obj)


def walk(value, path=""):

    if isinstance(value, dict):

        for key, child in value.items():

            p = (
                f"{path}.{key}"
                if path
                else str(key)
            )

            yield p, child
            yield from walk(child, p)

    elif isinstance(
        value,
        (list, tuple),
    ):

        for i, child in enumerate(value):

            yield from walk(
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

    for path, value in walk(data):

        if (
            isinstance(value, (int, float))
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

    for path, value in walk(data):

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
            "Cannot extract lineup"
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
    gw,
    squad,
    positions,
    ev,
    papp,
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
            kwargs[name] = tuple(squad)

        elif name == "positions":
            kwargs[name] = positions

        elif name == "expected_points":
            kwargs[name] = ev

        elif name == "p_appearance":
            kwargs[name] = papp

        elif parameter.default is inspect._empty:
            raise RuntimeError(
                f"Unsupported optimizer arg: {name}"
            )

    result = optimize_autosub_lineup(
        **kwargs
    )

    return extract_lineup(
        result,
        set(squad),
    )


# ------------------------------------------------------------
# RUNS
# ------------------------------------------------------------

run_ids = [
    line.split("run=", 1)[1].strip()
    for line in RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()
    if "run=" in line
]

runs = []

for run_id in run_ids:

    path = RUN_ROOT / run_id

    projections = adapt_player_projections(
        json.loads(
            (
                path
                / "player_projections.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    runs.append({
        "id": run_id,
        "path": path,
        "projections": {
            p.player_id: p
            for p in projections
        },
    })


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


# ------------------------------------------------------------
# AVAILABILITY
# ------------------------------------------------------------

def load_availability(run):

    minute_rows = rows(
        json.loads(
            (
                run["path"]
                / "minutes.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_rows = rows(
        json.loads(
            (
                run["path"]
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

            if row.get(key) is not None:

                fixture_to_gw[
                    str(row[key])
                ] = int(gw)

    grouped = {}

    for row in minute_rows:

        pid = row.get("player_id")
        p = row.get("p_appearance")

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
            (str(pid), int(gw)),
            [],
        ).append(float(p))

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


availability = [
    load_availability(run)
    for run in runs
]


# ------------------------------------------------------------
# MEAN PROJECTIONS
# ------------------------------------------------------------

mean_map = {}

for pid, base in (
    reference["projections"].items()
):

    new_rows = []

    for row in base.gameweeks:

        gw = int(row.gameweek)

        values = [
            gw_ev(
                run["projections"][pid],
                gw,
            )
            for run in runs
        ]

        new_rows.append(
            replace(
                row,
                expected_points=(
                    statistics.mean(values)
                ),
            )
        )

    mean_map[pid] = replace(
        base,
        gameweeks=tuple(new_rows),
    )


def rebuild(projection):

    row_map = {
        int(row.gameweek): row
        for row in projection.gameweeks
    }

    selected = [
        row_map[gw]
        for gw in GWS
    ]

    raw3 = sum(
        x.expected_points
        for x in selected[:3]
    )

    weighted3 = sum(
        WEIGHTS[i] * x.expected_points
        for i, x
        in enumerate(selected[:3])
    )

    raw6 = sum(
        x.expected_points
        for x in selected
    )

    weighted6 = sum(
        WEIGHTS[i] * x.expected_points
        for i, x
        in enumerate(selected)
    )

    return replace(
        projection,
        current_gameweek=4,
        gameweeks=tuple(selected),
        horizon_3=replace(
            projection.horizon_3,
            first_gameweek=4,
            last_gameweek=6,
            raw_expected_points=raw3,
            weighted_expected_points=weighted3,
            gameweeks=3,
        ),
        horizon_6=replace(
            projection.horizon_6,
            first_gameweek=4,
            last_gameweek=9,
            raw_expected_points=raw6,
            weighted_expected_points=weighted6,
            gameweeks=6,
        ),
    )


mean6 = {
    pid: rebuild(projection)
    for pid, projection
    in mean_map.items()
}


# ------------------------------------------------------------
# PLAYER RESOLUTION
# ------------------------------------------------------------

def resolve(
    display_name,
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

        print(
            "Resolution candidates:",
            display_name,
        )

        for pid in matches:

            print(
                names[pid],
                positions[pid],
                prices[pid] / 10,
                metadata[pid].get(
                    "team_id"
                ),
            )

        raise RuntimeError(
            f"Cannot resolve {display_name}"
        )

    return matches[0]


HAALAND = resolve(
    "Haaland",
    "FWD",
)

BRUNO = resolve(
    "B.Fernandes",
    "MID",
)

GROSS = resolve(
    "Groß",
    "MID",
)

PALMER = resolve(
    "Palmer",
    "MID",
)

SZOB = resolve(
    "Szoboszlai",
    "MID",
)

JOAO = resolve(
    "João Pedro",
    "FWD",
)

GABRIEL = resolve(
    "Gabriel",
    "DEF",
)

ROGERS = resolve(
    "Rogers",
    "MID",
)

RAYA = resolve(
    "Raya",
    "GK",
)


PROTECTED_CORE = {
    HAALAND,
    BRUNO,
    GROSS,
    PALMER,
    SZOB,
}


# ------------------------------------------------------------
# CURRENT SQUAD
# ------------------------------------------------------------

known_ids = set(metadata)


def collect_ids(value):

    result = set()

    if isinstance(value, str):

        if value in known_ids:
            result.add(value)

    elif isinstance(value, dict):

        for child in value.values():
            result |= collect_ids(child)

    elif isinstance(value, list):

        for child in value:
            result |= collect_ids(child)

    return result


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
            norm(names[pid])
        ]
    for pid in current_ids
}


# ------------------------------------------------------------
# BASE
# ------------------------------------------------------------

plan = json.loads(
    PLAN_PATH.read_text(
        encoding="utf-8"
    )
)

base = next(
    x
    for x in plan["candidates"]
    if "BASE_CAND5"
    in x["labels"]
)

base_ids = frozenset(
    base["player_ids"]
)

base_mean = statistics.mean(
    base["world_totals"]
)

base_worst = min(
    base["world_totals"]
)

base_weekly = {
    int(x["gameweek"]): x
    for x in base["weekly"]
}


# ------------------------------------------------------------
# TARGET VARIANTS
# ------------------------------------------------------------

targets = [
    ("JOAO", JOAO),
    ("GABRIEL", GABRIEL),
    ("ROGERS", ROGERS),
    ("RAYA", RAYA),
]


def build_variant(
    label,
    target,
):

    result = optimize_unlimited_squad(
        player_rows=player_rows,
        projections_by_id=mean6,
        current_player_ids=current_ids,
        selling_prices_tenths=(
            selling_prices
        ),
        bank_tenths=0,
        first_gameweek=4,
        horizon=6,
        weights=WEIGHTS,
        required_player_ids=tuple(
            PROTECTED_CORE
            | {target}
        ),
    )

    return {
        "label": label,
        "target": target,
        "player_ids": frozenset(
            result.player_ids
        ),
        "bank": int(
            result.remaining_budget_tenths
        ),
    }


variants = [
    build_variant(label, target)
    for label, target
    in targets
]


# ------------------------------------------------------------
# SCORE
# ------------------------------------------------------------

for index, variant in enumerate(
    variants,
    start=1,
):

    print(
        f"[{index}/{len(variants)}] "
        f"{variant['label']}"
    )

    squad = variant["player_ids"]

    world_totals = [
        0.0
        for _ in runs
    ]

    weekly = []

    for offset, gw in enumerate(GWS):

        ev = {
            pid:
                gw_ev(
                    mean6[pid],
                    gw,
                )
            for pid in squad
        }

        papp = {}

        for pid in squad:

            values = [
                a[(pid, gw)]
                for a in availability
                if (pid, gw) in a
            ]

            if values:

                papp[pid] = (
                    statistics.mean(values)
                )

            elif abs(ev[pid]) < 1e-9:

                papp[pid] = 0.0

            else:

                raise RuntimeError(
                    "Missing p_app: "
                    f"{names[pid]} GW{gw}"
                )

        lineup = optimize_lineup(
            gw,
            squad,
            positions,
            ev,
            papp,
        )

        world_scores = []

        for ri, run in enumerate(runs):

            world_ev = {
                pid:
                    gw_ev(
                        run[
                            "projections"
                        ][pid],
                        gw,
                    )
                for pid in squad
            }

            world_papp = {}

            for pid in squad:

                key = (pid, gw)

                if key in availability[ri]:

                    world_papp[pid] = (
                        availability[ri][key]
                    )

                elif abs(
                    world_ev[pid]
                ) < 1e-9:

                    world_papp[pid] = 0.0

                else:

                    raise RuntimeError(
                        "Missing world p_app "
                        f"{names[pid]} GW{gw}"
                    )

            score = result_total(
                evaluate_autosub_lineup(
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
                    expected_points=(
                        world_ev
                    ),
                    p_appearance=(
                        world_papp
                    ),
                )
            )

            world_scores.append(score)

            world_totals[ri] += (
                WEIGHTS[offset]
                * score
            )

        weekly.append({
            "gw": gw,
            "lineup": lineup,
            "world_scores": (
                world_scores
            ),
        })

    variant["weekly"] = weekly

    variant["mean"] = (
        statistics.mean(
            world_totals
        )
    )

    variant["worst"] = min(
        world_totals
    )

    variant["spread"] = (
        max(world_totals)
        - min(world_totals)
    )


# ------------------------------------------------------------
# REPORT
# ------------------------------------------------------------

print()
print(
    "=============================================="
)
print(
    "FINAL NAME CHECK | protected premium core"
)
print(
    "4 x 256 | GW4-GW9"
)
print(
    "=============================================="
)

print(
    f"BASE      "
    f"mean={base_mean:.2f} "
    f"worst={base_worst:.2f} "
    f"bank={base['bank']/10:.1f}"
)


for variant in variants:

    target = variant["target"]

    squad_out = sorted(
        base_ids
        - variant["player_ids"],
        key=lambda x: names[x],
    )

    squad_in = sorted(
        variant["player_ids"]
        - base_ids,
        key=lambda x: names[x],
    )

    start_count = 0
    roles = []

    for item in variant["weekly"]:

        gw = item["gw"]
        lineup = item["lineup"]

        if target in lineup[
            "starter_ids"
        ]:

            role = "S"
            start_count += 1

        elif target == lineup[
            "bench_gk_id"
        ]:

            role = "BGK"

        else:

            bench = list(
                lineup[
                    "bench_outfield_ids"
                ]
            )

            role = (
                "B"
                + str(
                    bench.index(target)
                    + 1
                )
            )

        roles.append(
            f"GW{gw}:{role}"
        )

    print()
    print(
        variant["label"]
    )

    print(
        f"mean={variant['mean']:.2f} "
        f"({variant['mean']-base_mean:+.2f}) | "
        f"worst={variant['worst']:.2f} "
        f"({variant['worst']-base_worst:+.2f}) | "
        f"spread={variant['spread']:.2f} | "
        f"bank={variant['bank']/10:.1f}"
    )

    print(
        f"{names[target]} starts: "
        f"{start_count}/6 | "
        + " ".join(roles)
    )

    print(
        "OUT:",
        ", ".join(
            names[x]
            for x in squad_out
        )
        or "-"
    )

    print(
        "IN :",
        ", ".join(
            names[x]
            for x in squad_in
        )
        or "-"
    )


ranking = [
    (
        "BASE",
        base_mean,
        base_worst,
    )
]

ranking += [
    (
        x["label"],
        x["mean"],
        x["worst"],
    )
    for x in variants
]

ranking.sort(
    key=lambda x: (
        x[2],
        x[1],
    ),
    reverse=True,
)


print()
print(
    "=============================================="
)
print(
    "RANKING"
)
print(
    "=============================================="
)

for i, (
    label,
    mean,
    worst,
) in enumerate(
    ranking,
    start=1,
):

    print(
        f"{i}. "
        f"{label:<10} "
        f"mean={mean:.2f} "
        f"worst={worst:.2f}"
    )

print()
print("=== END ===")
