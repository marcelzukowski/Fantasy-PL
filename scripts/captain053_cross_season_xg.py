from pathlib import Path
from io import BytesIO
import json
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

TRANSITIONS = (
    ("2023-24", "2024-25"),
    ("2024-25", "2025-26"),
)

PRIOR_MINUTES = float(
    PlayerTalentModel()
    .config
    .prior_minutes
)

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
        }

        if required.issubset(
            frame.columns
        ):
            candidates.append(frame)


    if not candidates:

        raise RuntimeError(
            f"{season}: no Vaastav "
            f"expected_goals frame"
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
        .astype(str)
        .str.upper()
        .replace({
            "FORWARD": "FWD",
            "MIDFIELDER": "MID",
            "DEFENDER": "DEF",
            "GOALKEEPER": "GK",
            "GKP": "GK",
        })
    )

    return frame


def mae(rows, field):

    return sum(
        abs(
            row["actual"]
            - row[field]
        )
        for row in rows
    ) / len(rows)


for train_season, test_season in TRANSITIONS:

    train = load_vaastav(
        train_season
    )

    test = load_vaastav(
        test_season
    )


    #
    # Frozen prior-season player rates.
    #
    rates = {}


    for (
        player_key,
        group
    ) in train.groupby(
        "player_key"
    ):

        position = str(
            group[
                "position_c"
            ].iloc[-1]
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


    rows = []


    for row in test.itertuples(
        index=False
    ):

        key = row.player_key

        historical = rates.get(key)

        if historical is None:
            continue

        position = str(
            row.position_c
        )

        if position != historical["position"]:
            continue

        minutes = float(
            row.minutes
        )

        actual = float(
            row.expected_goals
        )

        prior_rate = float(
            CORE_PRIORS.get(
                position,
                CORE_PRIORS["MID"],
            )["npxg"]
        )

        rows.append({
            "name": str(row.name),
            "position": position,
            "train_minutes": (
                historical["minutes"]
            ),
            "rate": historical["rate"],
            "actual": actual,
            "prior": (
                prior_rate
                * minutes
                / 90.0
            ),
            "frozen": (
                historical["rate"]
                * minutes
                / 90.0
            ),
        })


    print()
    print(
        "=" * 72
    )

    print(
        f"{train_season} -> "
        f"{test_season}"
    )

    print(
        "=" * 72
    )


    def report(label, selected):

        if not selected:

            print(
                label,
                "NO ROWS",
            )

            return

        prior_mae = mae(
            selected,
            "prior",
        )

        frozen_mae = mae(
            selected,
            "frozen",
        )

        delta = (
            frozen_mae
            - prior_mae
        )

        pct = (
            delta
            / prior_mae
            * 100.0
            if prior_mae
            else 0.0
        )

        print(
            f"{label:<20}"
            f"N={len(selected):5d}  "
            f"prior={prior_mae:.5f}  "
            f"frozen={frozen_mae:.5f}  "
            f"delta={delta:+.5f} "
            f"({pct:+.2f}%)"
        )


    report(
        "ALL",
        rows,
    )

    report(
        "FWD",
        [
            row
            for row in rows
            if row["position"] == "FWD"
        ],
    )

    report(
        "FWD train>=900",
        [
            row
            for row in rows
            if (
                row["position"] == "FWD"
                and row[
                    "train_minutes"
                ] >= 900
            )
        ],
    )

    report(
        "FWD train>=1800",
        [
            row
            for row in rows
            if (
                row["position"] == "FWD"
                and row[
                    "train_minutes"
                ] >= 1800
            )
        ],
    )


    forwards = {}

    for row in rows:

        if row["position"] != "FWD":
            continue

        forwards.setdefault(
            norm_name(
                row["name"]
            ),
            {
                "name": row["name"],
                "rate": row["rate"],
                "minutes": row[
                    "train_minutes"
                ],
            },
        )


    ranked = sorted(
        forwards.values(),
        key=lambda row:
            row["rate"],
        reverse=True,
    )


    print()
    print(
        "TOP frozen FWD rates:"
    )

    for item in ranked[:15]:

        marker = (
            "  <=="
            if "haaland"
            in norm_name(
                item["name"]
            )
            else ""
        )

        print(
            f"{item['name']:<28} "
            f"xG90={item['rate']:.3f} "
            f"train_min="
            f"{item['minutes']:.0f}"
            f"{marker}"
        )
