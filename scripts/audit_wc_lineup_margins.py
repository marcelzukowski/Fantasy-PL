from __future__ import annotations

import json
import math
import statistics
from itertools import combinations, permutations
from pathlib import Path

from fpl_engine.decision.autosubs import evaluate_autosub_lineup
from fpl_engine.decision.projection_adapter import adapt_player_projections

ROOT = Path.cwd()
RUN_ROOT = ROOT / "scratch" / "book003" / "current_market_shadow" / "2026-27"
RUN_MAP = ROOT / "scratch" / "decision" / "final_wc_256_run_map.txt"
PLAN_PATH = ROOT / "scratch" / "decision" / "final_wc_playing_plan.json"


def rows(raw):
    if isinstance(raw, list):
        return raw
    for key in ("rows", "data", "records", "minutes", "fixtures"):
        if isinstance(raw.get(key), list):
            return raw[key]
    raise RuntimeError("Unsupported JSON structure")


def gw_ev(projection, gw):
    for row in projection.gameweeks:
        if int(row.gameweek) == gw:
            return float(row.expected_points)
    return 0.0


def load_availability(run_path):
    minute_rows = rows(json.loads(
        (run_path / "minutes.json").read_text(encoding="utf-8")
    ))
    fixture_rows = rows(json.loads(
        (run_path / "fixture_horizon.json").read_text(encoding="utf-8")
    ))

    fixture_to_gw = {}

    for row in fixture_rows:
        gw = row.get("gameweek") or row.get("target_gameweek") or row.get("event")
        if gw is None:
            continue

        for key in ("fixture_id", "canonical_fixture_id", "id"):
            if row.get(key) is not None:
                fixture_to_gw[str(row[key])] = int(gw)

    grouped = {}

    for row in minute_rows:
        pid = row.get("player_id")
        p = row.get("p_appearance")

        if pid is None or p is None:
            continue

        gw = row.get("gameweek") or row.get("target_gameweek")

        if gw is None and row.get("fixture_id") is not None:
            gw = fixture_to_gw.get(str(row["fixture_id"]))

        if gw is None:
            continue

        grouped.setdefault((str(pid), int(gw)), []).append(float(p))

    return {
        key: 1.0 - math.prod(1.0 - x for x in values)
        for key, values in grouped.items()
    }


run_ids = [
    line.split("run=", 1)[1].strip()
    for line in RUN_MAP.read_text(encoding="utf-8-sig").splitlines()
    if "run=" in line
]

runs = []

for run_id in run_ids:
    path = RUN_ROOT / run_id

    projections = adapt_player_projections(json.loads(
        (path / "player_projections.json").read_text(encoding="utf-8")
    ))

    runs.append({
        "path": path,
        "projections": {p.player_id: p for p in projections},
        "availability": load_availability(path),
    })

players = json.loads(
    (runs[0]["path"] / "current_players.json").read_text(encoding="utf-8")
)

meta = {str(p["player_id"]): p for p in players}
name = {pid: row["display_name"] for pid, row in meta.items()}
pos = {pid: row["position"] for pid, row in meta.items()}

plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

cand = next(
    c for c in plan["candidates"]
    if "BASE_CAND5" in c["labels"]
)

squad = set(cand["player_ids"])


def mean_ev(pid, gw):
    return statistics.mean(
        gw_ev(run["projections"][pid], gw)
        for run in runs
    )


def mean_papp(pid, gw):
    vals = [
        run["availability"][(pid, gw)]
        for run in runs
        if (pid, gw) in run["availability"]
    ]

    if vals:
        return statistics.mean(vals)

    if abs(mean_ev(pid, gw)) < 1e-9:
        return 0.0

    raise RuntimeError(f"Missing p_app: {name[pid]} GW{gw}")


def total_value(result):
    for attr in (
        "total_expected_points",
        "total_ev",
        "expected_total",
        "total",
    ):
        if hasattr(result, attr):
            return float(getattr(result, attr))

    d = result.__dict__

    for key, value in d.items():
        if isinstance(value, (int, float)) and "total" in key.lower():
            return float(value)

    raise RuntimeError(f"Cannot extract total from {d.keys()}")


def best_with_forced(gw, forced_ids):
    ev = {pid: mean_ev(pid, gw) for pid in squad}
    papp = {pid: mean_papp(pid, gw) for pid in squad}

    gks = [pid for pid in squad if pos[pid] == "GK"]
    outfield = [pid for pid in squad if pos[pid] != "GK"]

    best = None

    for starter_gk in gks:
        bench_gk = next(pid for pid in gks if pid != starter_gk)

        for starters10 in combinations(outfield, 10):
            starters = {starter_gk, *starters10}

            if not forced_ids.issubset(starters):
                continue

            counts = {
                p: sum(pos[pid] == p for pid in starters)
                for p in ("DEF", "MID", "FWD")
            }

            if not (
                3 <= counts["DEF"] <= 5
                and 2 <= counts["MID"] <= 5
                and 1 <= counts["FWD"] <= 3
            ):
                continue

            bench_outfield = list(set(outfield) - set(starters10))

            for order in permutations(bench_outfield):
                result = evaluate_autosub_lineup(
                    gameweek=gw,
                    starter_ids=tuple(starters),
                    bench_gk_id=bench_gk,
                    bench_outfield_ids=order,
                    positions=pos,
                    expected_points=ev,
                    p_appearance=papp,
                )

                score = total_value(result)

                if best is None or score > best:
                    best = score

    return best


def resolve(display):
    matches = [
        pid for pid in squad
        if name[pid] == display
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Cannot resolve {display}: {matches}")
    return matches[0]


HAALAND = resolve("Haaland")
PALMER = resolve("Palmer")


weekly = {
    int(row["gameweek"]): row
    for row in cand["weekly"]
}


for gw in (5, 6):
    row = weekly[gw]

    starters = set(row["starter_ids"])
    bench_order = (
        [row["bench_gk_id"]]
        + row["bench_outfield_ids"]
    )

    print()
    print("=" * 58)
    print(f"GW{gw} | base autosub score = {row['ensemble_score']:.3f}")
    print("=" * 58)
    print(f"{'ROLE':<8} {'POS':<4} {'PLAYER':<20} {'EV':>6} {'P_APP':>7}")

    ordered = sorted(
        squad,
        key=lambda pid: mean_ev(pid, gw),
        reverse=True,
    )

    for pid in ordered:
        if pid in starters:
            role = "START"
        elif pid == row["bench_gk_id"]:
            role = "BGK"
        else:
            role = f"B{row['bench_outfield_ids'].index(pid)+1}"

        print(
            f"{role:<8} "
            f"{pos[pid]:<4} "
            f"{name[pid]:<20} "
            f"{mean_ev(pid, gw):>6.2f} "
            f"{mean_papp(pid, gw):>7.3f}"
        )

    print()
    forced_h = best_with_forced(gw, {HAALAND})

    print(
        f"Force Haaland START: "
        f"{forced_h:.3f} | "
        f"delta {forced_h-row['ensemble_score']:+.3f}"
    )

    if gw == 5:
        forced_p = best_with_forced(gw, {PALMER})
        forced_both = best_with_forced(gw, {HAALAND, PALMER})

        print(
            f"Force Palmer START : "
            f"{forced_p:.3f} | "
            f"delta {forced_p-row['ensemble_score']:+.3f}"
        )

        print(
            f"Force H+P START    : "
            f"{forced_both:.3f} | "
            f"delta {forced_both-row['ensemble_score']:+.3f}"
        )

print()
print("=== END ===")
