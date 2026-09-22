from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import math
import os
import shutil

import pandas as pd

from fpl_engine.current import (
    CurrentPipelineConfig,
    CurrentPredictionPipeline,
    CurrentSourceData,
    CurrentSourceRecord,
)

from fpl_engine.types import (
    PredictionContext,
)


ROOT = Path(".").resolve()

SOURCE_BASE = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

EXPECTED_CHALLENGER = (
    ROOT
    / "scratch"
    / "decision"
    / "captain063_same_source_multiseed"
    / "seed_42"
    / "challenger"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

BUILDER_REFERENCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066a"
    / "goal_allocation_proxy_builder.json"
)

WORK = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066c"
    / "integrated_replay"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066c"
    / "comparison.json"
)


def load_json(
    path: Path,
):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def parse_dt(
    value,
):

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value

    return datetime.fromisoformat(
        str(
            value
        ).replace(
            "Z",
            "+00:00",
        )
    )


def payload_value(
    value,
):

    if isinstance(
        value,
        str,
    ):

        return json.loads(
            value
        )

    return value


#
# ============================================================
# Preconditions
# ============================================================
#

for required in (
    SOURCE_BASE,
    EXPECTED_CHALLENGER,
    BUILDER_REFERENCE,
):

    if not required.exists():

        raise RuntimeError(
            f"Missing required path: "
            f"{required}"
        )


if WORK.exists():

    shutil.rmtree(
        WORK
    )


WORK.mkdir(
    parents=True,
    exist_ok=True,
)


#
# ============================================================
# Context / simulation contract
# ============================================================
#

context_payload = load_json(
    SOURCE_BASE
    / "prediction_context.json"
)

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
        PredictionContext.model_validate(
            context_payload
        )
    )

else:

    context = PredictionContext(
        **context_payload
    )


manifest = load_json(
    SOURCE_BASE
    / "run_manifest.json"
)

simulation_meta = (
    manifest[
        "simulation"
    ]
)

simulation_count = int(
    simulation_meta[
        "simulations_per_fixture"
    ]
)

seed = int(
    simulation_meta[
        "base_seed"
    ]
)


fixture_rows = load_json(
    SOURCE_BASE
    / "fixture_horizon.json"
)

future_gws = sorted({
    int(
        row[
            "target_gameweek"
        ]
    )
    for row in fixture_rows
    if row.get(
        "target_gameweek"
    ) is not None
})


if not future_gws:

    raise RuntimeError(
        "Baseline fixture horizon is empty."
    )


projection_horizon = (
    max(
        future_gws
    )
    - int(
        context.target_gameweek
    )
    + 1
)


#
# ============================================================
# Reconstruct the exact materialized CurrentSourceData
#
# No provider adapter is called.
# ============================================================
#

provenance = load_json(
    SOURCE_BASE
    / "source_provenance.json"
)

snapshot_path = (
    SOURCE_BASE
    / "canonical_parquet"
    / "fact_fpl_snapshot.parquet"
)


if not snapshot_path.exists():

    raise RuntimeError(
        "Baseline fact_fpl_snapshot.parquet "
        "is unavailable."
    )


snapshots = pd.read_parquet(
    snapshot_path
)


required_columns = {
    "source_provider",
    "source_record_id",
    "snapshot_timestamp",
    "entity",
    "provider_payload",
}


missing_columns = (
    required_columns
    - set(
        snapshots.columns
    )
)


if missing_columns:

    raise RuntimeError(
        "Snapshot parquet missing columns: "
        + ", ".join(
            sorted(
                missing_columns
            )
        )
    )


