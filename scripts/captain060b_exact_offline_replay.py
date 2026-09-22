from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
import json
import os
import math
import re
import shutil
import unicodedata

import pandas as pd

import fpl_engine.current as current

from fpl_engine.current import (
    CurrentPipelineConfig,
    CurrentPredictionPipeline,
    CurrentSourceData,
    CurrentSourceRecord,
)

from fpl_engine.models.events.goal_allocation_v2 import (
    GoalAllocationEventModels,
)


ROOT = Path(".").resolve()


def _env_path(
    name: str,
    default: Path,
) -> Path:

    value = os.environ.get(
        name
    )

    if not value:
        return default

    return Path(
        value
    ).expanduser().resolve()


BASE_RUN = _env_path(
    "CAPTAIN_BASE_RUN",
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z",
)

PROXY_PATH = _env_path(
    "CAPTAIN_PROXY_PATH",
    ROOT
    / "scratch"
    / "decision"
    / "captain059_goal_allocation_proxy"
    / "goal_allocation_proxy.json",
)

WORK_ROOT = _env_path(
    "CAPTAIN_WORK_ROOT",
    ROOT
    / "scratch"
    / "decision"
    / "captain060b_exact_offline_replay",
)

REPORT_PATH = (
    WORK_ROOT
    / "comparison.json"
)


def load_json(path: Path):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def parse_dt(value):

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value

    return datetime.fromisoformat(
        str(value).replace(
            "Z",
            "+00:00",
        )
    )


def norm(value):

    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.casefold(),
    )


#
# ============================================================
# PRECONDITIONS
# ============================================================
#

required = (
    BASE_RUN / "prediction_context.json",
    BASE_RUN / "source_provenance.json",
    BASE_RUN / "run_manifest.json",
    BASE_RUN / "current_players.json",
    BASE_RUN / "fixture_horizon.json",
    BASE_RUN / "team_strength.json",
    BASE_RUN / "minutes.json",
    BASE_RUN / "tactical_context.json",
    BASE_RUN / "player_talent.json",
    BASE_RUN / "event_projections.json",
    BASE_RUN / "player_projections.json",
    BASE_RUN
    / "canonical_parquet"
    / "fact_fpl_snapshot.parquet",
    PROXY_PATH,
)

missing = [
    str(path)
    for path in required
    if not path.exists()
]

if missing:

    raise RuntimeError(
        "Missing required replay artifacts:\n"
        + "\n".join(missing)
    )


if WORK_ROOT.exists():

    shutil.rmtree(
        WORK_ROOT
    )

WORK_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


#
# ============================================================
# BASELINE METADATA
# ============================================================
#

context_payload = load_json(
    BASE_RUN
    / "prediction_context.json"
)

manifest = load_json(
    BASE_RUN
    / "run_manifest.json"
)

provenance = load_json(
    BASE_RUN
    / "source_provenance.json"
)

baseline_events = load_json(
    BASE_RUN
    / "event_projections.json"
)


baseline_event_versions = sorted(
    {
        str(
            row.get(
                "model_version"
            )
        )
        for row in baseline_events
    }
)

if baseline_event_versions != [
    "event_models_v1"
]:

    raise RuntimeError(
        "CAPTAIN-060B expects EventModels V1 "
        "baseline. Found: "
        f"{baseline_event_versions}"
    )


simulation_meta = (
    manifest.get(
        "simulation",
        {}
    )
)

simulation_count = int(
    simulation_meta.get(
        "simulations_per_fixture",
        256,
    )
)

seed = int(
    os.environ.get(
        "CAPTAIN_RANDOM_SEED",
        simulation_meta.get(
            "base_seed",
            42,
        ),
    )
)

EVENT_MODE = (
    os.environ.get(
        "CAPTAIN_EVENT_MODE",
        "challenger",
    )
    .strip()
    .casefold()
)

if EVENT_MODE not in {
    "baseline",
    "challenger",
}:
    raise RuntimeError(
        "CAPTAIN_EVENT_MODE must be "
        "'baseline' or 'challenger'"
    )


fixture_rows = load_json(
    BASE_RUN
    / "fixture_horizon.json"
)

