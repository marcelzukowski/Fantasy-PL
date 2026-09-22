from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from pathlib import Path
import json
import lzma
import math

import pandas as pd

import fpl_engine.current_history as history

from fpl_engine.data.identity import (
    IdentityResolutionError,
    official_fpl_player_identity_key,
)

from fpl_engine.data.raw_store import RawStore

from fpl_engine.models.player_talent.goal_allocation import (
    predict_goal_allocation_proxy,
)


ROOT = Path(".").resolve()

SOURCE_SEASON = "2025-26"

BASE_RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

STRICT = (
    ROOT
    / "data"
    / "interim"
    / "strict"
    / SOURCE_SEASON
)

OLD_SIDECAR = (
    ROOT
    / "scratch"
    / "decision"
    / "captain059_goal_allocation_proxy"
    / "goal_allocation_proxy.json"
)

OUT_DIR = (
    ROOT
    / "scratch"
    / "decision"
    / "captain062_canonical_goal_allocation"
)

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUT_JSON = (
    OUT_DIR
    / "goal_allocation_proxy_canonical.json"
)

OUT_AUDIT = (
    OUT_DIR
    / "canonical_identity_audit.json"
)


def load_json(path: Path):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def canonical_position(
    value,
):

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


#
# ============================================================
# SOURCE MANIFEST + RAW STORE
# ============================================================
#

manifest_path = (
    STRICT
    / "source_manifest.json"
)

if not manifest_path.exists():

    raise RuntimeError(
        "STRICT source manifest missing"
    )

manifest = load_json(
    manifest_path
)

raw = RawStore(
    ROOT
    / "data"
    / "raw"
)


receipt_index_function = getattr(
    history,
    "_receipts",
    None,
)

id_function = getattr(
    history,
    "_id",
    None,
)


if receipt_index_function is None:

    raise RuntimeError(
        "current_history._receipts "
        "is unavailable"
    )

if id_function is None:

    raise RuntimeError(
        "current_history._id "
        "is unavailable"
    )


receipt_index = (
    receipt_index_function(
        raw.root
    )
)


def raw_receipt(
    root,
    source_record_id,
    checksum,
):
    """Resolve an already-materialized RawStore receipt.

    This is offline-only. No network/provider refresh is performed.
    """

    target = str(
        source_record_id
    )

    expected_checksum = str(
        checksum
    )

    #
    # Fast path: current_history._receipts
    # commonly indexes directly by a manifest
    # source-record identifier.
    #
    direct = receipt_index.get(
        target
    )

    if direct is not None:

        if str(
            getattr(
                direct,
                "checksum",
                "",
            )
        ) == expected_checksum:

            return direct


    #
    # Some receipt indexes contain a more
    # qualified key. Mirror the historical
    # backtest resolver semantics:
    #
    # record == source_record_id
    # OR
    # record.endswith(
    #     ":" + source_record_id
    # )
    #
    matches = []


    for key, receipt in (
        receipt_index.items()
    ):

        key_text = str(
            key
        )

        record_text = str(
            getattr(
                receipt,
                "source_record_id",
                "",
            )
            or ""
        )

        actual_checksum = str(
            getattr(
                receipt,
                "checksum",
                "",
            )
        )


        key_match = (
            key_text == target
            or key_text.endswith(
                f":{target}"
            )
        )

        record_match = (
            record_text == target
            or record_text.endswith(
                f":{target}"
            )
        )


        if (
            (
                key_match
                or record_match
            )
            and actual_checksum
            == expected_checksum
        ):

            matches.append(
                receipt
            )


    if not matches:

        raise RuntimeError(
            "Missing RawStore receipt for "
            f"{source_record_id}"
        )


    #
    # Multiple aliases may occasionally point
    # to the same immutable snapshot.
    #
    unique = {}

    for receipt in matches:

        identity = str(
            getattr(
                receipt,
                "snapshot_id",
                None,
            )
            or getattr(
                receipt,
                "payload_path",
                None,
            )
            or repr(
                receipt
            )
        )

        unique[
            identity
        ] = receipt


    if len(unique) != 1:

        raise RuntimeError(
            "Ambiguous RawStore receipt for "
            f"{source_record_id}: "
            f"{len(unique)} candidates"
        )


    return next(
        iter(
            unique.values()
        )
    )


#
# ============================================================
# RECONSTRUCT STRICT PLAYER-ID MAP
#
# This mirrors load_strict_historical_context:
#
# provider element ID
#   -> official_fpl_player_identity_key
#   -> canonical _id("ply", identity_key)
#
# No names participate in matching.
# ============================================================
#

first_elements = {}

snapshot_points = sorted(
    manifest["prediction_points"],
    key=lambda point:
        int(
            point["gameweek"]
        ),
)