def reconstruct_record(
    item,
):

    source = str(
        item[
            "source"
        ]
    )

    entity = str(
        item[
            "entity"
        ]
    )


    candidates = snapshots[
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


    identifiers = {
        str(
            value
        )
        for value in (
            item.get(
                "raw_snapshot_id"
            ),
            item.get(
                "cache_key"
            ),
        )
        if value not in (
            None,
            "",
        )
    }


    if identifiers:

        identified = candidates[
            candidates[
                "source_record_id"
            ].astype(str).isin(
                identifiers
            )
        ]

        if not identified.empty:

            candidates = (
                identified
            )


    snapshot_timestamp = (
        item.get(
            "source_snapshot_timestamp"
        )
    )


    if snapshot_timestamp:

        target_timestamp = pd.Timestamp(
            parse_dt(
                snapshot_timestamp
            )
        )

        timestamps = pd.to_datetime(
            candidates[
                "snapshot_timestamp"
            ],
            utc=True,
            errors="coerce",
        )

        timed = candidates[
            timestamps
            == target_timestamp
        ]

        if not timed.empty:

            candidates = timed


    if len(
        candidates
    ) != 1:

        raise RuntimeError(
            "Could not resolve unique "
            "materialized source record: "
            f"{source}.{entity}; "
            f"candidates={len(candidates)}"
        )


    row = candidates.iloc[
        0
    ]


    return CurrentSourceRecord(
        source=source,
        entity=entity,
        payload=payload_value(
            row[
                "provider_payload"
            ]
        ),
        known_at=parse_dt(
            item[
                "known_at"
            ]
        ),
        retrieved_at=parse_dt(
            item[
                "retrieved_at"
            ]
        ),
        checksum=str(
            item[
                "checksum"
            ]
        ),
        source_version=str(
            item[
                "source_version"
            ]
        ),
        raw_snapshot_id=(
            item.get(
                "raw_snapshot_id"
            )
        ),
        cache_key=(
            item.get(
                "cache_key"
            )
        ),
        from_cache=bool(
            item.get(
                "from_cache",
                False,
            )
        ),
        source_snapshot_timestamp=(
            parse_dt(
                snapshot_timestamp
            )
            if snapshot_timestamp
            else None
        ),
    )


records = tuple(
    reconstruct_record(
        item
    )
    for item in provenance
)


bootstrap_rows = [
    row
    for row in records
    if row.entity
    == "bootstrap_static"
]

fixture_source_rows = [
    row
    for row in records
    if row.entity
    == "fixtures"
]


if len(
    bootstrap_rows
) != 1:

    raise RuntimeError(
        "Expected exactly one "
        "bootstrap_static record."
    )


if len(
    fixture_source_rows
) != 1:

    raise RuntimeError(
        "Expected exactly one "
        "fixtures record."
    )


event_live = tuple(
    sorted(
        (
            row
            for row in records
            if row.entity.startswith(
                "event_live_"
            )
        ),
        key=lambda row:
            int(
                row.entity.rsplit(
                    "_",
                    1,
                )[-1]
            ),
    )
)


excluded = {
    id(
        bootstrap_rows[0]
    ),
    id(
        fixture_source_rows[0]
    ),
    *(
        id(
            row
        )
        for row in event_live
    ),
}


optional = tuple(
    row
    for row in records
    if id(
        row
    ) not in excluded
)


materialized_source = CurrentSourceData(
    bootstrap=(
        bootstrap_rows[
            0
        ]
    ),
    fixtures=(
        fixture_source_rows[
            0
        ]
    ),
    event_live=(
        event_live
    ),
    optional=(
        optional
    ),
    warnings=(),
)


#
# ============================================================
# Network guard
# ============================================================
#

class NoRefreshSource:

    def __init__(
        self,
    ):

        self.refresh_calls = 0


    def refresh(
        self,
        context,
    ):

        self.refresh_calls += 1

        raise RuntimeError(
            "NETWORK REFRESH FORBIDDEN "
            "IN CAPTAIN-066C"
        )


source_guard = (
    NoRefreshSource()
)


#
# ============================================================
# Run integrated pipeline twice.
#
# IMPORTANT:
# no monkeypatch of _runtime_model_stack.
# ============================================================
#

def run_integrated(
    *,
    label,
    enabled,
):

    case_root = (
        WORK
        / label
    )

    case_root.mkdir(
        parents=True,
        exist_ok=True,
    )


    config = CurrentPipelineConfig(
        canonical_database=(
            case_root
            / "canonical.duckdb"
        ),
        output_root=(
            case_root
            / "output"
        ),
        simulations_per_fixture=(
            simulation_count
        ),
        random_seed=seed,
        history_seasons=(
            "2024-25",
            "2025-26",
        ),
        projection_horizon_gameweeks=(
            projection_horizon
        ),
        goal_allocation_proxy_enabled=(
            enabled
        ),
        goal_allocation_source_season=(
            "2025-26"
            if enabled
            else None
        ),
    )


    pipeline = (
        CurrentPredictionPipeline(
            source_guard,
            project_root=ROOT,
            config=config,
        )
    )


    return pipeline.run(
        context,
        materialized_source=(
            materialized_source
        ),
    )


old_simulator_override = (
    os.environ.get(
        "FPL_SIMULATOR_CHALLENGER"
    )
)


#
# Force frozen simulator V1 for both sides.
#
os.environ[
    "FPL_SIMULATOR_CHALLENGER"
] = "v1"


try:

    baseline_result = (
        run_integrated(
            label="baseline_disabled",
            enabled=False,
        )
    )


    challenger_result = (
        run_integrated(
            label="challenger_enabled",
            enabled=True,
        )
    )

finally:

    if old_simulator_override is None:

        os.environ.pop(
            "FPL_SIMULATOR_CHALLENGER",
            None,
        )

    else:

        os.environ[
            "FPL_SIMULATOR_CHALLENGER"
        ] = old_simulator_override


BASELINE_RUN = (
    baseline_result
    .run_directory
)

CHALLENGER_RUN = (
    challenger_result
    .run_directory
)


#
# ============================================================
# Exact JSON comparisons
# ============================================================
#

CORE_ARTIFACTS = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
    "event_projections.json",
    "player_projections.json",
)