gameweeks = sorted(
    {
        int(
            row["target_gameweek"]
        )
        for row in fixture_rows
        if row.get(
            "target_gameweek"
        )
        is not None
    }
)

if not gameweeks:

    raise RuntimeError(
        "Baseline fixture horizon "
        "contains no gameweeks."
    )

projection_horizon = len(
    gameweeks
)


#
# ============================================================
# RECONSTRUCT EXACT MATERIALIZED SOURCE
#
# We use the canonical snapshot export produced by the old run.
# No HTTP/API/provider refresh occurs.
# ============================================================
#

snapshot_path = (
    BASE_RUN
    / "canonical_parquet"
    / "fact_fpl_snapshot.parquet"
)

snapshots = pd.read_parquet(
    snapshot_path
)


def payload_for(
    provenance_row,
):

    source = str(
        provenance_row["source"]
    )

    entity = str(
        provenance_row["entity"]
    )

    source_record_id = (
        provenance_row.get(
            "raw_snapshot_id"
        )
        or provenance_row.get(
            "cache_key"
        )
    )

    rows = snapshots[
        (
            snapshots[
                "source_provider"
            ].astype(str)
            == source
        )
        & (
            snapshots[
                "entity"
            ].astype(str)
            == entity
        )
    ].copy()

    if source_record_id is not None:

        exact = rows[
            rows[
                "source_record_id"
            ].astype(str)
            == str(
                source_record_id
            )
        ]

        if not exact.empty:

            rows = exact

    if rows.empty:

        raise RuntimeError(
            "Canonical source payload "
            f"not found for "
            f"{source}.{entity} "
            f"record={source_record_id}"
        )

    if len(rows) > 1:

        timestamp = (
            provenance_row.get(
                "source_snapshot_timestamp"
            )
        )

        if timestamp is not None:

            target = pd.Timestamp(
                timestamp
            )

            stamp = pd.to_datetime(
                rows[
                    "snapshot_timestamp"
                ],
                utc=True,
            )

            exact_time = rows[
                stamp == target
            ]

            if not exact_time.empty:

                rows = exact_time

    row = rows.iloc[-1]

    value = row[
        "provider_payload"
    ]

    if isinstance(
        value,
        str,
    ):

        return json.loads(
            value
        )

    if isinstance(
        value,
        dict,
    ):

        return value

    #
    # DuckDB JSON may occasionally
    # materialize as a JSON-compatible
    # scalar wrapper.
    #
    return json.loads(
        str(value)
    )


records = []


for row in provenance:

    payload = payload_for(
        row
    )

    record = CurrentSourceRecord(
        source=str(
            row["source"]
        ),
        entity=str(
            row["entity"]
        ),
        payload=payload,
        known_at=parse_dt(
            row["known_at"]
        ),
        retrieved_at=parse_dt(
            row["retrieved_at"]
        ),
        checksum=str(
            row["checksum"]
        ),
        source_version=str(
            row["source_version"]
        ),
        raw_snapshot_id=(
            row.get(
                "raw_snapshot_id"
            )
        ),
        cache_key=(
            row.get(
                "cache_key"
            )
        ),
        from_cache=bool(
            row.get(
                "from_cache",
                True,
            )
        ),
        source_snapshot_timestamp=(
            parse_dt(
                row.get(
                    "source_snapshot_timestamp"
                )
            )
        ),
    )

    records.append(
        record
    )


bootstrap_rows = [
    row
    for row in records
    if row.entity
    in {
        "bootstrap_static",
        "bootstrap",
    }
]

fixture_source_rows = [
    row
    for row in records
    if row.entity
    == "fixtures"
]

live_rows = [
    row
    for row in records
    if row.entity.startswith(
        "event_live_"
    )
]


if len(bootstrap_rows) != 1:

    raise RuntimeError(
        "Expected exactly one bootstrap "
        f"record, found "
        f"{len(bootstrap_rows)}"
    )

if len(fixture_source_rows) != 1:

    raise RuntimeError(
        "Expected exactly one fixtures "
        f"record, found "
        f"{len(fixture_source_rows)}"
    )


