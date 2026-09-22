from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from pathlib import Path
import json
import re
import unicodedata

import pandas as pd

from fpl_engine.current_history import _receipts
from fpl_engine.data.raw_store import RawStore
from fpl_engine.models.player_talent.goal_allocation import (
    predict_goal_allocation_proxy,
)


ROOT = Path(".").resolve()

SOURCE_SEASON = "2025-26"

RUN_DIR = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

OUT_DIR = (
    ROOT
    / "scratch"
    / "decision"
    / "captain059_goal_allocation_proxy"
)

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUT_JSON = (
    OUT_DIR
    / "goal_allocation_proxy.json"
)

OUT_AUDIT = (
    OUT_DIR
    / "goal_allocation_proxy_audit.json"
)


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def norm_name(value) -> str:

    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text,
    )


def walk_strings(value):

    if isinstance(value, dict):

        for item in value.values():
            yield from walk_strings(item)

    elif isinstance(value, list):

        for item in value:
            yield from walk_strings(item)

    elif isinstance(value, str):

        yield value


def load_strict_vaastav(
    season: str,
) -> pd.DataFrame:

    manifest_path = (
        ROOT
        / "data"
        / "interim"
        / "strict"
        / season
        / "source_manifest.json"
    )

    if not manifest_path.exists():

        raise RuntimeError(
            f"STRICT manifest missing: "
            f"{manifest_path}"
        )

    manifest = load_json(
        manifest_path
    )

    raw = RawStore(
        ROOT / "data" / "raw"
    )

    receipts = _receipts(
        raw.root
    )

    candidates = []

    required = {
        "element",
        "fixture",
        "name",
        "position",
        "minutes",
        "expected_goals",
    }

    for value in walk_strings(
        manifest
    ):

        receipt = receipts.get(
            value
        )

        if receipt is None:
            continue

        try:

            frame = pd.read_csv(
                BytesIO(
                    raw.read_bytes(
                        receipt
                    )
                )
            )

        except Exception:
            continue

        if required.issubset(
            set(frame.columns)
        ):

            candidates.append(
                frame
            )

    if not candidates:

        raise RuntimeError(
            f"No STRICT Vaastav frame "
            f"for {season}"
        )

    candidates.sort(
        key=len,
        reverse=True,
    )

    return candidates[0].copy()


def position(value) -> str:

    value = str(
        value or ""
    ).upper()

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


def current_name_candidates(
    row: dict,
) -> set[str]:

    payload = (
        row.get("provider_payload")
        or {}
    )

    values = {
        row.get("display_name"),
        row.get("name"),
        row.get("web_name"),
        payload.get("web_name"),
    }

    first = (
        payload.get("first_name")
        or ""
    )

    second = (
        payload.get("second_name")
        or ""
    )

    if first or second:

        values.add(
            f"{first} {second}".strip()
        )

    return {
        norm_name(value)
        for value in values
        if value
    }


players_path = (
    RUN_DIR
    / "current_players.json"
)

talent_path = (
    RUN_DIR
    / "player_talent.json"
)

events_path = (
    RUN_DIR
    / "event_projections.json"
)


for path in (
    players_path,
    talent_path,
    events_path,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing smoke artifact: "
            f"{path}"
        )


current_players = load_json(
    players_path
)

talent_rows = load_json(
    talent_path
)

event_rows = load_json(
    events_path
)


#
# Historical 2025/26 total-xG evidence.
#
history = load_strict_vaastav(
    SOURCE_SEASON
)

history["minutes"] = pd.to_numeric(
    history["minutes"],
    errors="coerce",
)

history["expected_goals"] = (
    pd.to_numeric(
        history["expected_goals"],
        errors="coerce",
    )
)

history = history[
    history["minutes"].notna()
    & history["expected_goals"].notna()
    & (history["minutes"] > 0)
].copy()

history["name_key"] = (
    history["name"]
    .map(norm_name)
)

history["position_c"] = (
    history["position"]
    .map(position)
)


historical_by_name = {}


