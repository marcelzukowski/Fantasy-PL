from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import desktop_app.chip_runner as runner
import fpl_engine.decision.chip_strategy as strategy
from fpl_engine.decision.chip_timing import (
    ExactChipTimingConfig,
    ExactChipTimingPolicy,
    ExactFutureChipOpportunity,
)
from fpl_engine.decision.chip_screen import ExactChipScreenEntry


@pytest.mark.parametrize(
    ("gameweek", "exact", "strategic", "period_end"),
    [
        (5, tuple(range(5, 11)), tuple(range(11, 20)), 19),
        (16, tuple(range(16, 20)), (), 19),
        (18, (18, 19), (), 19),
        (19, (19,), (), 19),
        (20, tuple(range(20, 26)), tuple(range(26, 39)), 38),
        (35, (35, 36, 37, 38), (), 38),
        (38, (38,), (), 38),
    ],
)
def test_chip_strategy_horizons_stop_at_reset_boundary(gameweek, exact, strategic, period_end):
    result = strategy.chip_strategy_horizons(gameweek)
    assert result.exact_gameweeks == exact
    assert result.strategic_gameweeks == strategic
    assert result.chip_period_end == period_end
    assert all(gw <= period_end for gw in (*exact, *strategic))


def test_strategic_scan_rejects_a_gameweek_after_the_chip_reset():
    with pytest.raises(strategy.ChipStrategyError, match="chip-period boundary"):
        strategy.strategic_chip_opportunities(
            player_rows=(), positions={}, projections_by_id={}, p_appearance_by_gameweek={},
            current_player_ids=(), selling_prices_tenths={}, bank_tenths=0,
            strategic_gameweeks=(20,), chip_period_end_gameweek=19,
        )


def test_strategic_scan_uses_existing_ev_paths_with_one_unlimited_candidate(monkeypatch):
    calls = []

    def fixed(*, chip, first_gameweek, horizon, **_):
        calls.append(("fixed", chip, first_gameweek, horizon))
        bonus = {"normal": 0.0, "triple_captain": 3.0, "bench_boost": 4.0}[chip]
        return SimpleNamespace(weighted_total_ev=100.0 + bonus)

    def unlimited(*, chip, first_gameweek, horizon, portfolio_limit, **_):
        calls.append(("unlimited", chip, first_gameweek, horizon, portfolio_limit))
        bonus = {"free_hit": 5.0, "wildcard": 6.0}[chip]
        return SimpleNamespace(selected=SimpleNamespace(exact=SimpleNamespace(weighted_total_ev=100.0 + bonus)))

    monkeypatch.setattr(strategy, "evaluate_exact_chip_squad", fixed)
    monkeypatch.setattr(strategy, "rank_unlimited_candidates_exact", unlimited)

    result = strategy.strategic_chip_opportunities(
        player_rows=({"player_id": "p", "position": "GK", "team_id": "t", "current_price": 50},),
        positions={"p": "GK"}, projections_by_id={}, p_appearance_by_gameweek={},
        current_player_ids=("p",), selling_prices_tenths={"p": 50}, bank_tenths=0,
        strategic_gameweeks=(11,), chip_period_end_gameweek=19,
    )

    assert {chip: rows[0].incremental_ev for chip, rows in result.opportunities.items()} == {
        "triple_captain": 3.0, "bench_boost": 4.0, "free_hit": 5.0, "wildcard": 6.0,
    }
    assert ("unlimited", "free_hit", 11, 1, 1) in calls
    assert ("unlimited", "wildcard", 11, 6, 1) in calls
    assert result.unavailable_gameweeks == {}


def test_strategic_scan_never_evaluates_an_unavailable_wildcard(monkeypatch):
    calls = []

    def fixed(*, chip, **_):
        calls.append(("fixed", chip))
        return SimpleNamespace(weighted_total_ev=100.0)

    def unlimited(*, chip, **_):
        calls.append(("unlimited", chip))
        return SimpleNamespace(selected=SimpleNamespace(exact=SimpleNamespace(weighted_total_ev=100.0)))

    monkeypatch.setattr(strategy, "evaluate_exact_chip_squad", fixed)
    monkeypatch.setattr(strategy, "rank_unlimited_candidates_exact", unlimited)

    result = strategy.strategic_chip_opportunities(
        player_rows=(), positions={}, projections_by_id={}, p_appearance_by_gameweek={},
        current_player_ids=("p",), selling_prices_tenths={"p": 50}, bank_tenths=0,
        strategic_gameweeks=(11,), chip_period_end_gameweek=19,
        available_chips=("triple_captain", "bench_boost", "free_hit"),
    )

    assert ("unlimited", "wildcard") not in calls
    assert result.opportunities["wildcard"] == ()
    assert {chip for _, chip in calls} == {"normal", "triple_captain", "bench_boost", "free_hit"}


