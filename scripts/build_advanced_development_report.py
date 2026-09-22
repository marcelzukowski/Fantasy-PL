"""Build the targeted ADV development audit without selecting a champion."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import time

from fpl_engine.current_history import load_strict_historical_context
from fpl_engine.features.advanced_event_data import development_feature_matrix
from fpl_engine.models.events import load_bps_support_matrix
from fpl_engine.validation.advanced import walk_forward_advanced_talent


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonable(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _metric_delta(active: dict, challenger: dict, component: str, metric: str):
    old = active["components"][component]["candidates"]
    new = challenger["components"][component]["candidates"]
    old_name = next(name for name in old if not name.startswith("raw_per90"))
    new_name = next(name for name in new if not name.startswith("raw_per90"))
    return {
        "active_model": old_name, "active_value": old[old_name].get(metric),
        "challenger_model": new_name, "challenger_value": new[new_name].get(metric),
        "delta_challenger_minus_active": (
            new[new_name][metric] - old[old_name][metric]
            if new[new_name].get(metric) is not None and old[old_name].get(metric) is not None
            else None
        ),
    }


def build(root: Path) -> tuple[Path, Path]:
    started = time.perf_counter()
    base_path = root / "data/processed/backtests/strict/2024-25/real_model_backtest.json"
    adv_path = root / "data/processed/backtests/strict/2024-25/advanced_challenger/real_model_backtest.json"
    holdout_path = root / "data/processed/backtests/strict/2023-24/real_model_backtest.json"
    active, advanced, prior_development = _load(base_path), _load(adv_path), _load(holdout_path)
    if advanced.get("candidate_mode") != "ADV_CHALLENGER":
        raise RuntimeError("advanced report input is not an ADV challenger run")
    if advanced.get("leakage_violations") != 0:
        raise RuntimeError("ADV challenger run has leakage violations")
    if advanced["components"]["projections"]["simulation"]["simulations_per_fixture"] < 512:
        raise RuntimeError("ADV projection comparison requires at least 512 simulations per fixture")
    # These seasons have already been observed, so both are development evidence.
    context = load_strict_historical_context(
        root, ("2024-25",), prediction_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    observations = [row for rows in context.talent.values() for row in rows]
    talent = walk_forward_advanced_talent(observations, minimum_history=2)
    matrix = development_feature_matrix()
    bps = load_bps_support_matrix(root)
    by_talent = {row.model_id: _jsonable(asdict(row)) for row in talent.candidates}
    xa_v1 = by_talent["player_talent_empirical_bayes_v1"]["xa"]
    xa_v2 = by_talent["player_talent_reliability_v2"]["xa"]
    xa_exp = by_talent["exponentially_weighted_per90_v1"]["xa"]
    v2_beats_v1 = xa_v2["mae"] < xa_v1["mae"]
    v2_beats_baseline = xa_v2["mae"] < xa_exp["mae"]
    feature_rows = [_jsonable(asdict(row)) for row in matrix.entries]
    bps_rows = [_jsonable(asdict(row)) for row in bps.entries]
    assist_comparison = {
        "2023/24_development": prior_development["components"]["event_models"]["candidates"],
        "2024/25_active_v1": active["components"]["event_models"]["candidates"],
        "2024/25_challenger": advanced["components"]["event_models"]["candidates"],
        "primary_delta": _metric_delta(active, advanced, "event_models", "assist_log_loss"),
    }
    assist_improved = assist_comparison["primary_delta"]["delta_challenger_minus_active"] < 0
    advanced_coherent = next(
        value for key, value in advanced["components"]["event_models"]["candidates"].items()
        if not key.startswith("raw_per90")
    )
    active_raw_assist = active["components"]["event_models"]["candidates"][
        "raw_per90_baseline_v1"
    ]["assist_log_loss"]
    assist_beats_simple_baseline = advanced_coherent["assist_log_loss"] < active_raw_assist
    assist_comparison["challenger_beats_active_raw_per90"] = assist_beats_simple_baseline
    goal_impact = {
        "contract": "V1 goal process retained; only Player Talent inputs may differ",
        "goal_log_loss": _metric_delta(active, advanced, "event_models", "goal_log_loss"),
        "goal_poisson_deviance": _metric_delta(
            active, advanced, "event_models", "goal_poisson_deviance",
        ),
    }
    projection_effect = {}
    for horizon in ("1", "3", "6"):
        old = active["components"]["projections"]["horizons"].get(horizon)
        new = advanced["components"]["projections"]["horizons"].get(horizon)
        projection_effect[horizon] = {"active_v1": old, "advanced_challenger": new}
    report = {
        "report_version": 1,
        "status": "DEVELOPMENT_ONLY_KEEP_TESTING",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_manifest": "data/processed/advanced/baseline_manifest_20260910T113453Z.json",
        "active_champions_updated": False,
        "advanced_components": [
            "temporal multi-source event contracts and provider-season-feature availability",
            "safe derived npxG requiring temporally safe xG and penalty-xG",
            "Player Talent V2 reliability-aware shrinkage and field-specific decay",
            "transfer/role regime weighting and evidence-gated league translation",
            "probabilistic temporal role and set-piece allocations",
            "coherent Assist V2 allocation with complete-feature gating",
            "strong-prior team penalty/taker/conversion decomposition",
            "2026/27 BPS source-support matrix",
            "data-quality/confidence metadata independent of expected value",
            "manifest-driven current inference registration for V1/V2",
        ],
        "historical_source_coverage": {
            "2023/24": {
                "status": "existing STRICT report available; ADV raw replay unavailable",
                "gameweeks": prior_development["coverage"]["gameweeks"],
                "prediction_points": prior_development["coverage"]["prediction_points"],
                "source_versions": prior_development["source_versions"],
                "limitation": "Vaastav RawStore receipt referenced by the materialization is absent locally; no aggregate-report reconstruction was used.",
            },
            "2024/25": {
                "status": "ADV STRICT replay complete",
                "gameweeks": advanced["coverage"]["gameweeks"],
                "prediction_points": advanced["coverage"]["prediction_points"],
                "source_versions": advanced["source_versions"],
            },
        },
        "feature_availability_matrix": feature_rows,
        "npxg_shooting_coverage": {
            "historical_development": "UNAVAILABLE: Vaastav has expected_goals but no independent penalty-xG or shot-event fields, so it is not treated as npxG.",
            "current": "PARTIAL/CURRENT_ONLY through API-Football where supplied; never back-projected.",
            "fallback": "Position/role priors remain explicit and confidence is reduced.",
        },
        "player_talent_results": {
            "season": "2024/25", "walk_forward": True,
            "prediction_rows": len(talent.prediction_order), "candidates": by_talent,
            "v2_beats_v1_xa_mae": v2_beats_v1,
            "v2_beats_exponential_baseline_xa_mae": v2_beats_baseline,
            "npxg_result": "UNAVAILABLE; no safe observed target",
        },
        "assist_results": assist_comparison,
        "goal_model_impact": goal_impact,
        "tactical_set_piece_contribution": {
            "implementation": "temporal probability distributions with explicit unknown mass",
            "strict_metric": None,
            "reason": "No complete historical pre-deadline role/set-piece feed is materialized for the development seasons.",
        },
        "bps_completeness": {
            "before": "implicit/partial V1 simulation coverage without a component audit artifact",
            "after_supported_fraction": bps.completeness,
            "season": bps.season, "support_matrix": bps_rows,
            "rule": "unsupported actions remain NULL/unmodelled rather than observed zero",
        },
        "ablations": {
            "talent": [
                {"stage": "Talent V1", "xa_mae": xa_v1["mae"]},
                {"stage": "+ improved recency/shrinkage (Talent V2)", "xa_mae": xa_v2["mae"],
                 "delta": xa_v2["mae"] - xa_v1["mae"]},
                {"stage": "+ shooting/npxG", "xa_mae": None, "status": "UNAVAILABLE"},
                {"stage": "+ role/tactical context", "xa_mae": None, "status": "UNAVAILABLE"},
                {"stage": "+ set pieces", "xa_mae": None, "status": "UNAVAILABLE"},
            ],
            "assists": [
                {"stage": "raw per90", "metric": "assist_log_loss",
                 "value": active["components"]["event_models"]["candidates"]["raw_per90_baseline_v1"]["assist_log_loss"]},
                {"stage": "Assist V1", "metric": "assist_log_loss",
                 "value": active["components"]["event_models"]["candidates"]["coherent_events_v1"]["assist_log_loss"]},
                {"stage": "+ Talent V2 / coherent Assist V2", "metric": "assist_log_loss",
                 "value": next(value["assist_log_loss"] for key, value in advanced["components"]["event_models"]["candidates"].items() if not key.startswith("raw_per90"))},
                {"stage": "+ creation features", "value": None, "status": "UNAVAILABLE"},
                {"stage": "+ set pieces/full", "value": None, "status": "UNAVAILABLE"},
            ],
        },
        "projection_effect_1_3_6gw": projection_effect,
        "simulation": {
            **advanced["components"]["projections"]["simulation"],
            "required_minimum_met": advanced["components"]["projections"]["simulation"]["simulations_per_fixture"] >= 512,
        },
        "confidence_data_quality": {
            "factors": ["provider coverage", "event-feature coverage", "minutes confidence",
                        "talent reliability", "role certainty", "set-piece certainty",
                        "availability certainty", "BPS completeness", "cross-league certainty"],
            "expected_value_modified": False,
            "missing_factors": "retained explicitly and reduce metadata confidence",
        },
        "runtime": {
            "talent_walk_forward_seconds": time.perf_counter() - started,
            "backtest_runtime_seconds": advanced.get("runtime_seconds"),
        },
        "leakage_violations": advanced["leakage_violations"] + talent.leakage_violations,
        "improved_components": [
            name for name, improved in (
                ("Player Talent V2 vs V1 xA MAE", v2_beats_v1),
                ("Coherent Assist V2 vs coherent Assist V1 log loss", assist_improved),
            )
            if improved
        ],
        "not_improved_or_unproven": [
            "Player Talent V2 vs exponentially weighted xA baseline" if not v2_beats_baseline else None,
            "Coherent Assist V2 vs coherent Assist V1" if not assist_improved else None,
            "Coherent Assist V2 vs frozen raw-per90 baseline" if not assist_beats_simple_baseline else None,
            "shooting/npxG enrichment (historical source unavailable)",
            "role/set-piece increments (historical source unavailable)",
            "defensive contribution (underlying events unavailable)",
        ],
        "final_holdout_candidates": {
            "player_talent_v2": ("candidate only; requires untouched final holdout"
                                 if v2_beats_v1 and v2_beats_baseline
                                 else "not supported over all simpler development baselines"),
            "coherent_assists_v2": ("candidate only; requires untouched final holdout"
                                    if assist_improved and assist_beats_simple_baseline
                                    else "not supported over all simpler development baselines"),
            "production_promotion": "PROHIBITED in this development block",
        },
        "untouched_2022_23_readiness": {
            "status": "NOT_READY",
            "metrics_inspected": False,
            "missing": ["STRICT fixture revision materialization", "strictly prior fplcache snapshots",
                        "RawStore-backed Vaastav outcomes", "provider-season feature availability audit"],
            "next_boundary": "materialize and integrity-audit sources without calculating final performance metrics",
        },
        "limitations": [
            "2023/24 and 2024/25 are development seasons because their metrics were previously observed.",
            "No ML challenger was added because current evidence does not justify extra complexity.",
            "No unsupported cross-league coefficient was estimated.",
        ],
    }
    report["not_improved_or_unproven"] = [
        value for value in report["not_improved_or_unproven"] if value is not None
    ]
    output = root / "data/processed/advanced"
    output.mkdir(parents=True, exist_ok=True)
    machine, human = output / "advanced_development_report.json", output / "advanced_development_report.md"
    machine.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Targeted ADV development report", "",
        "**DEVELOPMENT ONLY — KEEP_TESTING. No production champion was changed.**", "",
        f"2024/25 ADV replay used {report['simulation']['simulations_per_fixture']} simulations per fixture across {len(report['historical_source_coverage']['2024/25']['gameweeks'])} Gameweeks with {report['leakage_violations']} leakage violations.", "",
        "## Player Talent", "",
        f"Talent V1 xA MAE: `{xa_v1['mae']:.6f}`; Talent V2: `{xa_v2['mae']:.6f}`; exponential baseline: `{xa_exp['mae']:.6f}` on `{xa_v2['observations']}` rows.", "",
        "Observed historical npxG and shooting targets remain unavailable, so those ablations are not assigned zero-valued results.", "",
        "## Events and projections", "",
        f"Assist log-loss delta (challenger - active): `{assist_comparison['primary_delta']['delta_challenger_minus_active']:.6f}`.",
        "The V1 goal process was retained. Full 1/3/6GW metric objects are in the machine-readable report.", "",
        "Historical role, set-piece and defensive-action increments remain unproven because no complete pre-deadline feed is materialized.", "",
        "## Decision", "",
        "All V2 implementations remain challengers. The active manifest stays KEEP_TESTING and byte-reproducible. 2022/23 remains untouched and is not ready until its STRICT sources are materialized and audited.", "",
    ]
    human.write_text("\n".join(lines), encoding="utf-8")
    return machine, human


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(*(str(path) for path in build(args.root.resolve())), sep="\n")
