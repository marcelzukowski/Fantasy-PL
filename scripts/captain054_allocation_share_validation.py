from pathlib import Path
from io import BytesIO
import json
import math
import re
import unicodedata

import pandas as pd

from fpl_engine.current_history import _receipts
from fpl_engine.data.raw_store import RawStore
from fpl_engine.models.player_talent.model import (
    CORE_PRIORS,
    PlayerTalentModel,
)


ROOT = Path(".").resolve()

PRIOR_MINUTES = float(
    PlayerTalentModel()
    .config
    .prior_minutes
)

TRANSITIONS = (
    ("2023-24", "2024-25"),
    ("2024-25", "2025-26"),
)

ALPHAS = [
    i / 20
    for i in range(21)
]

EPS = 1e-12


raw = RawStore(
    ROOT / "data" / "raw"
)

receipts = _receipts(
    raw.root
)


def norm_name(value):

    text = unicodedata.normalize(
        "NFKD",
        str(value),
    ).casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text,
    )


def strings(value):

    if isinstance(value, dict):

        for item in value.values():
            yield from strings(item)

    elif isinstance(value, list):

        for item in value:
            yield from strings(item)

    elif isinstance(value, str):

        yield value


def canonical_position(value):

    value = str(value).upper()

    return {
        "GKP": "GK",
        "GOALKEEPER": "GK",
        "DEFENDER": "DEF",
        "MIDFIELDER": "MID",
        "FORWARD": "FWD",
    }.get(
        value,
        value,
    )