def test_strategic_bundle_is_3000_model_only_and_reused(tmp_path, monkeypatch):
    root = tmp_path
    base_bundle = root / "production" / "shadow_projection_bundle.json"
    base_bundle.parent.mkdir(parents=True)
    base_bundle.write_text("{}", encoding="utf-8")
    returned = root / "strategy-run"
    returned.mkdir()
    (returned / "shadow_projection_bundle.json").write_text("{}", encoding="utf-8")
    seen = []

    def fake_run(command, **_):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout=str(returned) + "\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    state = SimpleNamespace(season="2026/27", current_gameweek=5)
    bundle, reused = runner._strategic_bundle(
        project_root=root, state=state, base_bundle=base_bundle,
        strategic_gameweeks=tuple(range(11, 20)), chip_period_end=19,
    )
    cached, cached_reused = runner._strategic_bundle(
        project_root=root, state=state, base_bundle=base_bundle,
        strategic_gameweeks=tuple(range(11, 20)), chip_period_end=19,
    )

    assert bundle == returned / "shadow_projection_bundle.json"
    assert cached == bundle and not reused and cached_reused
    assert len(seen) == 1
    assert "--simulation-count" in seen[0]
    assert seen[0][seen[0].index("--simulation-count") + 1] == "3000"
    assert seen[0][seen[0].index("--gameweek") + 1] == "11"
    assert seen[0][seen[0].index("--projection-horizon-gameweeks") + 1] == "9"
    assert "--skip-market-shadow" in seen[0]
    assert "THE_ODDS_API_KEY" not in " ".join(seen[0])


def test_strategic_preflight_skips_before_subprocess_when_prerequisite_is_missing(tmp_path):
    horizons = strategy.chip_strategy_horizons(5)
    reason = runner._strategic_preflight(
        bundle_path=tmp_path / "shadow_projection_bundle.json",
        horizons=horizons,
        available=("free_hit", "bench_boost", "triple_captain"),
    )
    assert reason == "missing production minutes prerequisite"


def test_strategic_bundle_refuses_a_range_past_the_active_chip_period(tmp_path):
    state = SimpleNamespace(season="2026/27", current_gameweek=5)
    with pytest.raises(runner.DesktopChipError, match="chip-period boundary"):
        runner._strategic_bundle(
            project_root=tmp_path,
            state=state,
            base_bundle=tmp_path / "base.json",
            strategic_gameweeks=tuple(range(11, 21)),
            chip_period_end=19,
        )


def test_strategy_inputs_use_the_new_bundle_identity_not_the_near_term_identity(tmp_path, monkeypatch):
    captured = {}

    def fake_load(path, **_):
        captured.update(__import__("json").loads(Path(path).read_text(encoding="utf-8")))
        return "loaded"

    monkeypatch.setattr(runner, "load_squad_state", fake_load)
    result = runner._strategy_inputs(
        {
            "prediction_timestamp": "2026-09-15T12:00:00+00:00",
            "season": "2026/27",
            "current_gameweek": 5,
            "players": [],
            "bank": 0,
        },
        tmp_path / "strategic" / "shadow_projection_bundle.json",
        tmp_path,
    )

    assert result == "loaded"
    assert captured == {"players": [], "bank": 0}


def _entry(chip, delta):
    return ExactChipScreenEntry(
        chip=chip, baseline_ev=100.0, chip_ev=100.0 + delta, incremental_ev=delta,
        squad_player_ids=frozenset({"p"}), captain_id="p", vice_id="v",
        formation="3-4-3", candidate_count=1,
    )


def test_existing_timing_tolerance_keeps_current_chip_for_small_later_difference():
    screen = SimpleNamespace(
        triple_captain=_entry("triple_captain", 5.0),
        bench_boost=_entry("bench_boost", 0.0),
        free_hit=_entry("free_hit", 0.0),
        wildcard=_entry("wildcard", 0.0),
    )
    config = ExactChipTimingConfig(6, 1.0, 0.25, 8.0, 6.0)
    decision = ExactChipTimingPolicy(config).decide(
        screen=screen,
        future_opportunities={
            "triple_captain": (
                ExactFutureChipOpportunity("triple_captain", 17, 100.0, 105.2, 5.2),
            ),
        },
        available_chips=("triple_captain",),
    )
    assert decision.chosen_chip == "triple_captain"