for point in snapshot_points:

    receipt = raw_receipt(
        raw.root,
        point["snapshot_path"],
        point["checksum"],
    )

    body = raw.read_bytes(
        receipt
    )

    payload = json.loads(
        lzma.decompress(
            body
        )
    )

    elements = payload.get(
        "elements",
        []
    )

    for element in elements:

        provider_id = int(
            element["id"]
        )

        first_elements.setdefault(
            provider_id,
            element,
        )


provider_to_canonical = {}

canonical_to_provider = {}

identity_key_by_provider = {}


for provider_id, element in (
    first_elements.items()
):

    try:

        identity_key = (
            official_fpl_player_identity_key(
                element
            )
        )

    except IdentityResolutionError as exc:

        raise RuntimeError(
            f"STRICT {SOURCE_SEASON} "
            f"player {provider_id} lacks "
            f"safe identity key: {exc}"
        ) from exc


    player_id = id_function(
        "ply",
        identity_key,
    )


    previous = (
        canonical_to_provider.get(
            player_id
        )
    )

    if (
        previous is not None
        and previous != provider_id
    ):

        raise RuntimeError(
            "Canonical player collision: "
            f"{previous} and "
            f"{provider_id} -> "
            f"{player_id}"
        )


    provider_to_canonical[
        provider_id
    ] = player_id

    canonical_to_provider[
        player_id
    ] = provider_id

    identity_key_by_provider[
        provider_id
    ] = identity_key


#
# ============================================================
# LOAD VAastav STRICT MERGED_GW
# ============================================================
#

vaastav_ref = manifest[
    "vaastav_repository_ref"
]

vaastav_checksum = manifest[
    "vaastav"
][
    "checksum"
]

vaastav_record_id = (
    f"{vaastav_ref}:"
    f"{SOURCE_SEASON}:"
    f"merged_gw"
)

vaastav_receipt = raw_receipt(
    raw.root,
    vaastav_record_id,
    vaastav_checksum,
)

vaastav_bytes = raw.read_bytes(
    vaastav_receipt
)

frame = pd.read_csv(
    BytesIO(
        vaastav_bytes
    )
)


required = {
    "element",
    "minutes",
    "expected_goals",
    "position",
}

missing_columns = (
    required
    - set(
        frame.columns
    )
)

if missing_columns:

    raise RuntimeError(
        "Vaastav missing columns: "
        + ", ".join(
            sorted(
                missing_columns
            )
        )
    )


frame["provider_player_id"] = (
    pd.to_numeric(
        frame["element"],
        errors="coerce",
    )
)

frame["minutes_numeric"] = (
    pd.to_numeric(
        frame["minutes"],
        errors="coerce",
    )
)

frame["expected_goals_numeric"] = (
    pd.to_numeric(
        frame["expected_goals"],
        errors="coerce",
    )
)

frame["position_canonical"] = (
    frame["position"]
    .map(
        canonical_position
    )
)


frame = frame[
    frame[
        "provider_player_id"
    ].notna()
].copy()


frame[
    "provider_player_id"
] = (
    frame[
        "provider_player_id"
    ]
    .astype(int)
)


frame["player_id"] = (
    frame[
        "provider_player_id"
    ]
    .map(
        provider_to_canonical
    )
)


#
# Rows not resolvable through STRICT
# identity are excluded explicitly.
#
unresolved_vaastav_rows = int(
    frame[
        "player_id"
    ].isna().sum()
)

frame = frame[
    frame["player_id"].notna()
].copy()


#
# ============================================================
# AGGREGATE PRIOR-SEASON EVIDENCE
# ============================================================
#

historical = {}


for player_id, group in (
    frame.groupby(
        "player_id",
        sort=False,
    )
):

    valid = group[
        group[
            "minutes_numeric"
        ].notna()
        & group[
            "expected_goals_numeric"
        ].notna()
        & (
            group[
                "minutes_numeric"
            ] > 0
        )
    ]

    if valid.empty:
        continue


    position_minutes = (
        valid.groupby(
            "position_canonical"
        )[
            "minutes_numeric"
        ]
        .sum()
        .sort_values(
            ascending=False
        )
    )


    if position_minutes.empty:
        continue


    historical_position = str(
        position_minutes.index[0]
    )


    historical[
        str(player_id)
    ] = {
        "position": (
            historical_position
        ),
        "total_xg": float(
            valid[
                "expected_goals_numeric"
            ].sum()
        ),
        "minutes": float(
            valid[
                "minutes_numeric"
            ].sum()
        ),
        "rows": int(
            len(valid)
        ),
        "provider_player_ids": sorted(
            {
                int(value)
                for value in valid[
                    "provider_player_id"
                ]
            }
        ),
    }


