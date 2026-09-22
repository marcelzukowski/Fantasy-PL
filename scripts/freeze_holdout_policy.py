"""Freeze all decision and model parameters before STRICT holdout scoring."""

from __future__ import annotations

from dataclasses import asdict, fields
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from fpl_engine.config.loader import load_fpl_rules_config, load_scoring_rules_config
from fpl_engine.models.events import EventModelConfig
from fpl_engine.models.minutes import MinutesModelConfig
from fpl_engine.models.player_talent import PlayerTalentConfig
from fpl_engine.models.projections import DEFAULT_HORIZON_WEIGHTS
from fpl_engine.models.team_strength import TeamStrengthConfig
from fpl_engine.optimizer import OptimizerV2Config, OptimizerRules
from fpl_engine.simulation import SimulationConfig


POLICY_FILES = (
    "src/fpl_engine/models/team_strength/model.py",
    "src/fpl_engine/models/minutes/model.py",
    "src/fpl_engine/models/player_talent/model.py",
    "src/fpl_engine/models/events/model.py",
    "src/fpl_engine/simulation/fixture.py",
    "src/fpl_engine/models/projections.py",
    "src/fpl_engine/optimizer/core.py",
    "src/fpl_engine/optimizer/v2.py",
    "src/fpl_engine/optimizer/chips.py",
    "docs/03_SIMULATION/scoring_rules/2023_24.yaml",
    "docs/04_OPTIMIZER/fpl_rules/2023_24.yaml",
)


def _normal(value):
    if isinstance(value, Mapping):
        return {str(key): _normal(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normal(item) for item in value]
    return value


def _config(value):
    """Serialize frozen dataclasses without deepcopying immutable mapping proxies."""
    return _normal({field.name: getattr(value, field.name) for field in fields(value)})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root: Path, *, frozen_at: datetime | None = None) -> Path:
    target = root / "data/processed/backtests/strict/2023-24/frozen_policy_manifest.json"
    if target.exists():
        raise RuntimeError("frozen holdout policy already exists; it may not be overwritten")
    at = (frozen_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rules = OptimizerRules.load(root, season="2023/24")
    v2 = OptimizerV2Config.from_rules(rules)
    manifest = {
        "manifest_version": 1,
        "status": "FROZEN_BEFORE_2023_24_METRICS",
        "season": "2023/24",
        "evaluation_role": "STRICT_HOLDOUT",
        "frozen_at": at.isoformat(),
        "prohibition": "Do not change any recorded parameter after observing 2023/24 metrics.",
        "models": {
            "team_strength": _config(TeamStrengthConfig()),
            "minutes": _config(MinutesModelConfig()),
            "player_talent": _config(PlayerTalentConfig()),
            "event_models": _config(EventModelConfig()),
        },
        "simulation": {
            "production": _normal(asdict(SimulationConfig())),
            "holdout_override": {"simulations_per_fixture": 512, "random_seed": 202324},
            "seed_strategy": "SimulationRandom deterministic fixture-scoped derived seed",
        },
        "projection_builder": {"version": "projection_builder_v1", "horizon_weights": list(DEFAULT_HORIZON_WEIGHTS)},
        "decision_policies": {
            "ROLL": {"maximum_transfers": 0},
            "greedy_1GW": {"ranking_objective": "ev_next_1", "maximum_transfers": 1},
            "static_weighted_6GW": {"ranking_objective": "weighted_ev_next_6", "maximum_transfers": 1},
            "optimizer_V1": {"ranking_objective": "weighted_ev_next_6", "maximum_transfers": 2},
            "optimizer_V2": _normal(asdict(v2)),
            "candidate_generation": {
                "v1_and_baselines": "top 6 weighted-6GW plus 2 cheapest per position",
                "v2": "union of top 1GW, 3GW, 6GW, weighted-6GW, value and low-price candidates",
            },
            "ft_option_value": v2.future_transfer_need_probability,
            "indifference_threshold": v2.indifference_margin,
            "beam_width": v2.second_transfer_beam_width,
            "lookahead_steps": int(rules.value("decision_v2", "lookahead", "steps")),
            "lookahead_discount": v2.lookahead_discount,
        },
        "historical_rules": {
            "scoring": _normal(load_scoring_rules_config(root, season="2023/24").model_dump()),
            "optimizer": _normal(rules.raw),
        },
        "file_sha256": {name: _sha(root / name) for name in POLICY_FILES},
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(freeze(Path(__file__).resolve().parents[1]))
