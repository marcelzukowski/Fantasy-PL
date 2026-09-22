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


def fixed_path(
    report: Path,
):

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
            f"FIXED path missing: "
            f"{report}"
        )

    path = Path(
        match.group(1).strip()
    )

    if not path.exists():
        raise RuntimeError(
            f"run path missing: {path}"
        )

    return path


V1_RUNS = {
    seed: fixed_path(
        ROOT
        / "scratch"
        / "decision"
        / f"captain_xg_ab_report_seed{seed}.txt"
    )
    for seed in SEEDS
}


V21_RUNS = {
    seed: fixed_path(
        ROOT
        / "scratch"
        / "decision"
        / f"minutes_v21_fair_report_seed{seed}.txt"
    )
    for seed in SEEDS
}


def rows(
    path: Path,
):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if isinstance(
        raw,
        list,
    ):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "projections",
        "minutes",
        "fixtures",
    ):

        value = raw.get(
            key
        )

        if isinstance(
            value,
            list,
        ):
            return value

    raise RuntimeError(
        f"cannot resolve rows: {path}"
    )


# ============================================================
# Actual WC XI / robust optimizer base squad
# ============================================================

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
    if "BASE_CAND5"
    in row["labels"]
)

base_ids = set(
    base["player_ids"]
)


players = rows(
    V1_RUNS[42]
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


def resolve(
    name,
):

    matches = [
        pid
        for pid in base_ids
        if (
            pid in by_id
            and by_id[pid][
                "display_name"
            ] == name
        )
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"{name}: "
            f"matches={matches}"
        )

    return matches[0]


XI = tuple(
    resolve(name)
    for name in XI_NAMES
)


CAPTAIN_POOL = tuple(
    pid
    for pid in XI
    if by_id[pid]["position"]
    in {
        "MID",
        "FWD",
    }
)


# ============================================================
# Artifact helpers
# ============================================================

def gw_of(
    fixture,
):

    value = (
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

    if value is None:
        raise RuntimeError(
            "fixture GW missing"
        )

    return int(
        value
    )


def projection_ev(
    row,
):

    for key in (
        "ev_next_1",
        "expected_points_next_1",
        "weighted_ev_next_1",
    ):

        if key in row:
            return float(
                row[key]
            )

    raise RuntimeError(
        "projection EV field missing"
    )


def world_data(
    run,
):

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

    minute_rows = rows(
        run
        / "minutes.json"
    )

    gw4_minutes = {}

    for row in minute_rows:

        fixture_id = str(
            row["fixture_id"]
        )

        fixture = fixtures.get(
            fixture_id
        )

        if fixture is None:
            continue

        if gw_of(
            fixture
        ) != 4:
            continue

        gw4_minutes[
            str(row["player_id"])
        ] = row

    result = {}

    for pid in XI:

        if pid not in projections:
            raise RuntimeError(
                f"projection missing: {pid}"
            )

        if pid not in gw4_minutes:
            raise RuntimeError(
                f"minutes missing: {pid}"
            )

        minute = (
            gw4_minutes[pid]
        )

        result[pid] = {
            "ev": projection_ev(
                projections[pid]
            ),
            "p_app": float(
                minute[
                    "p_appearance"
                ]
            ),
            "p_start": float(
                minute[
                    "p_start"
                ]
            ),
            "minutes": float(
                minute[
                    "expected_minutes"
                ]
            ),
        }

    return result


V1 = {
    seed: world_data(
        V1_RUNS[seed]
    )
    for seed in SEEDS
}

V21 = {
    seed: world_data(
        V21_RUNS[seed]
    )
    for seed in SEEDS
}


# ============================================================
# Captaincy
# ============================================================

def pair_bonus(
    data,
    captain,
    vice,
):

    c = data[captain]
    v = data[vice]

    return (
        c["ev"]
        + (
            1.0
            - c["p_app"]
        )
        * v["ev"]
    )


def robust_pairs(
    worlds,
):

    result = []

    for captain in CAPTAIN_POOL:

        for vice in CAPTAIN_POOL:

            if (
                captain
                == vice
            ):
                continue

            values = [
                pair_bonus(
                    worlds[seed],
                    captain,
                    vice,
                )
                for seed in SEEDS
            ]

            result.append(
                {
                    "captain": captain,
                    "vice": vice,
                    "mean": mean(
                        values
                    ),
                    "worst": min(
                        values
                    ),
                    "sd": pstdev(
                        values
                    ),
                    "values": values,
                }
            )

    result.sort(
        key=lambda row: (
            -row["mean"],
            -row["worst"],
            row["sd"],
            row["captain"],
            row["vice"],
        )
    )

    return result


v1_pairs = robust_pairs(
    V1
)

v21_pairs = robust_pairs(
    V21
)


# ============================================================
# Report
# ============================================================

lines = []

lines.append(
    "============================================================"
)
lines.append(
    "MINUTES V1 vs V2.1 | FAIR CALIBRATED PRE-DEADLINE GW4"
)
lines.append(
    "============================================================"
)

lines.append(
    "same snapshots | fixed current xG | "
    "4 x 256 sims"
)

lines.append("")

lines.append(
    f"{'PLAYER':<18}"
    f"{'V1 MIN':>8}"
    f"{'V21 MIN':>9}"
    f"{'V1 APP':>9}"
    f"{'V21 APP':>9}"
    f"{'V1 EV':>8}"
    f"{'V21 EV':>9}"
    f"{'D EV':>8}"
)


for pid in CAPTAIN_POOL:

    name = by_id[
        pid
    ]["display_name"]

    v1_min = mean(
        V1[seed][pid]["minutes"]
        for seed in SEEDS
    )

    v21_min = mean(
        V21[seed][pid]["minutes"]
        for seed in SEEDS
    )

    v1_app = mean(
        V1[seed][pid]["p_app"]
        for seed in SEEDS
    )

    v21_app = mean(
        V21[seed][pid]["p_app"]
        for seed in SEEDS
    )

    v1_ev = mean(
        V1[seed][pid]["ev"]
        for seed in SEEDS
    )

    v21_ev = mean(
        V21[seed][pid]["ev"]
        for seed in SEEDS
    )

    lines.append(
        f"{name:<18}"
        f"{v1_min:>8.2f}"
        f"{v21_min:>9.2f}"
        f"{v1_app:>9.3f}"
        f"{v21_app:>9.3f}"
        f"{v1_ev:>8.3f}"
        f"{v21_ev:>9.3f}"
        f"{v21_ev-v1_ev:>+8.3f}"
    )


lines.append("")
lines.append(
    "=== HAALAND BY WORLD ==="
)

lines.append(
    f"{'SEED':<10}"
    f"{'V1 APP':>9}"
    f"{'V21 APP':>9}"
    f"{'V1 START':>10}"
    f"{'V21 START':>11}"
    f"{'V1 MIN':>9}"
    f"{'V21 MIN':>10}"
    f"{'V1 EV':>8}"
    f"{'V21 EV':>9}"
)


haaland = resolve(
    "Haaland"
)

for seed in SEEDS:

    a = V1[seed][
        haaland
    ]

    b = V21[seed][
        haaland
    ]

    lines.append(
        f"{seed:<10}"
        f"{a['p_app']:>9.3f}"
        f"{b['p_app']:>9.3f}"
        f"{a['p_start']:>10.3f}"
        f"{b['p_start']:>11.3f}"
        f"{a['minutes']:>9.2f}"
        f"{b['minutes']:>10.2f}"
        f"{a['ev']:>8.3f}"
        f"{b['ev']:>9.3f}"
    )


lines.append("")
lines.append(
    "=== ROBUST CAPTAINCY ==="
)

lines.append(
    f"{'#':<4}"
    f"{'MODEL':<6}"
    f"{'CAPTAIN':<18}"
    f"{'VICE':<18}"
    f"{'MEAN':>8}"
    f"{'WORST':>8}"
    f"{'SD':>8}"
)


for rank in range(5):

    old = v1_pairs[
        rank
    ]

    new = v21_pairs[
        rank
    ]

    lines.append(
        f"{rank+1:<4}"
        f"{'V1':<6}"
        f"{by_id[old['captain']]['display_name']:<18}"
        f"{by_id[old['vice']]['display_name']:<18}"
        f"{old['mean']:>8.3f}"
        f"{old['worst']:>8.3f}"
        f"{old['sd']:>8.3f}"
    )

    lines.append(
        f"{'':<4}"
        f"{'V2.1':<6}"
        f"{by_id[new['captain']]['display_name']:<18}"
        f"{by_id[new['vice']]['display_name']:<18}"
        f"{new['mean']:>8.3f}"
        f"{new['worst']:>8.3f}"
        f"{new['sd']:>8.3f}"
    )


lines.append("")

old = v1_pairs[0]
new = v21_pairs[0]

lines.append(
    "V1 WINNER   : "
    f"C={by_id[old['captain']]['display_name']} "
    f"VC={by_id[old['vice']]['display_name']} "
    f"mean={old['mean']:.3f}"
)

lines.append(
    "V2.1 WINNER : "
    f"C={by_id[new['captain']]['display_name']} "
    f"VC={by_id[new['vice']]['display_name']} "
    f"mean={new['mean']:.3f}"
)

lines.append("")
lines.append(
    "=== END ==="
)


report = "\n".join(
    lines
)

path = (
    ROOT
    / "scratch"
    / "decision"
    / "minutes_v21_fair_gw4_ab.txt"
)

path.write_text(
    report + "\n",
    encoding="utf-8",
)

print(
    report
)
