from __future__ import annotations

import json
from pathlib import Path

import pytest

import desktop_app.chip_runner as chip_runner


BASE = {"bundle_sha256": "base", "manifest_sha256": "manifest", "artifact_hashes": [["a", "1"]], "season": "2026/27", "gameweek": 6, "simulator_version": "sim", "simulation_mode": "PRODUCTION", "model_version": "model", "rule_version": "rules", "seed": 42}
STRATEGIC = {**BASE, "bundle_sha256": "strategic", "manifest_sha256": "strategic-manifest"}


def _state():
    return type("State", (), {"season": "2026/27", "current_gameweek": 6})()


def _context(base, strategic, **overrides):
    value = {
        "base_identity": base, "strategic_bundle_identity": strategic,
        "bundle_path": "cached/shadow_projection_bundle.json",
        "simulations_per_fixture": chip_runner.STRATEGIC_SIMULATIONS_PER_FIXTURE,
        "projection_start_gameweek": 12, "projection_gameweeks": list(range(12, 20)),
        "projection_horizon_gameweeks": 8, "chip_period_end": 19,
        "market_shadow": "DISABLED_MODEL_ONLY",
    }
    value.update(overrides)
    return value


def _cache_call(tmp_path, monkeypatch, context):
    root = tmp_path
    cached = root / "cached" / "shadow_projection_bundle.json"; cached.parent.mkdir(); cached.write_text("{}")
    context["bundle_path"] = str(cached)
    base = root / "base.json"; base.write_text("{}")
    path = chip_runner._strategy_context_path(root, season="2026/27", gameweek=6); path.parent.mkdir(parents=True); path.write_text(json.dumps(context))
    monkeypatch.setattr(chip_runner, "_verified_bundle_identity", lambda p: BASE if Path(p) == base else STRATEGIC if Path(p) == cached else None)
    return chip_runner._strategic_bundle(project_root=root, state=_state(), base_bundle=base, strategic_gameweeks=tuple(range(12,20)), chip_period_end=19)


def test_exact_verified_strategic_identity_hits_without_child(tmp_path, monkeypatch):
    monkeypatch.setattr(chip_runner.subprocess, "Popen", lambda *a, **k: pytest.fail("child must not spawn on cache hit"))
    bundle, reused = _cache_call(tmp_path, monkeypatch, _context(BASE, STRATEGIC))
    assert reused and bundle.name == "shadow_projection_bundle.json"


@pytest.mark.parametrize("field,value", [
    ("base_identity", {**BASE, "bundle_sha256": "changed"}),
    ("base_identity", {**BASE, "manifest_sha256": "changed"}),
    ("base_identity", {**BASE, "artifact_hashes": [["a", "changed"]]}),
    ("strategic_bundle_identity", {**STRATEGIC, "simulator_version": "changed"}),
    ("strategic_bundle_identity", {**STRATEGIC, "model_version": "changed"}),
    ("strategic_bundle_identity", {**STRATEGIC, "rule_version": "changed"}),
    ("strategic_bundle_identity", {**STRATEGIC, "seed": 99}),
    ("projection_gameweeks", list(range(13, 21))),
    ("projection_horizon_gameweeks", 7),
    ("simulations_per_fixture", 1),
    ("chip_period_end", 18),
    ("market_shadow", "ENABLED"),
    ("market_shadow", "UNKNOWN"),
    ("market_shadow", None),
    ("base_identity", None),
])
def test_cache_identity_mismatch_does_not_reuse_path(tmp_path, monkeypatch, field, value):
    context = _context(BASE, STRATEGIC); context[field] = value
    monkeypatch.setattr(chip_runner.subprocess, "Popen", lambda *a, **k: pytest.fail("miss reached child as expected"))
    with pytest.raises(pytest.fail.Exception):
        _cache_call(tmp_path, monkeypatch, context)


def test_cache_rejects_missing_market_shadow_mode(tmp_path, monkeypatch):
    context = _context(BASE, STRATEGIC)
    context.pop("market_shadow")
    monkeypatch.setattr(chip_runner.subprocess, "Popen", lambda *a, **k: pytest.fail("miss reached child as expected"))
    with pytest.raises(pytest.fail.Exception):
        _cache_call(tmp_path, monkeypatch, context)


def test_cache_rejects_opposite_market_shadow_direction(tmp_path, monkeypatch):
    # A cached ENABLED artifact must never satisfy the DISABLED_MODEL_ONLY request.
    context = _context(BASE, STRATEGIC, market_shadow="ENABLED")
    monkeypatch.setattr(chip_runner.subprocess, "Popen", lambda *a, **k: pytest.fail("miss reached child as expected"))
    with pytest.raises(pytest.fail.Exception):
        _cache_call(tmp_path, monkeypatch, context)