def live_number(
    record,
):

    match = re.search(
        r"(\d+)$",
        record.entity,
    )

    return (
        int(
            match.group(1)
        )
        if match
        else 999
    )


live_rows.sort(
    key=live_number
)

core_ids = {
    id(
        bootstrap_rows[0]
    ),
    id(
        fixture_source_rows[0]
    ),
    *(
        id(row)
        for row in live_rows
    ),
}

optional_rows = [
    row
    for row in records
    if id(row)
    not in core_ids
]


materialized_source = (
    CurrentSourceData(
        bootstrap=(
            bootstrap_rows[0]
        ),
        fixtures=(
            fixture_source_rows[0]
        ),
        event_live=tuple(
            live_rows
        ),
        optional=tuple(
            optional_rows
        ),
        warnings=(),
    )
)


#
# ============================================================
# EXACT PREDICTION CONTEXT
# ============================================================
#

PredictionContext = (
    current.PredictionContext
)

# PredictionContext uses strict datetime validation.
# JSON persistence serializes prediction_timestamp as text,
# therefore reconstruct the aware datetime explicitly before
# validating the replay context.
context_payload = dict(
    context_payload
)

context_payload[
    "prediction_timestamp"
] = parse_dt(
    context_payload[
        "prediction_timestamp"
    ]
)

if hasattr(
    PredictionContext,
    "model_validate",
):

    context = (
        PredictionContext
        .model_validate(
            context_payload
        )
    )

else:

    context = (
        PredictionContext(
            **context_payload
        )
    )


#
# ============================================================
# LOAD ONLY EVIDENCE-BACKED PROXIES
#
# Unmatched players do NOT receive the
# positional-prior proxy here.
# They stay exact V1.
# ============================================================
#

proxy_payload = load_json(
    PROXY_PATH
)

proxy_by_player = {
    str(
        row["player_id"]
    ):
    float(
        row[
            "goal_allocation_proxy_per90"
        ]
    )
    for row in proxy_payload[
        "players"
    ]
    if row.get(
        "used_historical_total_xg"
    )
}


if len(
    proxy_by_player
) != int(
    proxy_payload.get(
        "historical_matches",
        len(
            proxy_by_player
        ),
    )
):

    #
    # Sidecar top-level payload does not
    # necessarily carry historical_matches;
    # count itself remains authoritative.
    #
    pass


#
# ============================================================
# PATCH RUNTIME STACK IN MEMORY ONLY
# ============================================================
#

original_stack = (
    current._runtime_model_stack
)


def replay_stack(
    active_manifest,
):

    (
        team_model,
        minutes_model,
        talent_model,
        event_model,
    ) = original_stack(
        active_manifest
    )

    #
    # Both sides of CAPTAIN-063 must start
    # from frozen EventModels V1.
    #
    if (
        event_model.__class__.__name__
        != "EventModels"
    ):

        raise RuntimeError(
            "Runtime event baseline changed: "
            f"{event_model.__class__.__name__}"
        )

    if EVENT_MODE == "baseline":

        return (
            team_model,
            minutes_model,
            talent_model,
            event_model,
        )

    return (
        team_model,
        minutes_model,
        talent_model,
        GoalAllocationEventModels(
            proxy_by_player
        ),
    )


class NoRefreshSource:

    def refresh(
        self,
        context,
    ):

        raise RuntimeError(
            "Network/provider refresh is forbidden "
            "in CAPTAIN-060B."
        )


output_root = (
    WORK_ROOT
    / "output"
)

canonical_db = (
    WORK_ROOT
    / "canonical.duckdb"
)


pipeline = (
    CurrentPredictionPipeline(
        NoRefreshSource(),
        project_root=ROOT,
        config=(
            CurrentPipelineConfig(
                canonical_database=(
                    canonical_db
                ),
                output_root=(
                    output_root
                ),
                simulations_per_fixture=(
                    simulation_count
                ),
                random_seed=seed,
                projection_horizon_gameweeks=(
                    projection_horizon
                ),
            )
        ),
        progress=lambda message: None,
    )
)


current._runtime_model_stack = (
    replay_stack
)

