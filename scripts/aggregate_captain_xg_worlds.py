from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean, pstdev


ROOT = Path.cwd()

SEEDS = (
    42,
    202627,
    606,
    91991,
)

REPORTS = {
    seed: (
        ROOT
        / "scratch"
        / "decision"
        / f"captain_xg_ab_report_seed{seed}.txt"
    )
    for seed in SEEDS
}


# ------------------------------------------------------------
# Locate FIXED run from each report
# ------------------------------------------------------------

fixed_runs = {}

for seed, report in REPORTS.items():

    text = report.read_text(
        encoding="utf-8"
    )

    match = re.search(
        r"^FIXED\s*:\s*(.+)$",
        text,
        flags=re.MULTILINE,
    )

    if not match:
        raise RuntimeError(
            f"FIXED path missing for seed {seed}"
        )

    fixed_runs[seed] = Path(
        match.group(1).strip()
    )


def rows(path):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(raw, list):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "projections",
        "fixtures",
        "minutes",
    ):

        value = raw.get(key)

        if isinstance(value, list):
            return value

    raise RuntimeError(
        f"cannot find rows in {path}"
    )


# ------------------------------------------------------------
# Actual WC XI
# ------------------------------------------------------------

plan = json.loads(
    (
        ROOT
        / "scratch"
        / "decision"
        / "final_wc_playing_plan.json"
    ).read_text(
        encoding="utf-8"
    )
)

base = next(
    row
    for row in plan["candidates"]
    if "BASE_CAND5" in row["labels"]
)

base_ids = set(
    base["player_ids"]
)

reference = fixed_runs[42]

players = rows(
    reference
    / "current_players.json"
)

by_id = {
    str(row["player_id"]): row
    for row in players
}

XI_NAMES = (
    "Sels",
    "Maatsen",
    "Justin",
    "De Cuyper",
    "Groß",
    "Tavernier",
    "B.Fernandes",
    "Szoboszlai",
    "Palmer",
    "Calvert-Lewin",
    "Haaland",
)


def resolve(name):

    matches = [
        pid
        for pid in base_ids
        if (
            pid in by_id
            and by_id[pid]["display_name"] == name
        )
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"{name}: {matches}"
        )

    return matches[0]


xi = tuple(
    resolve(name)
    for name in XI_NAMES
)

pool = tuple(
    pid
    for pid in xi
    if by_id[pid]["position"]
    in {"MID", "FWD"}
)


# ------------------------------------------------------------
# Extract EV + p_app from every world
# ------------------------------------------------------------

world_ev = {
    pid: []
    for pid in pool
}

world_papp = {
    pid: []
    for pid in pool
}


def ev1(row):

    for key in (
        "ev_next_1",
        "expected_points_next_1",
        "weighted_ev_next_1",
    ):

        if key in row:
            return float(row[key])

    raise RuntimeError(
        f"EV field missing: {sorted(row)}"
    )


for seed, run in fixed_runs.items():

    projections = {
        str(row["player_id"]): row
        for row in rows(
            run
            / "player_projections.json"
        )
    }

    fixtures = {
        str(row["fixture_id"]): row
        for row in rows(
            run
            / "fixture_horizon.json"
        )
    }

    minutes = rows(
        run
        / "minutes.json"
    )

    for pid in pool:

        world_ev[pid].append(
            ev1(
                projections[pid]
            )
        )

        candidates = []

        for row in minutes:

            if str(
                row.get("player_id")
            ) != pid:
                continue

            fixture = fixtures[
                str(row["fixture_id"])
            ]

            gw = (
                fixture.get(
                    "target_gameweek"
                )
                or fixture.get(
                    "gameweek"
                )
                or fixture.get(
                    "event"
                )
            )

            if int(gw) == 4:
                candidates.append(row)

        if len(candidates) != 1:

            raise RuntimeError(
                f"{seed} {pid}: "
                f"GW4 minute rows="
                f"{len(candidates)}"
            )

        world_papp[pid].append(
            float(
                candidates[0][
                    "p_appearance"
                ]
            )
        )


# ------------------------------------------------------------
# Robust statistics
# ------------------------------------------------------------

stats = {}

for pid in pool:

    evs = world_ev[pid]
    apps = world_papp[pid]

    stats[pid] = {
        "ev_mean": mean(evs),
        "ev_sd": pstdev(evs),
        "ev_min": min(evs),
        "ev_max": max(evs),
        "p_app": mean(apps),
    }


pairs = []

for captain in pool:

    for vice in pool:

        if captain == vice:
            continue

        bonuses = []

        for i in range(
            len(SEEDS)
        ):

            bonus = (
                world_ev[captain][i]
                + (
                    1.0
                    - world_papp[captain][i]
                )
                * world_ev[vice][i]
            )

            bonuses.append(
                bonus
            )

        pairs.append(
            (
                mean(bonuses),
                min(bonuses),
                pstdev(bonuses),
                captain,
                vice,
            )
        )


pairs.sort(
    key=lambda row: (
        -row[0],
        -row[1],
        row[2],
        row[3],
        row[4],
    )
)


# ------------------------------------------------------------
# Report
# ------------------------------------------------------------

print()
print(
    "============================================"
)
print(
    "ROBUST PLAYER EV | FIXED xG | GW4"
)
print(
    "============================================"
)

print(
    f"{'PLAYER':<18}"
    f"{'MEAN':>8}"
    f"{'SD':>8}"
    f"{'WORST':>8}"
    f"{'BEST':>8}"
    f"{'P_APP':>8}"
)

ordered = sorted(
    pool,
    key=lambda pid: (
        -stats[pid]["ev_mean"],
        pid,
    )
)

for pid in ordered:

    s = stats[pid]

    print(
        f"{by_id[pid]['display_name']:<18}"
        f"{s['ev_mean']:>8.3f}"
        f"{s['ev_sd']:>8.3f}"
        f"{s['ev_min']:>8.3f}"
        f"{s['ev_max']:>8.3f}"
        f"{s['p_app']:>8.3f}"
    )


print()
print(
    "============================================"
)
print(
    "TOP 10 ROBUST C/VC PAIRS"
)
print(
    "============================================"
)

print(
    f"{'#':<4}"
    f"{'CAPTAIN':<18}"
    f"{'VICE':<18}"
    f"{'MEAN':>8}"
    f"{'WORST':>8}"
    f"{'SD':>8}"
)

for rank, (
    avg,
    worst,
    sd,
    captain,
    vice,
) in enumerate(
    pairs[:10],
    start=1,
):

    print(
        f"{rank:<4}"
        f"{by_id[captain]['display_name']:<18}"
        f"{by_id[vice]['display_name']:<18}"
        f"{avg:>8.3f}"
        f"{worst:>8.3f}"
        f"{sd:>8.3f}"
    )


winner = pairs[0]

print()
print(
    "ROBUST WINNER:"
)

print(
    f"C={by_id[winner[3]]['display_name']} | "
    f"VC={by_id[winner[4]]['display_name']} | "
    f"mean={winner[0]:.3f} | "
    f"worst={winner[1]:.3f} | "
    f"sd={winner[2]:.3f}"
)

print()
print(
    "=== END ==="
)
