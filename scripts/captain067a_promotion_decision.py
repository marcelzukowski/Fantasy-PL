from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(".").resolve()

STRUCTURAL = (
    ROOT
    / "scratch"
    / "decision"
    / "captain064r_structural_audit.json"
)

DEPLOYABLE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain065_deployable_exposure_holdout.json"
)

BUILDER = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066a"
    / "goal_allocation_proxy_builder.json"
)

INTEGRATED = (
    ROOT
    / "scratch"
    / "decision"
    / "captain066c"
    / "comparison.json"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067"
    / "promotion_decision.json"
)


def load(
    path: Path,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing evidence: "
            f"{path.relative_to(ROOT)}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


structural = load(
    STRUCTURAL
)

deployable = load(
    DEPLOYABLE
)

builder = load(
    BUILDER
)

integrated = load(
    INTEGRATED
)


#
# ============================================================
# Mandatory promotion gates
#
# No thresholds are tuned here.
# We only consume previously defined gates.
# ============================================================
#

structural_pass = bool(
    structural[
        "structural_pass"
    ]
)


deployable_pass = bool(
    deployable[
        "holdout_gate"
    ][
        "pass"
    ]
)


builder_rows = (
    builder[
        "rows"
    ]
)


builder_evidence = [
    row
    for row in builder_rows
    if row[
        "used_historical_total_xg"
    ]
]


builder_pass = all((
    int(
        builder[
            "current_player_count"
        ]
    )
    == 656,

    int(
        builder[
            "matched_count"
        ]
    )
    == 399,

    int(
        builder[
            "position_mismatch_count"
        ]
    )
    == 10,

    int(
        builder[
            "no_history_count"
        ]
    )
    == 247,

    int(
        builder[
            "unresolved_vaastav_rows"
        ]
    )
    == 1,

    len(
        builder_evidence
    )
    == 399,
))


integrated_pass = bool(
    integrated[
        "gate"
    ]
)


network_pass = (
    int(
        integrated[
            "network_refresh_calls"
        ]
    )
    == 0
)


baseline_v1_pass = all(
    integrated[
        "baseline_exact"
    ].values()
)


challenger_exact_pass = all(
    integrated[
        "challenger_exact"
    ].values()
)


proxy_pass = all((
    int(
        integrated[
            "integrated_proxy_matches"
        ]
    )
    == 399,

    int(
        integrated[
            "integrated_evidence_count"
        ]
    )
    == 399,

    bool(
        integrated[
            "proxy_id_pass"
        ]
    ),

    int(
        integrated[
            "proxy_difference_count"
        ]
    )
    == 0,
))


team_envelope_pass = (
    int(
        integrated[
            "team_envelope_mismatches"
        ]
    )
    == 0
)


mandatory = {
    "structural_isolation": (
        structural_pass
    ),
    "deployable_historical_holdout": (
        deployable_pass
    ),
    "canonical_builder": (
        builder_pass
    ),
    "integrated_pipeline": (
        integrated_pass
    ),
    "offline_replay": (
        network_pass
    ),
    "disabled_switch_exact_v1": (
        baseline_v1_pass
    ),
    "enabled_switch_exact_challenger": (
        challenger_exact_pass
    ),
    "canonical_proxy_exact": (
        proxy_pass
    ),
    "team_goal_envelope_preserved": (
        team_envelope_pass
    ),
}


promotion_ready = all(
    mandatory.values()
)


#
# ============================================================
# Known limitations remain explicitly documented.
#
# These are not silently reinterpreted as npxG.
# ============================================================
#

limitations = (
    "historical total xG may include penalties; "
    "proxy remains explicitly allocation-only",

    "historical independent penalty-xG is unavailable",

    "FWD-only cross-entropy on the frozen holdout "
    "was slightly worse at alpha=0.55",

    "alpha=0.55 remains frozen from the original "
    "2023-24 -> 2024-25 tuning transition",

    "players without canonical same-position historical "
    "evidence retain exact Event V1 allocation behaviour",
)


decision = (
    "PROMOTE_TO_DEFAULT_WITH_EXPLICIT_V1_ROLLBACK"
    if promotion_ready
    else "KEEP_OPT_IN"
)


report = {
    "decision_version": (
        "captain067_promotion_decision_v1"
    ),

    "candidate": (
        "goal_allocation_proxy_v1"
    ),

    "decision": (
        decision
    ),

    "promotion_ready": (
        promotion_ready
    ),

    "mandatory_gates": (
        mandatory
    ),

    "validated_configuration": {
        "alpha": 0.55,
        "prior_minutes": 600.0,
        "canonical_evidence_players": 399,
        "source_metric": (
            "historical_total_xg_including_penalties"
        ),
        "intended_use": (
            "relative_team_goal_allocation_only"
        ),
    },

    "semantic_invariants": {
        "talent_npxg_modified": False,
        "penalty_process_modified": False,
        "team_goal_envelope_modified": False,
        "frozen_event_v1_modified": False,
    },

    "known_limitations": (
        limitations
    ),

    "rollout_policy": {
        "recommended_default": (
            "goal_allocation_proxy_v1"
            if promotion_ready
            else "event_models_v1"
        ),
        "rollback_model": (
            "event_models_v1"
        ),
        "rollback_must_remain_explicit": True,
        "fallback_for_missing_player_evidence": (
            "exact_event_v1_player_allocation"
        ),
        "silent_fallback_if_builder_fails": False,
    },
}


OUT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-067A "
    "PROMOTION DECISION ==="
)

for name, passed in (
    mandatory.items()
):

    print(
        f"{name:<38} "
        f"{'PASS' if passed else 'FAIL'}"
    )


print()
print(
    "PROMOTION READY:",
    (
        "YES"
        if promotion_ready
        else "NO"
    ),
)

print(
    "DECISION:",
    decision,
)

print()
print(
    "validated alpha:",
    0.55,
)

print(
    "canonical evidence:",
    len(
        builder_evidence
    ),
)

print(
    "default production changed:",
    "NO",
)

print(
    "report:",
    OUT.relative_to(
        ROOT
    ),
)


if not promotion_ready:

    raise RuntimeError(
        "CAPTAIN-067A promotion "
        "gate failed."
    )