def load_vaastav(season):

    manifest_path = (
        ROOT
        / "data"
        / "interim"
        / "strict"
        / season
        / "source_manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    candidates = []

    for value in strings(manifest):

        receipt = receipts.get(value)

        if receipt is None:
            continue

        try:

            body = raw.read_bytes(
                receipt
            )

            frame = pd.read_csv(
                BytesIO(body)
            )

        except Exception:
            continue


        required = {
            "element",
            "fixture",
            "minutes",
            "expected_goals",
            "position",
            "name",
            "team",
        }

        if required.issubset(
            frame.columns
        ):
            candidates.append(frame)


    if not candidates:

        raise RuntimeError(
            f"{season}: no suitable "
            f"Vaastav frame"
        )


    candidates.sort(
        key=len,
        reverse=True,
    )

    frame = candidates[0].copy()


    frame["minutes"] = pd.to_numeric(
        frame["minutes"],
        errors="coerce",
    )

    frame["expected_goals"] = (
        pd.to_numeric(
            frame["expected_goals"],
            errors="coerce",
        )
    )


    frame = frame[
        frame["minutes"].notna()
        & frame["expected_goals"].notna()
        & (frame["minutes"] > 0)
    ].copy()


    frame["player_key"] = (
        frame["name"]
        .map(norm_name)
    )

    frame["position_c"] = (
        frame["position"]
        .map(canonical_position)
    )

    frame["team_key"] = (
        frame["team"]
        .astype(str)
    )

    return frame


def build_frozen_rates(frame):

    rates = {}

    for player_key, group in (
        frame.groupby("player_key")
    ):

        position = str(
            group["position_c"].iloc[-1]
        )

        prior = float(
            CORE_PRIORS.get(
                position,
                CORE_PRIORS["MID"],
            )["npxg"]
        )

        minutes = float(
            group["minutes"].sum()
        )

        xg = float(
            group[
                "expected_goals"
            ].sum()
        )

        if minutes <= 0:
            continue


        rate = (
            xg * 90.0
            + prior * PRIOR_MINUTES
        ) / (
            minutes
            + PRIOR_MINUTES
        )


        rates[player_key] = {
            "rate": rate,
            "minutes": minutes,
            "position": position,
            "name": str(
                group["name"].iloc[-1]
            ),
        }

    return rates


def aggregate_test(
    frame,
    frozen_rates,
    alpha,
):

    grouped = (
        frame.groupby(
            [
                "team_key",
                "player_key",
                "position_c",
                "name",
            ],
            as_index=False,
        )
        .agg(
            minutes=(
                "minutes",
                "sum",
            ),
            actual_xg=(
                "expected_goals",
                "sum",
            ),
        )
    )


    rows = []

    for row in grouped.itertuples(
        index=False
    ):

        position = str(
            row.position_c
        )

        prior_rate = float(
            CORE_PRIORS.get(
                position,
                CORE_PRIORS["MID"],
            )["npxg"]
        )


        frozen = frozen_rates.get(
            row.player_key
        )


        if (
            frozen is not None
            and frozen["position"]
            == position
        ):

            source_rate = float(
                frozen["rate"]
            )

            train_minutes = float(
                frozen["minutes"]
            )

        else:

            source_rate = prior_rate
            train_minutes = 0.0


        blended_rate = (
            prior_rate
            + alpha
            * (
                source_rate
                - prior_rate
            )
        )


        exposure = (
            float(row.minutes)
            / 90.0
        )


        rows.append({
            "team": str(
                row.team_key
            ),
            "name": str(
                row.name
            ),
            "player_key": str(
                row.player_key
            ),
            "position": position,
            "actual_xg": float(
                row.actual_xg
            ),
            "minutes": float(
                row.minutes
            ),
            "train_minutes": (
                train_minutes
            ),
            "prior_weight": (
                prior_rate
                * exposure
            ),
            "blend_weight": (
                blended_rate
                * exposure
            ),
        })


    output = []


    by_team = {}

    for row in rows:

        by_team.setdefault(
            row["team"],
            [],
        ).append(row)


    for team, team_rows in (
        by_team.items()
    ):

        actual_total = sum(
            row["actual_xg"]
            for row in team_rows
        )

        prior_total = sum(
            row["prior_weight"]
            for row in team_rows
        )

        blend_total = sum(
            row["blend_weight"]
            for row in team_rows
        )


        if (
            actual_total <= 0
            or prior_total <= 0
            or blend_total <= 0
        ):
            continue


        for row in team_rows:

            output.append({
                **row,
                "actual_share": (
                    row["actual_xg"]
                    / actual_total
                ),
                "prior_share": (
                    row["prior_weight"]
                    / prior_total
                ),
                "blend_share": (
                    row["blend_weight"]
                    / blend_total
                ),
                "team_actual_xg": (
                    actual_total
                ),
            })


    return output


def metrics(rows, prefix):

    if not rows:

        return {
            "ce": math.nan,
            "mae": math.nan,
        }


    teams = {}

    for row in rows:

        teams.setdefault(
            row["team"],
            [],
        ).append(row)


    weighted_ce = 0.0
    weighted_mae = 0.0
    total_weight = 0.0


    for team_rows in teams.values():

        team_xg = float(
            team_rows[0][
                "team_actual_xg"
            ]
        )


        ce = 0.0
        share_mae = 0.0


        for row in team_rows:

            actual = row[
                "actual_share"
            ]

            predicted = max(
                EPS,
                row[
                    f"{prefix}_share"
                ],
            )


            if actual > 0:

                ce += (
                    -actual
                    * math.log(
                        predicted
                    )
                )


            share_mae += abs(
                actual
                - predicted
            )


        share_mae /= len(
            team_rows
        )


        weighted_ce += (
            ce
            * team_xg
        )

        weighted_mae += (
            share_mae
            * team_xg
        )

        total_weight += team_xg


    return {
        "ce": (
            weighted_ce
            / total_weight
        ),
        "mae": (
            weighted_mae
            / total_weight
        ),
    }


def fwd_only(rows):

    result = []


    teams = {}

    for row in rows:

        if row["position"] != "FWD":
            continue

        teams.setdefault(
            row["team"],
            [],
        ).append(
            dict(row)
        )


    for team_rows in teams.values():

        if len(team_rows) < 2:
            continue


        actual_total = sum(
            row["actual_xg"]
            for row in team_rows
        )

        prior_total = sum(
            row["prior_weight"]
            for row in team_rows
        )

        blend_total = sum(
            row["blend_weight"]
            for row in team_rows
        )


        if (
            actual_total <= 0
            or prior_total <= 0
            or blend_total <= 0
        ):
            continue


        for row in team_rows:

            row["actual_share"] = (
                row["actual_xg"]
                / actual_total
            )

            row["prior_share"] = (
                row["prior_weight"]
                / prior_total
            )

            row["blend_share"] = (
                row["blend_weight"]
                / blend_total
            )

            row["team_actual_xg"] = (
                actual_total
            )

            result.append(row)


    return result


data = {
    season: load_vaastav(
        season
    )
    for season in {
        season
        for pair in TRANSITIONS
        for season in pair
    }
}


#
# Tune alpha ONLY on first transition.
#
train_season, tune_season = (
    TRANSITIONS[0]
)

train_rates = build_frozen_rates(
    data[train_season]
)


grid = []


for alpha in ALPHAS:

    rows = aggregate_test(
        data[tune_season],
        train_rates,
        alpha,
    )

    score = metrics(
        rows,
        "blend",
    )

    fwd_score = metrics(
        fwd_only(rows),
        "blend",
    )


    grid.append(
        (
            score["ce"],
            alpha,
            score,
            fwd_score,
        )
    )


grid.sort(
    key=lambda item:
        item[0]
)


best_ce, BEST_ALPHA, _, _ = (
    grid[0]
)


print(
    "=== CAPTAIN-054 "
    "ALLOCATION-SHARE VALIDATION ==="
)

print(
    "Diagnostic uses actual minutes "
    "only to isolate talent-rate quality."
)

print(
    "Alpha tuned ONLY on "
    "2023-24 -> 2024-25."
)

print()

print(
    "BEST_ALPHA:",
    f"{BEST_ALPHA:.2f}",
)


print()
print(
    "--- alpha grid "
    "(tuning transition, ALL CE) ---"
)

for (
    ce,
    alpha,
    score,
    fwd_score,
) in sorted(
    grid,
    key=lambda item:
        item[1],
):

    print(
        f"alpha={alpha:.2f}  "
        f"ALL_CE={score['ce']:.6f}  "
        f"ALL_MAE={score['mae']:.6f}  "
        f"FWD_CE={fwd_score['ce']:.6f}"
    )


print()


for (
    source_season,
    target_season,
) in TRANSITIONS:

    rates = build_frozen_rates(
        data[source_season]
    )


    rows = aggregate_test(
        data[target_season],
        rates,
        BEST_ALPHA,
    )


    baseline = metrics(
        rows,
        "prior",
    )

    challenger = metrics(
        rows,
        "blend",
    )


    fwd_rows = fwd_only(
        rows
    )

    baseline_fwd = metrics(
        fwd_rows,
        "prior",
    )

    challenger_fwd = metrics(
        fwd_rows,
        "blend",
    )


    print(
        "=" * 72
    )

    print(
        f"{source_season} -> "
        f"{target_season}"
    )

    print(
        "=" * 72
    )


    print(
        "ALL "
        f"CE prior={baseline['ce']:.6f} "
        f"blend={challenger['ce']:.6f} "
        f"delta="
        f"{challenger['ce'] - baseline['ce']:+.6f}"
    )

    print(
        "ALL "
        f"shareMAE prior={baseline['mae']:.6f} "
        f"blend={challenger['mae']:.6f} "
        f"delta="
        f"{challenger['mae'] - baseline['mae']:+.6f}"
    )


    print(
        "FWD "
        f"CE prior={baseline_fwd['ce']:.6f} "
        f"blend={challenger_fwd['ce']:.6f} "
        f"delta="
        f"{challenger_fwd['ce'] - baseline_fwd['ce']:+.6f}"
    )


    print()


    haaland = [
        row
        for row in rows
        if "haaland"
        in norm_name(
            row["name"]
        )
    ]


    if haaland:

        for row in haaland:

            print(
                "Haaland:",
                row["team"],
                f"actual_share="
                f"{row['actual_share']:.3f}",
                f"prior_share="
                f"{row['prior_share']:.3f}",
                f"blend_share="
                f"{row['blend_share']:.3f}",
                f"train_min="
                f"{row['train_minutes']:.0f}",
            )


    print()
