from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import io
import json
import os
import runpy
import shutil

from fpl_engine.current import (
    CurrentPipelineConfig,
    CurrentPredictionPipeline,
)


ROOT = Path(".").resolve()

SOURCE_SCRIPT = (
    ROOT
    / "scripts"
    / "captain066c_integrated_offline_replay.py"
)

OUT_ROOT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)


if not SOURCE_SCRIPT.exists():

    raise RuntimeError(
        "CAPTAIN-066C replay script missing."
    )


#
# ============================================================
# 1. Recreate the already validated explicit branches.
#
# We reuse CAPTAIN-066C only as an exact materialized-source
# fixture. Its console output is suppressed here.
# ============================================================
#

buffer = io.StringIO()

with redirect_stdout(
    buffer
):

    ns = runpy.run_path(
        str(
            SOURCE_SCRIPT
        ),
        run_name=(
            "captain066c_for_067c"
        ),
    )


ROOT_066C = ns[
    "ROOT"
]

context = ns[
    "context"
]

materialized_source = ns[
    "materialized_source"
]

simulation_count = ns[
    "simulation_count"
]

seed = ns[
    "seed"
]

projection_horizon = ns[
    "projection_horizon"
]

explicit_challenger_run = ns[
    "CHALLENGER_RUN"
]

core_artifacts = tuple(
    ns[
        "CORE_ARTIFACTS"
    ]
)


if (
    ROOT_066C.resolve()
    != ROOT.resolve()
):

    raise RuntimeError(
        "CAPTAIN-066C project root mismatch."
    )


#
# ============================================================
# 2. Clean dedicated default-path output
# ============================================================
#

if OUT_ROOT.exists():

    shutil.rmtree(
        OUT_ROOT
    )


OUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


#
# ============================================================
# 3. Provider guard
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
            "IN CAPTAIN-067C"
        )


source = NoRefreshSource()


#
# ============================================================
# 4. IMPORTANT:
#
# Construct config WITHOUT:
#
#   goal_allocation_proxy_enabled=
#   goal_allocation_source_season=
#
# This is the actual promoted default path.
# ============================================================
#