for name_key, group in (
    history.groupby(
        "name_key"
    )
):

    names = sorted(
        {
            str(value)
            for value in group[
                "name"
            ].dropna()
        }
    )

    positions = sorted(
        set(
            group[
                "position_c"
            ].astype(str)
        )
    )

    historical_by_name[
        name_key
    ] = {
        "names": names,
        "positions": positions,
        "total_xg": float(
            group[
                "expected_goals"
            ].sum()
        ),
        "minutes": float(
            group[
                "minutes"
            ].sum()
        ),
        "rows": int(
            len(group)
        ),
    }


#
# Build current-player proxy sidecar.
#
proxy_rows = []

matched = 0
unmatched = []
ambiguous = []


for player in current_players:

    player_id = str(
        player["player_id"]
    )

    player_position = position(
        player.get(
            "position"
        )
    )

    candidates = current_name_candidates(
        player
    )

    hits = [
        historical_by_name[key]
        for key in candidates
        if key in historical_by_name
    ]


    #
    # Deduplicate identical historical
    # objects reached by two aliases.
    #
    unique_hits = {}

    for hit in hits:

        identity = (
            tuple(hit["names"]),
            hit["total_xg"],
            hit["minutes"],
        )

        unique_hits[
            identity
        ] = hit

    hits = list(
        unique_hits.values()
    )


    compatible = [
        hit
        for hit in hits
        if (
            player_position
            in hit["positions"]
        )
    ]


    if len(compatible) == 1:

        evidence = compatible[0]

        source_xg = float(
            evidence["total_xg"]
        )

        source_minutes = float(
            evidence["minutes"]
        )

        source_name = (
            evidence["names"][0]
            if evidence["names"]
            else None
        )

        matched += 1

    else:

        source_xg = None
        source_minutes = 0.0
        source_name = None

        display = (
            player.get(
                "display_name"
            )
            or player.get(
                "name"
            )
            or player_id
        )

        if len(compatible) > 1:

            ambiguous.append(
                str(display)
            )

        else:

            unmatched.append(
                str(display)
            )


    prediction = (
        predict_goal_allocation_proxy(
            player_id=player_id,
            position=player_position,
            source_season=(
                SOURCE_SEASON
                if source_xg
                is not None
                else None
            ),
            source_total_xg=source_xg,
            source_minutes=(
                source_minutes
            ),
        )
    )


    proxy_rows.append({
        "player_id": player_id,
        "display_name": (
            player.get(
                "display_name"
            )
            or player.get(
                "name"
            )
            or player_id
        ),
        "position": (
            player_position
        ),
        "historical_name": (
            source_name
        ),
        "source_season": (
            prediction.source_season
        ),
        "source_total_xg": (
            prediction.source_total_xg
        ),
        "source_minutes": (
            prediction.source_minutes
        ),
        "position_prior_per90": (
            prediction
            .position_prior_per90
        ),
        "frozen_total_xg_rate_per90": (
            prediction
            .frozen_total_xg_rate_per90
        ),
        "goal_allocation_proxy_per90": (
            prediction
            .goal_allocation_proxy_per90
        ),
        "alpha": prediction.alpha,
        "used_historical_total_xg": (
            prediction
            .used_historical_total_xg
        ),
        "source_metric": (
            prediction.source_metric
        ),
        "intended_use": (
            prediction.intended_use
        ),
        "model_version": (
            prediction.model_version
        ),
        "feature_version": (
            prediction.feature_version
        ),
    })


proxy_rows.sort(
    key=lambda row:
        row["player_id"]
)


payload = {
    "artifact_version": (
        "goal_allocation_proxy_sidecar_v1"
    ),
    "status": (
        "DEVELOPMENT_ONLY"
    ),
    "production_projection_modified": (
        False
    ),
    "source_run": str(
        RUN_DIR.relative_to(
            ROOT
        )
    ),
    "source_season": (
        SOURCE_SEASON
    ),
    "alpha": 0.55,
    "source_metric": (
        "historical_total_xg_including_penalties"
    ),
    "intended_use": (
        "relative_team_goal_allocation_only"
    ),
    "players": proxy_rows,
}


