from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.analysis_trust import (
    AnalysisTrustInputs,
    AnalysisTrustStatus,
    ChipTrustStatus,
    build_analysis_trust,
)
from fpl_engine.planning import PlanningContext

NOW = "2026-09-24T10:00:00+00:00"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _context(*, gameweek=6, run_id="run-6", bank=10):
    return PlanningContext(
        schema_version="planning_context_v1", season="2026/27", gameweek=gameweek,
        deadline="2026-09-26T17:30:00+00:00", player_ids=tuple(f"p{i}" for i in range(15)),
        selling_prices_tenths=tuple((f"p{i}", 50) for i in range(15)), bank_tenths=bank,
        free_transfers=1, chips_used=(("wildcard_h1", False),), projection_run_id=run_id,
        prediction_timestamp=NOW, simulator_version="v22", model_versions=("v22",),
        simulation_count=10_000, optimizer_rule_version=1, scoring_rule_version=1,
        manifest_sha256="a" * 64, artifact_hashes=(("minutes", "b" * 64),),
        fpl_sync_timestamp=NOW, source_state_timestamp=NOW, data_freshness=(),
    )


@dataclass(frozen=True)
class _V3:
    payload: dict


@dataclass(frozen=True)
class _Decision:
    planning_context: PlanningContext | None
    external_mutations: tuple[str, ...] = ()
    created_at: str = NOW
    legacy_unverified: bool = False
    v3_result: _V3 | None = None


def _verified(**overrides):
    context = _context()
    values = dict(
        decision=_Decision(context, v3_result=_V3({"price_signal_status": "UNAVAILABLE"})),
        current_context=context, selected_season="2026/27", selected_gameweek=6,
        artifact_verified=True, deadline=datetime(2026, 9, 26, 17, 30, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return build_analysis_trust(AnalysisTrustInputs(**values))


def test_verified_requires_matching_context_verified_artifacts_and_valid_decision():
    model = _verified()
    assert model.status is AnalysisTrustStatus.VERIFIED
    assert model.core_verified and model.context_status == "MATCH"
    assert "Price signals unavailable" in model.optional_notes


def test_stale_when_material_account_state_projection_or_gw_changes():
    assert _verified(material_state_changed=True).status is AnalysisTrustStatus.STALE
    assert _verified(projection_changed=True).status is AnalysisTrustStatus.STALE
    assert _verified(selected_gameweek=7).status is AnalysisTrustStatus.STALE


def test_invalid_for_artifact_failure_and_hard_context_mismatch():
    assert _verified(artifact_verified=False, artifact_error="hash mismatch").status is AnalysisTrustStatus.INVALID
    assert _verified(current_context=_context(bank=11)).status is AnalysisTrustStatus.INVALID


def test_optional_chip_market_and_price_do_not_invalidate_verified_core():
    model = _verified(chip_state=ChipTrustStatus.RUNNING, market_status="PARTIAL", market_coverage="8/10")
    assert model.status is AnalysisTrustStatus.VERIFIED
    assert model.core_verified
    assert model.chip_status is ChipTrustStatus.RUNNING
    assert "Market data: PARTIAL 8/10" in model.optional_notes


def test_legacy_never_shows_verified():
    model = build_analysis_trust(AnalysisTrustInputs(
        decision=_Decision(None, legacy_unverified=True), selected_season="2026/27", selected_gameweek=6,
    ))
    assert model.status is AnalysisTrustStatus.LEGACY_UNVERIFIED
    assert model.badge_text == "LEGACY / UNVERIFIED"


def test_verified_historical_is_not_compared_with_live_context():
    report_context = _context(gameweek=4, run_id="old-run")
    model = build_analysis_trust(AnalysisTrustInputs(
        decision=_Decision(report_context), historical=True, selected_season="2026/27", selected_gameweek=6,
        current_context=_context(gameweek=6), artifact_verified=True,
    ))
    assert model.status is AnalysisTrustStatus.VERIFIED
    assert model.badge_text == "VERIFIED HISTORICAL"
    assert model.context_status == "HISTORICAL MATCH"


def test_missing_active_decision_after_local_invalidation_is_stale_not_green():
    model = build_analysis_trust(AnalysisTrustInputs(
        decision=None, selected_season="2026/27", selected_gameweek=6, material_state_changed=True,
    ))
    assert model.status is AnalysisTrustStatus.STALE
    assert not model.core_verified


def test_no_decision_is_partial_without_provider_or_account_side_effects():
    model = build_analysis_trust(AnalysisTrustInputs(decision=None))
    assert model.status is AnalysisTrustStatus.PARTIAL



def test_trust_card_is_compact_and_adds_no_nested_scrollbar(qapp):
    from PySide6.QtWidgets import QScrollArea
    from desktop_app.analysis_views import AnalysisTrustCard

    card = AnalysisTrustCard()
    try:
        card.set_model(_verified())
        assert card.badge.text() == "VERIFIED"
        assert not card.findChildren(QScrollArea)
        assert card.optional.isVisible() is False or card.optional.text()
    finally:
        card.deleteLater()


def test_chip_forecast_optional_coverage_is_visible_without_affecting_core_status():
    model = _verified(chip_forecast_status="PARTIAL")
    assert model.status is AnalysisTrustStatus.VERIFIED
    assert model.chip_forecast_status == "PARTIAL"
    assert "Chip forecast: PARTIAL" in model.optional_notes
