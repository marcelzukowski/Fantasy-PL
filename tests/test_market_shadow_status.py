from datetime import timedelta
import json

import pytest

from desktop_app.run_center import discover_projection_runs
from desktop_app.market_shadow_status import resolve_market_shadow
from tests.test_desktop_run_center import AT, ROOT, _projection_run


def sidecar(root, payload=None):
    bundle = _projection_run(root, "model-run", AT)
    path = bundle.parent / "run_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("market_shadow")
    path.write_text(json.dumps(manifest))
    observed = (AT + timedelta(minutes=1)).isoformat()
    record = {
        "artifact_version": "current_market_shadow_v2",
        "status": "SUCCESS",
        "production_influence": False,
        "production_run_directory": str(bundle.parent),
        "production_metadata": {
            "pipeline_version": None,
            "model_versions": [],
            "simulator_version": manifest["simulation"]["simulator_version"],
            "simulation_count": manifest["simulation"]["simulations_per_fixture"],
            "base_seed": 42,
            "seed_strategy": None,
        },
        "season": "2026/27",
        "current_gameweek": 5,
        "model_prediction_timestamp": AT.isoformat(),
        "market_snapshot_timestamp": observed,
        "shadow_prediction_timestamp": observed,
        "generated_at": observed,
        "coverage": {
            "mapped_fixture_count": 10,
            "current_gameweek_fixture_count": 10,
            "quote_count": 1,
            "pit_usable_quote_count": 1,
        },
        "comparison": {
            "model_prediction_timestamp": AT.isoformat(),
            "prediction_timestamp": observed,
        },
        "normalized_market_probabilities": [{"known_at": AT.isoformat()}],
    }
    if payload:
        record.update(payload)
    destination = root / "data/processed/market_shadow/2026-27/model-run"
    destination.mkdir(parents=True)
    path = destination / "market_shadow_20260917T081600Z.json"
    path.write_text(json.dumps(record))
    return path, record


def test_completed_sidecar_overrides_missing_manifest_and_exposes_both_cutoffs(tmp_path):
    _, record = sidecar(tmp_path)
    run = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)[0]
    # The old observation is stale today; its successful completion still exists.
    assert run.market_shadow_status == "STALE"
    assert run.market_shadow_coverage == "10/10"
    assert record["model_prediction_timestamp"] in run.market_shadow_detail
    assert record["market_snapshot_timestamp"] in run.market_shadow_detail
    assert "completed" in run.market_shadow_detail.lower()
    assert "advisory" in run.detail.lower()


@pytest.mark.parametrize(
    "changes",
    [
        {"production_influence": True},
        {"artifact_version": "unsupported"},
        {"coverage": {"mapped_fixture_count": 20, "current_gameweek_fixture_count": 10}},
        {"comparison": None},
        {"market_snapshot_timestamp": "invalid"},
    ],
)
def test_invalid_success_is_unavailable_not_completed(tmp_path, changes):
    sidecar(tmp_path, changes)
    run = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)[0]
    assert run.market_shadow_status == "UNAVAILABLE"
    assert run.market_shadow_coverage is None


@pytest.mark.parametrize(
    "changes",
    [
        {"season": "2025/26"},
        {"current_gameweek": 6},
        {"production_run_directory": "other-run"},
        {"model_prediction_timestamp": (AT - timedelta(days=1)).isoformat()},
        {"production_metadata": {"simulator_version": "other"}},
    ],
)
def test_incompatible_sidecar_is_stale(tmp_path, changes):
    sidecar(tmp_path, changes)
    run = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)[0]
    assert run.market_shadow_status == "STALE"
    assert run.market_shadow_coverage is None


@pytest.mark.parametrize("source,expected", [("FAILED", "FAILED"), ("SKIPPED", "NOT_RUN")])
def test_explicit_failure_and_skip_are_not_replaced_by_success(tmp_path, source, expected):
    sidecar(
        tmp_path,
        {
            "status": source,
            "market_snapshot_timestamp": None,
            "comparison": None,
            "normalized_market_probabilities": [],
        },
    )
    run = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)[0]
    assert run.market_shadow_status == expected


def test_corrupt_sidecar_does_not_fall_back_to_manifest_success(tmp_path):
    path, _ = sidecar(tmp_path)
    path.write_text("{broken")
    run = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)[0]
    assert run.market_shadow_status == "UNAVAILABLE"


@pytest.mark.parametrize("status,expected", [("SUCCESS", "COMPLETED"), ("PARTIAL", "PARTIAL")])
@pytest.mark.parametrize("market_offset", [-1, 1])
def test_fresh_pit_safe_completion_including_quotes_before_model_cutoff(
    tmp_path, status, expected, market_offset
):
    path, record = sidecar(
        tmp_path,
        {
            "status": status,
            "market_snapshot_timestamp": (AT + timedelta(minutes=market_offset)).isoformat(),
        },
    )
    run_dir = tmp_path / "data/processed/predictions/2026-27/model-run"
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    resolved = resolve_market_shadow(
        tmp_path,
        run_dir,
        manifest,
        season="2026/27",
        gameweek=5,
        model_timestamp=AT.isoformat(),
        now=AT + timedelta(minutes=2),
    )
    assert resolved[0] == expected and resolved[1] == "10/10"
    assert path.exists() and record["production_influence"] is False


def test_existing_real_success_sidecar_is_reported_without_mutation():
    source = (
        ROOT
        / "data/processed/market_shadow/2026-27/20261022T071806Z/market_shadow_20261022T081106Z.json"
    )
    if not source.exists():
        pytest.skip("local frozen audit artifact not distributed with repository")
    raw = source.read_bytes()
    run = discover_projection_runs(ROOT, season="2026/27", gameweek=8)[0]
    assert run.run_id == "20261022T071806Z"
    assert run.market_shadow_status == "STALE"
    assert run.market_shadow_coverage == "10/10"
    assert "completed" in run.market_shadow_detail.lower()
    assert source.read_bytes() == raw