try:

    challenger = pipeline.run(
        context,
        materialized_source=(
            materialized_source
        ),
    )

finally:

    current._runtime_model_stack = (
        original_stack
    )


CHALLENGER_RUN = (
    challenger.run_directory
)


#
# ============================================================
# FAIRNESS CHECK
#
# Everything upstream of Event Model
# must remain exactly equal.
# ============================================================
#

artifact_names = (
    "current_players",
    "fixture_horizon",
    "team_strength",
    "minutes",
    "tactical_context",
    "player_talent",
    "candidate_pool",
)

upstream = {}

for name in artifact_names:

    old_path = (
        BASE_RUN
        / f"{name}.json"
    )

    new_path = (
        challenger.artifacts[
            name
        ]
    )

    old = load_json(
        old_path
    )

    new = load_json(
        new_path
    )

    upstream[name] = (
        old == new
    )


upstream_pass = all(
    upstream.values()
)


if not upstream_pass:

    bad = [
        key
        for key, value
        in upstream.items()
        if not value
    ]

    raise RuntimeError(
        "Replay is not isolated to Event Model. "
        "Upstream mismatch: "
        + ", ".join(bad)
    )


#
# ============================================================
# LOAD PROJECTIONS
# ============================================================
#

old_players = load_json(
    BASE_RUN
    / "current_players.json"
)

old_proj = load_json(
    BASE_RUN
    / "player_projections.json"
)

new_proj = load_json(
    CHALLENGER_RUN
    / "player_projections.json"
)

new_events = load_json(
    CHALLENGER_RUN
    / "event_projections.json"
)


names = {
    str(
        row["player_id"]
    ):
    (
        row.get(
            "display_name"
        )
        or row.get(
            "name"
        )
        or str(
            row["player_id"]
        )
    )
    for row in old_players
}

positions = {
    str(
        row["player_id"]
    ):
    str(
        row["position"]
    ).upper()
    for row in old_players
}


def projection_map(
    rows,
):

    result = {}

    for row in rows:

        pid = str(
            row["player_id"]
        )

        result[
            pid
        ] = {
            int(
                gw[
                    "target_gameweek"
                ]
            ):
            float(
                gw[
                    "expected_points"
                ]
            )
            for gw in row.get(
                "gameweeks",
                []
            )
        }

    return result


old_ev = projection_map(
    old_proj
)

new_ev = projection_map(
    new_proj
)


#
# ============================================================
# APPEARANCE BY GAMEWEEK
# ============================================================
#

fixture_to_gw = {
    str(
        row["fixture_id"]
    ):
    int(
        row["target_gameweek"]
    )
    for row in fixture_rows
    if row.get(
        "target_gameweek"
    )
    is not None
}


minutes_rows = load_json(
    BASE_RUN
    / "minutes.json"
)

appearance_parts = (
    defaultdict(list)
)


for row in minutes_rows:

    fixture_id = str(
        row["fixture_id"]
    )

    gw = fixture_to_gw.get(
        fixture_id
    )

    if gw is None:
        continue

    pid = str(
        row["player_id"]
    )

    appearance_parts[
        (
            pid,
            gw,
        )
    ].append(
        float(
            row[
                "p_appearance"
            ]
        )
    )


p_app = {}


for key, probabilities in (
    appearance_parts.items()
):

    p_app[key] = (
        1.0
        - math.prod(
            1.0 - value
            for value
            in probabilities
        )
    )


#
# ============================================================
# KEY PLAYER RESOLUTION
# ============================================================
#

def resolve_player(
    aliases,
    position=None,
):

    if isinstance(
        aliases,
        str,
    ):
        aliases = (
            aliases,
        )

    normalized = [
        norm(value)
        for value in aliases
    ]

    exact = [
        pid
        for pid, name
        in names.items()
        if (
            position is None
            or positions.get(pid)
            == position
        )
        and norm(name)
        in normalized
    ]

    if len(exact) == 1:
        return exact[0]

    fuzzy = [
        pid
        for pid, name
        in names.items()
        if (
            position is None
            or positions.get(pid)
            == position
        )
        and any(
            token
            in norm(name)
            for token
            in normalized
        )
    ]

    if len(fuzzy) == 1:
        return fuzzy[0]

    return None