def exact_json(
    left: Path,
    right: Path,
):

    if (
        not left.exists()
        or not right.exists()
    ):

        return False

    return (
        load_json(
            left
        )
        == load_json(
            right
        )
    )


baseline_exact = {
    name:
        exact_json(
            SOURCE_BASE
            / name,
            BASELINE_RUN
            / name,
        )
    for name in (
        CORE_ARTIFACTS
    )
}


challenger_exact = {
    name:
        exact_json(
            EXPECTED_CHALLENGER
            / name,
            CHALLENGER_RUN
            / name,
        )
    for name in (
        CORE_ARTIFACTS
    )
}


baseline_exact_pass = all(
    baseline_exact.values()
)

challenger_exact_pass = all(
    challenger_exact.values()
)


#
# ============================================================
# Proxy artifact contract
# ============================================================
#

baseline_proxy_path = (
    BASELINE_RUN
    / "goal_allocation_proxy.json"
)

challenger_proxy_path = (
    CHALLENGER_RUN
    / "goal_allocation_proxy.json"
)


baseline_proxy_absent = (
    not baseline_proxy_path.exists()
)


if not challenger_proxy_path.exists():

    raise RuntimeError(
        "Enabled integrated pipeline did "
        "not materialize "
        "goal_allocation_proxy.json"
    )


integrated_proxy = load_json(
    challenger_proxy_path
)

reference_proxy = load_json(
    BUILDER_REFERENCE
)


integrated_rows = {
    str(
        row[
            "player_id"
        ]
    ):
    row
    for row in integrated_proxy[
        "rows"
    ]
}


reference_rows = {
    str(
        row[
            "player_id"
        ]
    ):
    row
    for row in reference_proxy[
        "rows"
    ]
}


integrated_evidence = {
    player_id
    for player_id, row
    in integrated_rows.items()
    if row.get(
        "used_historical_total_xg"
    )
}


