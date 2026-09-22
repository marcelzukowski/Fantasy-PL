from pathlib import Path
from io import BytesIO
import json
import math

import pandas as pd

from fpl_engine.current_history import _receipts
from fpl_engine.data.raw_store import RawStore
from fpl_engine.models.player_talent.model import (
    CORE_PRIORS,
    PlayerTalentModel,
)


ROOT = Path(".").resolve()

SEASONS = (
    "2024-25",
    "2025-26",
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


raw = RawStore(
    ROOT / "data" / "raw"
)

receipts = _receipts(
    raw.root
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

    for value in strings(
        manifest
    ):

        receipt = receipts.get(
            value
        )

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
            "kickoff_time",
            "position",
        }


        if required.issubset(
            set(frame.columns)
        ):

            candidates.append(
                frame
            )


    if not candidates:

        raise RuntimeError(
            f"{season}: Vaastav frame "
            f"with expected_goals not found"
        )


    candidates.sort(
        key=len,
        reverse=True,
    )

    return candidates[0].copy()


def canonical_position(value):

    value = str(
        value
    ).upper()

    aliases = {
        "GKP": "GK",
        "GOALKEEPER": "GK",
        "DEFENDER": "DEF",
        "MIDFIELDER": "MID",
        "FORWARD": "FWD",
    }

    return aliases.get(
        value,
        value,
    )


prior_minutes = float(
    PlayerTalentModel()
    .config
    .prior_minutes
)


print(
    "=== TOTAL xG/90 WALK-FORWARD ==="
)

print(
    "prior_minutes:",
    prior_minutes,
)


all_results = []


for season in SEASONS:

    frame = load_vaastav(
        season
    )


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

    frame["kickoff_dt"] = (
        pd.to_datetime(
            frame["kickoff_time"],
            utc=True,
            errors="coerce",
        )
    )

    frame = frame[
        frame["minutes"].notna()
        & frame["expected_goals"].notna()
        & frame["kickoff_dt"].notna()
        & (frame["minutes"] > 0)
    ].copy()


    frame["position_c"] = (
        frame["position"]
        .map(
            canonical_position
        )
    )


    sort_columns = [
        "kickoff_dt",
        "fixture",
        "element",
    ]

    frame = frame.sort_values(
        sort_columns
    )


    histories = {}

    results = []


    for row in frame.itertuples(
        index=False
    ):

        player = int(
            row.element
        )

        pos = str(
            row.position_c
        )

        minutes = float(
            row.minutes
        )

        target_xg = float(
            row.expected_goals
        )


        prior = float(
            CORE_PRIORS.get(
                pos,
                CORE_PRIORS["MID"],
            )["npxg"]
        )


        history = histories.setdefault(
            player,
            {
                "xg": 0.0,
                "minutes": 0.0,
                "games": 0,
            },
        )


        if history["games"] >= 2:

            prior_prediction = (
                prior
                * minutes
                / 90.0
            )


            player_rate = (
                (
                    history["xg"]
                    * 90.0
                    + prior
                    * prior_minutes
                )
                /
                (
                    history["minutes"]
                    + prior_minutes
                )
            )


            challenger_prediction = (
                player_rate
                * minutes
                / 90.0
            )


            results.append(
                {
                    "season": season,
                    "position": pos,
                    "history_games": (
                        history["games"]
                    ),
                    "actual": target_xg,
                    "prior": prior_prediction,
                    "challenger": (
                        challenger_prediction
                    ),
                }
            )


        history["xg"] += (
            target_xg
        )

        history["minutes"] += (
            minutes
        )

        history["games"] += 1


    all_results.extend(
        results
    )


    def report(
        label,
        rows,
    ):

        if not rows:

            print(
                label,
                "NO ROWS",
            )

            return


        prior_mae = sum(
            abs(
                row["actual"]
                - row["prior"]
            )
            for row in rows
        ) / len(rows)


        challenger_mae = sum(
            abs(
                row["actual"]
                - row["challenger"]
            )
            for row in rows
        ) / len(rows)


        delta = (
            challenger_mae
            - prior_mae
        )


        pct = (
            delta
            / prior_mae
            * 100.0
            if prior_mae
            else math.nan
        )


        print(
            f"{label:<18} "
            f"N={len(rows):5d}  "
            f"prior={prior_mae:.5f}  "
            f"xG={challenger_mae:.5f}  "
            f"delta={delta:+.5f} "
            f"({pct:+.2f}%)"
        )


    print()
    print(
        f"--- {season} ---"
    )


    report(
        "ALL",
        results,
    )

    report(
        "FWD",
        [
            row
            for row in results
            if row["position"] == "FWD"
        ],
    )

    report(
        "ESTABLISHED",
        [
            row
            for row in results
            if row["history_games"] >= 5
        ],
    )

    report(
        "FWD >=5",
        [
            row
            for row in results
            if (
                row["position"] == "FWD"
                and row[
                    "history_games"
                ] >= 5
            )
        ],
    )


    #
    # End-of-season FWD rates.
    #
    final = []


    for (
        player,
        group
    ) in frame[
        frame["position_c"]
        == "FWD"
    ].groupby(
        "element"
    ):

        total_minutes = float(
            group["minutes"].sum()
        )

        total_xg = float(
            group[
                "expected_goals"
            ].sum()
        )


        if total_minutes <= 0:
            continue


        rate = (
            total_xg
            * 90.0
            + CORE_PRIORS["FWD"][
                "npxg"
            ]
            * prior_minutes
        ) / (
            total_minutes
            + prior_minutes
        )


        if "name" in group.columns:

            player_name = str(
                group["name"].iloc[-1]
            )

        else:

            player_name = (
                f"element_{player}"
            )


        final.append(
            (
                rate,
                total_minutes,
                player_name,
            )
        )


    final.sort(
        reverse=True
    )


    print()
    print(
        "TOP FWD total-xG/90 "
        "(shrunk):"
    )


    for (
        rate,
        minutes,
        player_name,
    ) in final[:15]:

        marker = (
            "  <=="
            if "haaland"
            in player_name.casefold()
            else ""
        )

        print(
            f"{player_name:<24} "
            f"xG90={rate:.3f} "
            f"min={minutes:.0f}"
            f"{marker}"
        )


    haaland = [
        row
        for row in final
        if "haaland"
        in row[2].casefold()
    ]


    if haaland:

        rank = (
            final.index(
                haaland[0]
            )
            + 1
        )

        print(
            f"Haaland FWD rank: "
            f"{rank}/{len(final)}"
        )


print()
print(
    "=== COMBINED ==="
)


def combined_report(
    label,
    predicate,
):

    rows = [
        row
        for row in all_results
        if predicate(row)
    ]


    if not rows:
        return


    prior_mae = sum(
        abs(
            row["actual"]
            - row["prior"]
        )
        for row in rows
    ) / len(rows)


    challenger_mae = sum(
        abs(
            row["actual"]
            - row["challenger"]
        )
        for row in rows
    ) / len(rows)


    delta = (
        challenger_mae
        - prior_mae
    )


    print(
        f"{label:<18} "
        f"N={len(rows):5d} "
        f"prior={prior_mae:.5f} "
        f"xG={challenger_mae:.5f} "
        f"delta={delta:+.5f}"
    )


combined_report(
    "ALL",
    lambda row: True,
)

combined_report(
    "FWD",
    lambda row:
        row["position"] == "FWD",
)

combined_report(
    "FWD >=5",
    lambda row:
        row["position"] == "FWD"
        and row["history_games"] >= 5,
)