#
# ============================================================
# CURRENT 2026/27 PLAYERS
# ============================================================
#

current_players = load_json(
    BASE_RUN
    / "current_players.json"
)

current_ids = {
    str(
        row["player_id"]
    )
    for row in current_players
}


proxy_rows = []

matched = 0
position_mismatch = []
no_history = []


for player in current_players:

    player_id = str(
        player["player_id"]
    )

    position = canonical_position(
        player["position"]
    )

    evidence = historical.get(
        player_id
    )


    use_evidence = False

    source_xg = None
    source_minutes = 0.0
    provider_ids = []


    if evidence is None:

        no_history.append(
            player_id
        )

    elif (
        evidence["position"]
        != position
    ):

        position_mismatch.append({
            "player_id": (
                player_id
            ),
            "display_name": (
                player.get(
                    "display_name"
                )
            ),
            "current_position": (
                position
            ),
            "historical_position": (
                evidence[
                    "position"
                ]
            ),
            "historical_minutes": (
                evidence[
                    "minutes"
                ]
            ),
        })

    else:

        use_evidence = True

        source_xg = float(
            evidence[
                "total_xg"
            ]
        )

        source_minutes = float(
            evidence[
                "minutes"
            ]
        )

        provider_ids = list(
            evidence[
                "provider_player_ids"
            ]
        )

        matched += 1


    prediction = (
        predict_goal_allocation_proxy(
            player_id=player_id,
            position=position,
            source_season=(
                SOURCE_SEASON
                if use_evidence
                else None
            ),
            source_total_xg=(
                source_xg
            ),
            source_minutes=(
                source_minutes
            ),
        )
    )


    proxy_rows.append({
        "player_id": (
            player_id
        ),
        "display_name": (
            player.get(
                "display_name"
            )
            or player_id
        ),
        "position": position,
        "source_season": (
            prediction.source_season
        ),
        "source_provider_player_ids": (
            provider_ids
        ),
        "source_total_xg": (
            prediction
            .source_total_xg
        ),
        "source_minutes": (
            prediction
            .source_minutes
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
        "alpha": (
            prediction.alpha
        ),
        "used_historical_total_xg": (
            prediction
            .used_historical_total_xg
        ),
        "identity_method": (
            "official_fpl_player_identity_key"
            "_to_canonical_player_id"
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


#
# ============================================================
# COMPARE WITH CAPTAIN-059 NAME MATCHER
# ============================================================
#

old_rows = {}

if OLD_SIDECAR.exists():

    old_payload = load_json(
        OLD_SIDECAR
    )

    old_rows = {
        str(
            row["player_id"]
        ):
        row
        for row in old_payload[
            "players"
        ]
    }


new_by_id = {
    row["player_id"]:
        row
    for row in proxy_rows
}


old_used = {
    pid
    for pid, row
    in old_rows.items()
    if row.get(
        "used_historical_total_xg"
    )
}

new_used = {
    pid
    for pid, row
    in new_by_id.items()
    if row.get(
        "used_historical_total_xg"
    )
}


overlap = (
    old_used
    & new_used
)

canonical_only = (
    new_used
    - old_used
)

name_only = (
    old_used
    - new_used
)


proxy_differences = []


for player_id in sorted(
    overlap
):

    old_proxy = float(
        old_rows[
            player_id
        ][
            "goal_allocation_proxy_per90"
        ]
    )

    new_proxy = float(
        new_by_id[
            player_id
        ][
            "goal_allocation_proxy_per90"
        ]
    )

    delta = (
        new_proxy
        - old_proxy
    )

    if not math.isclose(
        old_proxy,
        new_proxy,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):

        proxy_differences.append({
            "player_id": (
                player_id
            ),
            "display_name": (
                new_by_id[
                    player_id
                ][
                    "display_name"
                ]
            ),
            "old_proxy": (
                old_proxy
            ),
            "canonical_proxy": (
                new_proxy
            ),
            "delta": delta,
        })


#
# ============================================================
# WRITE SIDECAR
# ============================================================
#

payload = {
    "artifact_version": (
        "goal_allocation_proxy_sidecar_v2"
    ),
    "status": (
        "DEVELOPMENT_ONLY"
    ),
    "production_projection_modified": (
        False
    ),
    "source_run": str(
        BASE_RUN.relative_to(
            ROOT
        )
    ),
    "source_season": (
        SOURCE_SEASON
    ),
    "alpha": 0.55,
    "identity_method": (
        "official_fpl_player_identity_key"
        "_to_canonical_player_id"
    ),
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


audit = {
    "current_players": (
        len(
            current_players
        )
    ),
    "strict_snapshot_players": (
        len(
            provider_to_canonical
        )
    ),
    "historical_players_with_xg": (
        len(
            historical
        )
    ),
    "canonical_matches": (
        matched
    ),
    "canonical_match_rate": (
        matched
        / len(
            current_players
        )
        if current_players
        else 0.0
    ),
    "position_mismatch_count": (
        len(
            position_mismatch
        )
    ),
    "no_history_count": (
        len(
            no_history
        )
    ),
    "unresolved_vaastav_rows": (
        unresolved_vaastav_rows
    ),
    "old_name_matches": (
        len(
            old_used
        )
    ),
    "overlap_with_name_matcher": (
        len(
            overlap
        )
    ),
    "canonical_only": (
        len(
            canonical_only
        )
    ),
    "name_only": (
        len(
            name_only
        )
    ),
    "overlap_proxy_difference_count": (
        len(
            proxy_differences
        )
    ),
    "position_mismatches": (
        position_mismatch
    ),
    "canonical_only_players": [
        {
            "player_id": pid,
            "display_name": (
                new_by_id[
                    pid
                ][
                    "display_name"
                ]
            ),
        }
        for pid in sorted(
            canonical_only
        )
    ],
    "name_only_players": [
        {
            "player_id": pid,
            "display_name": (
                old_rows[
                    pid
                ].get(
                    "display_name",
                    pid,
                )
            ),
        }
        for pid in sorted(
            name_only
        )
    ],
    "proxy_differences": (
        proxy_differences
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


#
# ============================================================
# COMPACT REPORT
# ============================================================
#

print(
    "=== CAPTAIN-062 "
    "CANONICAL GOAL-ALLOCATION SIDECAR ==="
)

print(
    "current players:",
    len(
        current_players
    ),
)

print(
    "STRICT identity players:",
    len(
        provider_to_canonical
    ),
)

print(
    "historical players with xG:",
    len(
        historical
    ),
)

print(
    "canonical matches:",
    matched,
)

print(
    "canonical match_rate:",
    f"{audit['canonical_match_rate']:.3f}",
)

print(
    "position mismatches:",
    len(
        position_mismatch
    ),
)

print(
    "no history:",
    len(
        no_history
    ),
)

print(
    "unresolved Vaastav rows:",
    unresolved_vaastav_rows,
)


print()
print(
    "=== VS CAPTAIN-059 NAME MATCHER ==="
)

print(
    "old name matches:",
    len(
        old_used
    ),
)

print(
    "overlap:",
    len(
        overlap
    ),
)

print(
    "canonical only:",
    len(
        canonical_only
    ),
)

print(
    "name only:",
    len(
        name_only
    ),
)

print(
    "different proxy within overlap:",
    len(
        proxy_differences
    ),
)


print()
print(
    "=== KEY PLAYERS ==="
)


for token in (
    "Haaland",
    "Palmer",
    "B.Fernandes",
    "Tavernier",
    "Szoboszlai",
):

    rows = [
        row
        for row in proxy_rows
        if token.casefold()
        in str(
            row[
                "display_name"
            ]
        ).casefold()
    ]

    for row in rows:

        print(
            f"{row['display_name']:<24} "
            f"{row['position']:<3} "
            f"used="
            f"{str(row['used_historical_total_xg']):<5} "
            f"xG="
            f"{str(row['source_total_xg']):<8} "
            f"min="
            f"{row['source_minutes']:.0f} "
            f"proxy="
            f"{row['goal_allocation_proxy_per90']:.3f}"
        )


if canonical_only:

    print()
    print(
        "=== CANONICAL-ONLY SAMPLE ==="
    )

    for pid in sorted(
        canonical_only
    )[:20]:

        row = new_by_id[
            pid
        ]

        print(
            f"{row['display_name']:<28} "
            f"{row['position']} "
            f"proxy="
            f"{row['goal_allocation_proxy_per90']:.3f}"
        )


if name_only:

    print()
    print(
        "=== NAME-ONLY SAMPLE ==="
    )

    for pid in sorted(
        name_only
    )[:20]:

        row = old_rows[
            pid
        ]

        print(
            f"{row.get('display_name', pid):<28} "
            f"{row.get('position')} "
            f"proxy="
            f"{row.get('goal_allocation_proxy_per90')}"
        )


if proxy_differences:

    print()
    print(
        "=== OVERLAP DIFFERENCES SAMPLE ==="
    )

    for row in sorted(
        proxy_differences,
        key=lambda item:
            -abs(
                item[
                    "delta"
                ]
            ),
    )[:20]:

        print(
            f"{row['display_name']:<28} "
            f"old="
            f"{row['old_proxy']:.3f} "
            f"canonical="
            f"{row['canonical_proxy']:.3f} "
            f"delta="
            f"{row['delta']:+.3f}"
        )


print()
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

print(
    "Production/frozen artifacts modified: NO"
)