reference_evidence = {
    player_id
    for player_id, row
    in reference_rows.items()
    if row.get(
        "used_historical_total_xg"
    )
}


proxy_id_pass = (
    integrated_evidence
    == reference_evidence
)


proxy_differences = []


for player_id in sorted(
    integrated_evidence
    & reference_evidence
):

    actual = float(
        integrated_rows[
            player_id
        ][
            "goal_allocation_proxy_per90"
        ]
    )

    expected = float(
        reference_rows[
            player_id
        ][
            "goal_allocation_proxy_per90"
        ]
    )


    if not math.isclose(
        actual,
        expected,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):

        proxy_differences.append({
            "player_id": (
                player_id
            ),
            "expected": (
                expected
            ),
            "actual": (
                actual
            ),
        })


proxy_value_pass = (
    len(
        proxy_differences
    )
    == 0
)


proxy_count_pass = (
    int(
        integrated_proxy[
            "matched_count"
        ]
    )
    == 399
    and len(
        integrated_evidence
    )
    == 399
)


#
# ============================================================
# Event versions
# ============================================================
#

baseline_events = load_json(
    BASELINE_RUN
    / "event_projections.json"
)

challenger_events = load_json(
    CHALLENGER_RUN
    / "event_projections.json"
)


baseline_versions = sorted({
    str(
        row.get(
            "model_version"
        )
    )
    for row in baseline_events
})


challenger_versions = sorted({
    str(
        row.get(
            "model_version"
        )
    )
    for row in challenger_events
})


version_gate = (
    baseline_versions
    == [
        "event_models_v1"
    ]
    and challenger_versions
    == [
        "event_models_goal_allocation_proxy_v1"
    ]
)


#
# ============================================================
# Team-goal envelope
# ============================================================
#

def fixture_map(
    rows,
):

    return {
        str(
            row[
                "fixture_id"
            ]
        ):
        row
        for row in rows
    }


base_fixture_map = (
    fixture_map(
        baseline_events
    )
)

new_fixture_map = (
    fixture_map(
        challenger_events
    )
)


if (
    set(
        base_fixture_map
    )
    != set(
        new_fixture_map
    )
):

    raise RuntimeError(
        "Baseline/challenger fixture "
        "universes differ."
    )


team_envelope_max_delta = 0.0
team_envelope_mismatches = 0


for fixture_id in (
    base_fixture_map
):

    for side in (
        "home",
        "away",
    ):

        baseline_team = (
            base_fixture_map[
                fixture_id
            ][
                side
            ]
        )

        challenger_team = (
            new_fixture_map[
                fixture_id
            ][
                side
            ]
        )


        for field in (
            "expected_team_goals",
            "own_goal_expected_goals",
            "allocated_player_goals",
            "unassigned_expected_goals",
        ):

            left = float(
                baseline_team[
                    field
                ]
            )

            right = float(
                challenger_team[
                    field
                ]
            )

            delta = abs(
                left
                - right
            )

            team_envelope_max_delta = max(
                team_envelope_max_delta,
                delta,
            )


            if delta > 1e-12:

                team_envelope_mismatches += 1


team_envelope_pass = (
    team_envelope_mismatches
    == 0
)


#
# ============================================================
# Final gate
# ============================================================
#

network_refresh_pass = (
    source_guard.refresh_calls
    == 0
)


gate = all((
    network_refresh_pass,
    baseline_proxy_absent,
    baseline_exact_pass,
    challenger_exact_pass,
    proxy_count_pass,
    proxy_id_pass,
    proxy_value_pass,
    version_gate,
    team_envelope_pass,
))