key_specs = (
    (
        "Haaland",
        (
            "Haaland",
            "Erling Haaland",
        ),
        "FWD",
    ),
    (
        "Palmer",
        (
            "Palmer",
            "Cole Palmer",
        ),
        "MID",
    ),
    (
        "B.Fernandes",
        (
            "B.Fernandes",
            "Bruno Fernandes",
        ),
        "MID",
    ),
    (
        "Tavernier",
        (
            "Tavernier",
        ),
        "MID",
    ),
)


key_ids = {
    label:
        resolve_player(
            aliases,
            position,
        )
    for (
        label,
        aliases,
        position,
    )
    in key_specs
}


#
# ============================================================
# TOP-10 COMPARISON
# ============================================================
#

top10 = {}


for gw in gameweeks:

    old_rows = sorted(
        (
            (
                pid,
                values.get(
                    gw,
                    0.0,
                ),
            )
            for pid, values
            in old_ev.items()
        ),
        key=lambda item:
            (
                -item[1],
                item[0],
            ),
    )[:10]

    new_rows = sorted(
        (
            (
                pid,
                values.get(
                    gw,
                    0.0,
                ),
            )
            for pid, values
            in new_ev.items()
        ),
        key=lambda item:
            (
                -item[1],
                item[0],
            ),
    )[:10]

    top10[str(gw)] = {
        "baseline": [
            {
                "player_id": pid,
                "name": names.get(
                    pid,
                    pid,
                ),
                "position": positions.get(
                    pid
                ),
                "ev": ev,
            }
            for pid, ev
            in old_rows
        ],
        "challenger": [
            {
                "player_id": pid,
                "name": names.get(
                    pid,
                    pid,
                ),
                "position": positions.get(
                    pid
                ),
                "ev": ev,
            }
            for pid, ev
            in new_rows
        ],
    }


#
# ============================================================
# FIXED SAVED WC: EXACT XI + C/VC
#
# Brute-force 15 choose 11.
# All positions may captain.
# ============================================================
#

squad_specs = (
    (
        "Sels",
        ("Sels",),
        "GK",
    ),
    (
        "Kelleher",
        ("Kelleher",),
        "GK",
    ),
    (
        "Maatsen",
        ("Maatsen",),
        "DEF",
    ),
    (
        "Justin",
        ("Justin",),
        "DEF",
    ),
    (
        "De Cuyper",
        (
            "De Cuyper",
            "DeCuyper",
        ),
        "DEF",
    ),
    (
        "Egan",
        (
            "Egan",
            "Egan-Riley",
        ),
        "DEF",
    ),
    (
        "Giles",
        ("Giles",),
        "DEF",
    ),
    (
        "Groß",
        (
            "Groß",
            "Gross",
        ),
        "MID",
    ),
    (
        "Tavernier",
        ("Tavernier",),
        "MID",
    ),
    (
        "B.Fernandes",
        (
            "B.Fernandes",
            "Bruno Fernandes",
        ),
        "MID",
    ),
    (
        "Szoboszlai",
        ("Szoboszlai",),
        "MID",
    ),
    (
        "Palmer",
        (
            "Palmer",
            "Cole Palmer",
        ),
        "MID",
    ),
    (
        "Calvert-Lewin",
        (
            "Calvert-Lewin",
            "Calvert Lewin",
        ),
        "FWD",
    ),
    (
        "Haaland",
        (
            "Haaland",
            "Erling Haaland",
        ),
        "FWD",
    ),
    (
        "Evanilson",
        (
            "Evanilson",
        ),
        "FWD",
    ),
)


resolved_squad = {}

unresolved_squad = []


for (
    label,
    aliases,
    position,
) in squad_specs:

    pid = resolve_player(
        aliases,
        position,
    )

    if pid is None:

        unresolved_squad.append(
            label
        )

    else:

        resolved_squad[
            label
        ] = pid


