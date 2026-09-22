"""Compare the frozen 2023/24 holdout with 2024/25 development evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


STRATEGIES = ("ROLL", "greedy_1GW", "static_weighted_6GW", "optimizer_V1", "optimizer_V2")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_frozen(root: Path, manifest: dict) -> dict:
    mismatches = []
    for relative, expected in manifest["file_sha256"].items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append({"path": relative, "expected": expected, "actual": actual})
    if mismatches:
        raise RuntimeError(f"frozen policy changed after holdout: {mismatches}")
    return {"verified": True, "files_verified": len(manifest["file_sha256"]), "mismatches": []}


def _projection(report: dict) -> dict:
    output = {}
    for horizon, row in report["components"]["projections"]["horizons"].items():
        output[horizon] = {
            "sample_size": row["coverage"]["evaluated"],
            "metrics": row["metrics"],
            "segments": row["segments"],
        }
    return output


def _strategies(report: dict) -> dict:
    selected = report["reference_strategy"]["strategies"]
    fields = (
        "total_points", "transfer_count", "hit_gameweeks", "hit_points", "points_per_transfer",
        "average_decision_margin", "average_action_stability", "chip_gameweeks", "diagnostic_counts",
        "final_bank", "final_free_transfers",
    )
    return {
        name: {
            **{field: selected[name][field] for field in fields},
            "roll_selections": sum(
                row["action"] == "ROLL_FT" for row in selected[name]["decision_diagnostics"]
            ),
            "short_term_reversals": selected[name]["diagnostic_counts"]["reversed_within_3gw"],
        }
        for name in STRATEGIES
    }


def finalize(root: Path) -> tuple[Path, Path]:
    output = root / "data/processed/backtests/strict/2023-24"
    frozen = _load(output / "frozen_policy_manifest.json")
    holdout = _load(output / "real_model_backtest.json")
    development = _load(root / "data/processed/backtests/strict/2024-25/real_model_backtest.json")
    source = _load(root / "data/interim/strict/2023-24/source_manifest.json")
    fixtures = _load(root / "data/interim/strict/2023-24/fixture_schedule_manifest.json")
    coverage = _load(output / "coverage_boundary_report.json")
    integrity = _verify_frozen(root, frozen)
    holdout_strategies = _strategies(holdout)
    development_strategies = _strategies(development)
    holdout_order = sorted(STRATEGIES, key=lambda name: holdout_strategies[name]["total_points"], reverse=True)
    development_order = sorted(STRATEGIES, key=lambda name: development_strategies[name]["total_points"], reverse=True)
    combined_order = sorted(
        STRATEGIES,
        key=lambda name: holdout_strategies[name]["total_points"] + development_strategies[name]["total_points"],
        reverse=True,
    )
    changed_deadlines = [point for point in source["prediction_points"] if point.get("deadline_changed_from_preseason")]
    report = {
        "report_version": 1,
        "mode": "STRICT",
        "evaluation_role": "HOLDOUT",
        "season": "2023/24",
        "frozen_policy": {
            "path": "data/processed/backtests/strict/2023-24/frozen_policy_manifest.json",
            "manifest_sha256": frozen["manifest_sha256"],
            "status": frozen["status"],
            "integrity_after_metrics": integrity,
        },
        "source_coverage": {
            "prediction_points": len(source["prediction_points"]),
            "gameweeks": [point["gameweek"] for point in source["prediction_points"]],
            "fplcache_repository_ref": source["fplcache_repository_ref"],
            "pre_deadline_snapshots": coverage["source_coverage"]["pre_deadline_fplcache_snapshots"],
            "fixture_repository": fixtures["repository"],
            "fixture_repository_head": fixtures["repository_head_examined"],
            "fixture_unique_commits": fixtures["unique_commits_materialized"],
            "fixture_states": fixtures["canonical_fixture_state"],
            "fixture_missing_gameweeks": fixtures["missing_gameweeks"],
            "vaastav_repository_ref": source["vaastav_repository_ref"],
            "vaastav_rows": source["vaastav"]["rows"],
            "unsafe_columns_excluded": source["vaastav"]["unsafe_columns"],
            "deadlines_changed_from_preseason": len(changed_deadlines),
            "deadline_change_gameweeks": [point["gameweek"] for point in changed_deadlines],
        },
        "leakage_violations": holdout["leakage_violations"],
        "historical_rules": {
            "scoring_version": holdout["components"]["projections"]["scoring_rule_version"],
            "optimizer_version": holdout["reference_strategy"]["optimizer_rule_version"],
            "season": "2023/24",
        },
        "simulation": holdout["components"]["projections"]["simulation"],
        "projection_metrics": _projection(holdout),
        "component_metrics": {
            name: holdout["components"][name]
            for name in ("team_strength", "minutes", "player_talent", "event_models")
        },
        "reference_strategy": {
            "label": holdout["reference_strategy"]["label"],
            "starting_squad": holdout["reference_strategy"]["starting_squad"],
            "starting_bank": holdout["reference_strategy"]["starting_bank"],
            "starting_free_transfers": holdout["reference_strategy"]["starting_free_transfers"],
            "state_carried_without_reset": True,
            "strategies": holdout_strategies,
            "holdout_ranking": holdout_order,
            "statistical_limit": "One deterministic sequential season trajectory; optimizer total-point confidence intervals are unavailable.",
        },
        "development_comparison": {
            "development_season": "2024/25",
            "holdout_season": "2023/24",
            "development_ranking": development_order,
            "holdout_ranking": holdout_order,
            "combined_points_ranking_diagnostic_only": combined_order,
            "strategy_points": {
                name: {
                    "development": development_strategies[name]["total_points"],
                    "holdout": holdout_strategies[name]["total_points"],
                } for name in STRATEGIES
            },
            "component_ranking_changes": {
                "team_strength": False,
                "minutes": False,
                "player_talent_xa": False,
                "event_goals": False,
                "event_assists": False,
                "decision_policy": True,
            },
            "generalized_behavior": [
                "Greedy 1GW avoided hits in both seasons and retained similar action stability.",
                "Optimizer V2 used fewer transfers and fewer hit points than V1 in both seasons.",
                "Team Strength, Minutes, partial-xA Talent and Event candidate rankings were unchanged.",
            ],
            "unstable_behavior": [
                "Optimizer V2 trailed V1 and Greedy in development but beat both on holdout.",
                "Static weighted-6GW ranked fourth in development and first on holdout.",
                "V2 action stability remained low in both seasons.",
            ],
        },
        "final_policy_decision": {
            "recommended_experimental_policy": "greedy_1GW",
            "reason": "It won development, remained competitive on holdout, had the best two-season point total, made no paid transfers, and was materially more stable than V2.",
            "optimizer_promoted": False,
            "champion_manifest_updated": False,
            "champion_status": "KEEP_TESTING",
            "why_no_optimizer_promotion": "V1 and V2 rankings reverse by season, V2 action stability is low, and a single holdout season does not provide an optimizer total-point confidence interval.",
        },
        "remaining_weaknesses": [
            "Player Talent is evaluated for xA only because point-in-time non-penalty xG and shot-event history are unavailable.",
            "Historical pre-match lineups, manager formations and penalty-taker history remain incomplete.",
            "Projection underprediction grows with horizon and 6GW ranking/calibration weakened on holdout.",
            "Sequential strategy uncertainty cannot be estimated from one deterministic season path.",
        ],
        "next_finalization_work": "Run an untouched additional STRICT season or rolling multi-season policy evaluation, add season-level uncertainty for sequential policies, and perform a current-season shadow run before production decisions.",
    }
    machine = output / "holdout_summary.json"
    human = output / "holdout_summary.md"
    machine.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# 2023/24 frozen STRICT holdout", "",
        f"- Frozen manifest: `{frozen['manifest_sha256']}` ({integrity['files_verified']} files reverified)",
        f"- Coverage: 38/38 deadlines; {fixtures['unique_commits_materialized']} fixture commits; leakage: **{holdout['leakage_violations']}**",
        f"- Simulation: **{report['simulation']['simulations_per_fixture']}** per fixture, seed **{report['simulation']['base_seed']}**",
        "", "## Projection metrics", "",
    ]
    for horizon, row in report["projection_metrics"].items():
        metric = row["metrics"]
        lines.append(
            f"- {horizon}GW (n={row['sample_size']}): MAE {metric['mae']['value']:.4f}, "
            f"RMSE {metric['rmse']['value']:.4f}, bias {metric['bias']['value']:.4f}, "
            f"Spearman {metric['spearman']['value']:.4f}, return Brier {metric['return_brier']['value']:.4f}, "
            f"10+ Brier {metric['haul_10_brier']['value']:.4f}."
        )
    lines += ["", "## Sequential reference strategies", ""]
    for name in holdout_order:
        row = holdout_strategies[name]
        lines.append(f"- {name}: {row['total_points']:.0f} points, {row['transfer_count']} transfers, {row['hit_points']} hit points.")
    lines += [
        "", "## Frozen policy decision", "",
        "Recommended experimental policy: **Greedy 1GW**. No optimizer is promoted; champion status remains **KEEP_TESTING**.",
        "", "The static policy won this holdout but changed from fourth on development to first on holdout. "
        "Greedy won development, stayed competitive here, avoided hits in both seasons, and has the best combined diagnostic total.",
        "", "Full component metrics, confidence intervals, position/minutes-risk segments, provenance and decision diagnostics are in the machine-readable reports.", "",
    ]
    human.write_text("\n".join(lines), encoding="utf-8")
    return machine, human


if __name__ == "__main__":
    print(*(str(path) for path in finalize(Path(__file__).resolve().parents[1])), sep="\n")