report = {
    "status": (
        "CAPTAIN_066C_"
        "INTEGRATED_OFFLINE_REPLAY"
    ),
    "source_run": str(
        SOURCE_BASE.relative_to(
            ROOT
        )
    ),
    "expected_challenger": str(
        EXPECTED_CHALLENGER.relative_to(
            ROOT
        )
    ),
    "prediction_timestamp": (
        context
        .prediction_timestamp
        .isoformat()
    ),
    "simulation_count": (
        simulation_count
    ),
    "seed": seed,
    "projection_horizon": (
        projection_horizon
    ),
    "network_refresh_calls": (
        source_guard.refresh_calls
    ),
    "baseline_proxy_absent": (
        baseline_proxy_absent
    ),
    "baseline_exact": (
        baseline_exact
    ),
    "challenger_exact": (
        challenger_exact
    ),
    "baseline_versions": (
        baseline_versions
    ),
    "challenger_versions": (
        challenger_versions
    ),
    "integrated_proxy_matches": int(
        integrated_proxy[
            "matched_count"
        ]
    ),
    "integrated_evidence_count": (
        len(
            integrated_evidence
        )
    ),
    "proxy_id_pass": (
        proxy_id_pass
    ),
    "proxy_difference_count": (
        len(
            proxy_differences
        )
    ),
    "proxy_differences": (
        proxy_differences
    ),
    "team_envelope_mismatches": (
        team_envelope_mismatches
    ),
    "team_envelope_max_delta": (
        team_envelope_max_delta
    ),
    "gate": gate,
    "baseline_run": str(
        BASELINE_RUN.relative_to(
            ROOT
        )
    ),
    "challenger_run": str(
        CHALLENGER_RUN.relative_to(
            ROOT
        )
    ),
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-066C "
    "INTEGRATED OFFLINE REPLAY ==="
)

print(
    "prediction:",
    context.prediction_timestamp.isoformat(),
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
    "horizon:",
    projection_horizon,
)

print(
    "network refresh:",
    (
        "NO"
        if network_refresh_pass
        else "FAIL"
    ),
)


print()
print(
    "=== DISABLED SWITCH ==="
)

print(
    "proxy artifact absent:",
    (
        "PASS"
        if baseline_proxy_absent
        else "FAIL"
    ),
)

print(
    "exact original V1:",
    (
        "PASS"
        if baseline_exact_pass
        else "FAIL"
    ),
)


for name, value in (
    baseline_exact.items()
):

    print(
        f"  {name:<28} "
        f"{'PASS' if value else 'FAIL'}"
    )


print()
print(
    "=== ENABLED SWITCH ==="
)

print(
    "proxy matched:",
    integrated_proxy[
        "matched_count"
    ],
)

print(
    "proxy evidence:",
    len(
        integrated_evidence
    ),
)

print(
    "proxy IDs vs 066A:",
    (
        "PASS"
        if proxy_id_pass
        else "FAIL"
    ),
)

print(
    "proxy differences:",
    len(
        proxy_differences
    ),
)

print(
    "exact CAPTAIN-063 challenger:",
    (
        "PASS"
        if challenger_exact_pass
        else "FAIL"
    ),
)


for name, value in (
    challenger_exact.items()
):

    print(
        f"  {name:<28} "
        f"{'PASS' if value else 'FAIL'}"
    )


print()
print(
    "=== EVENT CONTRACT ==="
)

print(
    "baseline versions:",
    baseline_versions,
)

print(
    "challenger versions:",
    challenger_versions,
)

print(
    "version gate:",
    (
        "PASS"
        if version_gate
        else "FAIL"
    ),
)

print(
    "team xG envelope:",
    (
        "PASS"
        if team_envelope_pass
        else "FAIL"
    ),
)

print(
    "team envelope max delta:",
    f"{team_envelope_max_delta:.3e}",
)


print()
print(
    "INTEGRATED REPLAY GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)

print(
    "Production default changed:",
    "NO",
)

print(
    "Production/frozen Event V1 modified:",
    "NO",
)


if not gate:

    raise RuntimeError(
        "CAPTAIN-066C integrated "
        "replay gate failed."
    )