OUT_JSON.write_text(
    json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


#
# Existing PlayerTalent rates.
#
talent_by_player = {}

for row in talent_rows:

    player_id = str(
        row["player_id"]
    )

    talent_by_player.setdefault(
        player_id,
        row,
    )


proxy_by_player = {
    row["player_id"]: row
    for row in proxy_rows
}


#
# Diagnostic reallocation using existing
# fixture context.
#
#
# Event V1 has:
#
# raw_expected_npxg =
#   talent_npxg_per90
#   * fixture modifiers
#   * exposure
#
# Therefore:
#
# fixture_scale =
#   raw_expected_npxg
#   / talent_npxg_per90
#
# and the challenger allocation weight is:
#
# proxy_per90 * fixture_scale
#
# No event artifact is modified.
#
diagnostic_player = defaultdict(
    lambda: {
        "legacy_open_goals": 0.0,
        "proxy_open_goals": 0.0,
        "penalty_goals": 0.0,
        "fixtures": 0,
    }
)

team_diagnostics = []


for event in event_rows:

    fixture_id = str(
        event.get(
            "fixture_id",
            ""
        )
    )

    for side_name in (
        "home",
        "away",
    ):

        team = event.get(
            side_name
        )

        if not isinstance(
            team,
            dict,
        ):
            continue

        rows = team.get(
            "players",
            []
        )

        prepared = []

        for row in rows:

            rates = (
                row.get("rates")
                or {}
            )

            goals = (
                row.get("goals")
                or {}
            )

            player_id = str(
                rates.get(
                    "player_id"
                )
                or row.get(
                    "player_id"
                )
                or ""
            )

            if not player_id:
                continue


            legacy_weight = float(
                rates.get(
                    "raw_expected_npxg"
                )
                or 0.0
            )


            talent = (
                talent_by_player.get(
                    player_id,
                    {}
                )
            )

            talent_rate = float(
                talent.get(
                    "talent_npxg_per90"
                )
                or 0.0
            )


            proxy = (
                proxy_by_player.get(
                    player_id
                )
            )

            proxy_rate = (
                float(
                    proxy[
                        "goal_allocation_proxy_per90"
                    ]
                )
                if proxy
                else talent_rate
            )


            if talent_rate > 0.0:

                fixture_scale = (
                    legacy_weight
                    / talent_rate
                )

                proxy_weight = (
                    proxy_rate
                    * fixture_scale
                )

            else:

                proxy_weight = (
                    legacy_weight
                )


            legacy_open = float(
                goals.get(
                    "expected_open_play_goals"
                )
                or 0.0
            )

            penalty = float(
                goals.get(
                    "expected_penalty_goals"
                )
                or 0.0
            )


            prepared.append({
                "player_id": (
                    player_id
                ),
                "legacy_weight": (
                    legacy_weight
                ),
                "proxy_weight": (
                    proxy_weight
                ),
                "legacy_open": (
                    legacy_open
                ),
                "penalty": (
                    penalty
                ),
            })


        open_envelope = sum(
            row["legacy_open"]
            for row in prepared
        )

        legacy_weight_total = sum(
            row["legacy_weight"]
            for row in prepared
        )

        proxy_weight_total = sum(
            row["proxy_weight"]
            for row in prepared
        )


        for row in prepared:

            if (
                open_envelope > 0.0
                and proxy_weight_total > 0.0
            ):

                proxy_open = (
                    open_envelope
                    * row[
                        "proxy_weight"
                    ]
                    / proxy_weight_total
                )

            else:

                proxy_open = (
                    row["legacy_open"]
                )


            result = (
                diagnostic_player[
                    row["player_id"]
                ]
            )

            result[
                "legacy_open_goals"
            ] += row["legacy_open"]

            result[
                "proxy_open_goals"
            ] += proxy_open

            result[
                "penalty_goals"
            ] += row["penalty"]

            result[
                "fixtures"
            ] += 1


        team_diagnostics.append({
            "fixture_id": (
                fixture_id
            ),
            "side": (
                side_name
            ),
            "team_id": (
                team.get(
                    "team_id"
                )
            ),
            "open_envelope": (
                open_envelope
            ),
            "legacy_weight_total": (
                legacy_weight_total
            ),
            "proxy_weight_total": (
                proxy_weight_total
            ),
        })


names = {
    str(row["player_id"]): (
        row.get(
            "display_name"
        )
        or row.get(
            "name"
        )
        or row["player_id"]
    )
    for row in current_players
}


diagnostic_rows = []


for player_id, values in (
    diagnostic_player.items()
):

    legacy_total = (
        values["legacy_open_goals"]
        + values["penalty_goals"]
    )

    proxy_total = (
        values["proxy_open_goals"]
        + values["penalty_goals"]
    )

    diagnostic_rows.append({
        "player_id": player_id,
        "display_name": names.get(
            player_id,
            player_id,
        ),
        **values,
        "legacy_total_goals": (
            legacy_total
        ),
        "proxy_total_goals": (
            proxy_total
        ),
        "delta_total_goals": (
            proxy_total
            - legacy_total
        ),
    })


diagnostic_rows.sort(
    key=lambda row:
        (
            -row[
                "delta_total_goals"
            ],
            row[
                "display_name"
            ],
        )
)


audit = {
    "status": "DEVELOPMENT_ONLY",
    "players_total": len(
        current_players
    ),
    "historical_matches": (
        matched
    ),
    "historical_match_rate": (
        matched
        / len(current_players)
        if current_players
        else 0.0
    ),
    "unmatched_count": len(
        unmatched
    ),
    "ambiguous_count": len(
        ambiguous
    ),
    "unmatched": sorted(
        unmatched
    ),
    "ambiguous": sorted(
        ambiguous
    ),
    "team_diagnostics": (
        team_diagnostics
    ),
    "player_diagnostic": (
        diagnostic_rows
    ),
}


OUT_AUDIT.write_text(
    json.dumps(
        audit,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-059 "
    "GOAL ALLOCATION SIDECAR ==="
)

print(
    "players:",
    len(current_players),
)

print(
    "matched:",
    matched,
)

print(
    "match_rate:",
    f"{audit['historical_match_rate']:.3f}",
)

print(
    "unmatched:",
    len(unmatched),
)

print(
    "ambiguous:",
    len(ambiguous),
)

print(
    "sidecar:",
    OUT_JSON.relative_to(
        ROOT
    ),
)

print(
    "audit:",
    OUT_AUDIT.relative_to(
        ROOT
    ),
)


print()
print(
    "=== KEY PLAYERS ==="
)


targets = (
    "haaland",
    "bruno",
    "palmer",
    "szoboszlai",
    "tavernier",
)


for token in targets:

    rows = [
        row
        for row in proxy_rows
        if token
        in norm_name(
            row["display_name"]
        )
    ]

    for row in rows[:3]:

        print(
            f"{row['display_name']:<28} "
            f"{row['position']:<3} "
            f"used={str(row['used_historical_total_xg']):<5} "
            f"xG={str(row['source_total_xg']):<7} "
            f"min={row['source_minutes']:.0f} "
            f"prior={row['position_prior_per90']:.3f} "
            f"frozen={row['frozen_total_xg_rate_per90']:.3f} "
            f"proxy={row['goal_allocation_proxy_per90']:.3f}"
        )


print()
print(
    "=== BIGGEST OPEN-GOAL GAINS "
    "GW4-GW9 DIAGNOSTIC ==="
)


for row in diagnostic_rows[:15]:

    print(
        f"{row['display_name']:<28} "
        f"legacy={row['legacy_total_goals']:.3f} "
        f"proxy={row['proxy_total_goals']:.3f} "
        f"delta={row['delta_total_goals']:+.3f}"
    )


print()
print(
    "=== BIGGEST OPEN-GOAL LOSSES "
    "GW4-GW9 DIAGNOSTIC ==="
)


for row in sorted(
    diagnostic_rows,
    key=lambda item:
        item["delta_total_goals"],
)[:10]:

    print(
        f"{row['display_name']:<28} "
        f"legacy={row['legacy_total_goals']:.3f} "
        f"proxy={row['proxy_total_goals']:.3f} "
        f"delta={row['delta_total_goals']:+.3f}"
    )


print()
print(
    "Production artifacts modified: NO"
)