def legal_xi(
    xi,
):

    counts = defaultdict(
        int
    )

    for pid in xi:

        counts[
            positions[pid]
        ] += 1

    return (
        counts["GK"] == 1
        and 3
        <= counts["DEF"]
        <= 5
        and 2
        <= counts["MID"]
        <= 5
        and 1
        <= counts["FWD"]
        <= 3
    )


def best_fixed_squad(
    squad_ids,
    ev_map,
    gw,
):

    best = None

    for xi in combinations(
        squad_ids,
        11,
    ):

        if not legal_xi(
            xi
        ):
            continue

        xi_ev = sum(
            ev_map.get(
                pid,
                {},
            ).get(
                gw,
                0.0,
            )
            for pid in xi
        )

        for captain in xi:

            captain_ev = (
                ev_map.get(
                    captain,
                    {},
                ).get(
                    gw,
                    0.0,
                )
            )

            captain_app = (
                p_app.get(
                    (
                        captain,
                        gw,
                    ),
                    0.0,
                )
            )

            for vice in xi:

                if vice == captain:
                    continue

                vice_ev = (
                    ev_map.get(
                        vice,
                        {},
                    ).get(
                        gw,
                        0.0,
                    )
                )

                bonus = (
                    captain_ev
                    + (
                        1.0
                        - captain_app
                    )
                    * vice_ev
                )

                total = (
                    xi_ev
                    + bonus
                )

                candidate = (
                    total,
                    bonus,
                    xi_ev,
                    captain,
                    vice,
                    tuple(
                        sorted(
                            xi
                        )
                    ),
                )

                if (
                    best is None
                    or candidate
                    > best
                ):

                    best = candidate

    if best is None:

        raise RuntimeError(
            f"No legal XI for GW{gw}"
        )

    return {
        "total_ev": best[0],
        "captain_bonus": best[1],
        "xi_ev": best[2],
        "captain_id": best[3],
        "captain": names.get(
            best[3],
            best[3],
        ),
        "vice_id": best[4],
        "vice": names.get(
            best[4],
            best[4],
        ),
        "xi": [
            names.get(
                pid,
                pid,
            )
            for pid in best[5]
        ],
    }


captaincy = {}


if not unresolved_squad:

    squad_ids = tuple(
        resolved_squad.values()
    )

    for gw in gameweeks:

        captaincy[
            str(gw)
        ] = {
            "baseline": (
                best_fixed_squad(
                    squad_ids,
                    old_ev,
                    gw,
                )
            ),
            "challenger": (
                best_fixed_squad(
                    squad_ids,
                    new_ev,
                    gw,
                )
            ),
        }


#
# ============================================================
# KEY PLAYER DELTAS
# ============================================================
#

key_player_rows = []


for gw in gameweeks:

    for (
        label,
        pid,
    ) in key_ids.items():

        if pid is None:
            continue

        old = old_ev.get(
            pid,
            {},
        ).get(
            gw,
            0.0,
        )

        new = new_ev.get(
            pid,
            {},
        ).get(
            gw,
            0.0,
        )

        key_player_rows.append({
            "gameweek": gw,
            "label": label,
            "player_id": pid,
            "baseline_ev": old,
            "challenger_ev": new,
            "delta": new - old,
        })


#
# ============================================================
# EVENT ENVELOPE INVARIANT
# ============================================================
#

def team_envelopes(
    rows,
):

    result = {}

    for event in rows:

        fid = str(
            event["fixture_id"]
        )

        for side in (
            "home",
            "away",
        ):

            team = event[
                side
            ]

            result[
                (
                    fid,
                    side,
                )
            ] = (
                float(
                    team[
                        "expected_team_goals"
                    ]
                ),
                float(
                    team[
                        "own_goal_expected_goals"
                    ]
                ),
                float(
                    team[
                        "allocated_player_goals"
                    ]
                ),
                float(
                    team[
                        "unassigned_expected_goals"
                    ]
                ),
            )

    return result


old_envelopes = team_envelopes(
    baseline_events
)

new_envelopes = team_envelopes(
    new_events
)