config = CurrentPipelineConfig(
    canonical_database=(
        OUT_ROOT
        / "canonical.duckdb"
    ),
    output_root=(
        OUT_ROOT
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
)


default_config_pass = (
    config.goal_allocation_proxy_enabled
    is True
)


source_season_default_pass = (
    config.goal_allocation_source_season
    is None
)


pipeline = CurrentPredictionPipeline(
    source,
    project_root=ROOT,
    config=config,
)


#
# Keep simulator identical to the validated replay.
#
previous_simulator = os.environ.get(
    "FPL_SIMULATOR_CHALLENGER"
)

os.environ.pop(
    "FPL_SIMULATOR_CHALLENGER",
    None,
)


try:

    result = pipeline.run(
        context,
        materialized_source=(
            materialized_source
        ),
    )

finally:

    if previous_simulator is None:

        os.environ.pop(
            "FPL_SIMULATOR_CHALLENGER",
            None,
        )

    else:

        os.environ[
            "FPL_SIMULATOR_CHALLENGER"
        ] = previous_simulator


DEFAULT_RUN = (
    result.run_directory
)


#
# ============================================================
# 5. Exact comparison against explicit True branch
# ============================================================
#

def load_json(
    path,
):

    return json.loads(
        Path(
            path
        ).read_text(
            encoding="utf-8"
        )
    )


def exact_json(
    left,
    right,
):

    left = Path(
        left
    )

    right = Path(
        right
    )


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


artifact_exact = {}


for name in core_artifacts:

    artifact_exact[
        name
    ] = exact_json(
        explicit_challenger_run
        / name,
        DEFAULT_RUN
        / name,
    )


core_exact_pass = all(
    artifact_exact.values()
)


#
# Proxy artifact must also be exactly the same.
#
proxy_name = (
    "goal_allocation_proxy.json"
)

proxy_exact_pass = exact_json(
    explicit_challenger_run
    / proxy_name,
    DEFAULT_RUN
    / proxy_name,
)


#
# ============================================================
# 6. Runtime event version
# ============================================================
#

events = load_json(
    DEFAULT_RUN
    / "event_projections.json"
)


event_versions = sorted({
    str(
        row[
            "model_version"
        ]
    )
    for row in events
})


event_version_pass = (
    event_versions
    == [
        "event_models_goal_allocation_proxy_v1"
    ]
)


#
# ============================================================
# 7. Manifest policy
# ============================================================
#

manifest = load_json(
    DEFAULT_RUN
    / "run_manifest.json"
)


policy = manifest.get(
    "goal_allocation_policy"
)


promotion = (
    manifest
    .get(
        "promotion_candidates",
        {},
    )
    .get(
        "goal_allocation_proxy"
    )
)


policy_pass = (
    isinstance(
        policy,
        dict,
    )
    and policy.get(
        "default_enabled"
    )
    is True
    and policy.get(
        "enabled_this_run"
    )
    is True
    and policy.get(
        "selection"
    )
    == "goal_allocation_proxy_v1"
    and policy.get(
        "explicit_v1_rollback"
    )
    is False
    and policy.get(
        "runtime_event_model"
    )
    == "GoalAllocationEventModels"
    and policy.get(
        "silent_fallback_allowed"
    )
    is False
)


promotion_pass = (
    isinstance(
        promotion,
        dict,
    )
    and promotion.get(
        "status"
    )
    == "PROMOTION_CANDIDATE"
    and promotion.get(
        "matched_count"
    )
    == 399
    and promotion.get(
        "current_player_count"
    )
    == 656
    and promotion.get(
        "talent_npxg_modified"
    )
    is False
    and promotion.get(
        "penalty_process_modified"
    )
    is False
    and promotion.get(
        "team_goal_envelope_modified"
    )
    is False
)


#
# ============================================================
# 8. Network contract
# ============================================================
#

offline_pass = (
    source.refresh_calls
    == 0
)


#
# ============================================================
# 9. Final acceptance gate
# ============================================================
#

gate = all((
    default_config_pass,
    source_season_default_pass,
    offline_pass,
    core_exact_pass,
    proxy_exact_pass,
    event_version_pass,
    policy_pass,
    promotion_pass,
))


report = {
    "status": (
        "CAPTAIN_067C_"
        "DEFAULT_RUNTIME_ACCEPTANCE"
    ),
    "default_config_enabled": (
        config
        .goal_allocation_proxy_enabled
    ),
    "default_source_season_config": (
        config
        .goal_allocation_source_season
    ),
    "resolved_historical_source": (
        promotion.get(
            "source_season"
        )
        if isinstance(
            promotion,
            dict,
        )
        else None
    ),
    "network_refresh_calls": (
        source.refresh_calls
    ),
    "event_versions": (
        event_versions
    ),
    "core_artifact_exact": (
        artifact_exact
    ),
    "proxy_exact": (
        proxy_exact_pass
    ),
    "policy_pass": (
        policy_pass
    ),
    "promotion_pass": (
        promotion_pass
    ),
    "explicit_challenger_run": str(
        explicit_challenger_run
        .relative_to(
            ROOT
        )
    ),
    "default_run": str(
        DEFAULT_RUN.relative_to(
            ROOT
        )
    ),
    "gate": (
        gate
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
    "=== CAPTAIN-067C "
    "DEFAULT RUNTIME ACCEPTANCE ==="
)

print(
    "config default=True:",
    (
        "PASS"
        if default_config_pass
        else "FAIL"
    ),
)

print(
    "source season auto-resolution:",
    (
        "PASS"
        if source_season_default_pass
        and (
            promotion is not None
            and promotion.get(
                "source_season"
            )
            == "2025-26"
        )
        else "FAIL"
    ),
)

print(
    "network refresh:",
    (
        "NO"
        if offline_pass
        else "FAIL"
    ),
)


print()
print(
    "=== EXACT DEFAULT VS EXPLICIT TRUE ==="
)

for name, value in (
    artifact_exact.items()
):

    print(
        f"{name:<30} "
        f"{'PASS' if value else 'FAIL'}"
    )


print(
    f"{proxy_name:<30} "
    f"{'PASS' if proxy_exact_pass else 'FAIL'}"
)


print()
print(
    "event versions:",
    event_versions,
)

print(
    "event model:",
    (
        "PASS"
        if event_version_pass
        else "FAIL"
    ),
)

print(
    "manifest policy:",
    (
        "PASS"
        if policy_pass
        else "FAIL"
    ),
)

print(
    "promotion provenance:",
    (
        "PASS"
        if promotion_pass
        else "FAIL"
    ),
)


print()
print(
    "DEFAULT RUNTIME GATE:",
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


if not gate:

    raise RuntimeError(
        "CAPTAIN-067C default runtime "
        "acceptance failed."
    )