team_goal_envelope_exact = all(
    math.isclose(
        old_envelopes[key][0],
        new_envelopes[key][0],
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    for key in old_envelopes
)


#
# ============================================================
# REPORT
# ============================================================
#

report = {
    "status": (
        "DEVELOPMENT_ONLY_EXACT_OFFLINE_REPLAY"
    ),
    "baseline_run": str(
        BASE_RUN.relative_to(
            ROOT
        )
    ),
    "challenger_run": str(
        CHALLENGER_RUN.relative_to(
            ROOT
        )
    ),
    "prediction_timestamp": (
        context.prediction_timestamp.isoformat()
    ),
    "simulation_count": (
        simulation_count
    ),
    "seed": seed,
    "gameweeks": gameweeks,
    "proxy_players": len(
        proxy_by_player
    ),
    "network_refresh": False,
    "upstream_exact": upstream,
    "upstream_pass": (
        upstream_pass
    ),
    "team_goal_envelope_exact": (
        team_goal_envelope_exact
    ),
    "baseline_event_versions": (
        baseline_event_versions
    ),
    "challenger_event_versions": sorted(
        {
            str(
                row.get(
                    "model_version"
                )
            )
            for row in new_events
        }
    ),
    "key_players": (
        key_player_rows
    ),
    "top10": top10,
    "fixed_wc_unresolved": (
        unresolved_squad
    ),
    "fixed_wc_captaincy": (
        captaincy
    ),
}


REPORT_PATH.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


#
# ============================================================
# COMPACT OUTPUT
# ============================================================
#

print(
    "=== CAPTAIN-060B EXACT OFFLINE REPLAY ==="
)

print(
    "prediction:",
    context.prediction_timestamp.isoformat(),
)

print(
    "GW:",
    gameweeks,
)

print(
    "simulations:",
    simulation_count,
)

print(
    "seed:",
    seed,
)

print(
    "proxy evidence players:",
    len(
        proxy_by_player
    ),
)

print(
    "network refresh: NO"
)

print(
    "upstream exact:",
    (
        "PASS"
        if upstream_pass
        else "FAIL"
    ),
)

print(
    "team xG envelope:",
    (
        "PASS"
        if team_goal_envelope_exact
        else "FAIL"
    ),
)

print(
    "challenger event:",
    report[
        "challenger_event_versions"
    ],
)


print()
print(
    "=== KEY PLAYER EV ==="
)


for gw in gameweeks:

    print(
        f"GW{gw}"
    )

    for row in key_player_rows:

        if row[
            "gameweek"
        ] != gw:
            continue

        print(
            f"  {row['label']:<14} "
            f"{row['baseline_ev']:.3f}"
            f" -> "
            f"{row['challenger_ev']:.3f} "
            f"({row['delta']:+.3f})"
        )


print()
print(
    "=== TOP 5 BY GW ==="
)


for gw in gameweeks:

    old = top10[
        str(gw)
    ][
        "baseline"
    ][:5]

    new = top10[
        str(gw)
    ][
        "challenger"
    ][:5]

    print(
        f"GW{gw}"
    )

    print(
        "  OLD:",
        " | ".join(
            f"{row['name']} "
            f"{row['ev']:.2f}"
            for row in old
        ),
    )

    print(
        "  NEW:",
        " | ".join(
            f"{row['name']} "
            f"{row['ev']:.2f}"
            for row in new
        ),
    )


print()
print(
    "=== FIXED WC C/VC ==="
)


if unresolved_squad:

    print(
        "SKIPPED unresolved:",
        ", ".join(
            unresolved_squad
        ),
    )

else:

    for gw in gameweeks:

        rows = captaincy[
            str(gw)
        ]

        old = rows[
            "baseline"
        ]

        new = rows[
            "challenger"
        ]

        print(
            f"GW{gw}: "
            f"OLD C={old['captain']} "
            f"VC={old['vice']} "
            f"bonus={old['captain_bonus']:.3f} "
            f"| NEW C={new['captain']} "
            f"VC={new['vice']} "
            f"bonus={new['captain_bonus']:.3f}"
        )


print()
print(
    "report:",
    REPORT_PATH.relative_to(
        ROOT
    ),
)

print(
    "challenger run:",
    CHALLENGER_RUN.relative_to(
        ROOT
    ),
)

print(
    "Production/frozen artifacts modified: NO"
)
