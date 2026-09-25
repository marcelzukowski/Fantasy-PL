from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState
from fpl_engine.planning import (
    ChipForecastStatus, ChipOpportunityForecastCache, ChipOpportunityForecastConfig,
    ChipOpportunityForecastError, build_chip_opportunity_forecast,
)

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _projection(player_id, values):
    gameweeks = tuple(
        GameweekPlayerProjection("2026/27", 1, player_id, 5 + offset, AT, (f"f{offset}",), 1,
            value, value, 1.0, {0.5: value}, .2, .5, .4, .2, .1, .05, 80.0,
            {int(value): 1.0}, 1.0)
        for offset, value in enumerate(values)
    )
    return PlayerProjection(player_id, "2026/27", 1, AT, 5, gameweeks,
        values[0], sum(values[:3]), sum(values), values[0], sum(values[:3]), sum(values),
        80.0, 240.0, 480.0, .2, .8, 1.0, ("model",), ("data",), ("features",), ("sim",), (42,), (1,))


def _input(*, gameweek=5, chips=ChipState(), context_id="context-a"):
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = tuple(SquadPlayer(f"p{index}", position, f"club{index // 3}", 50, 50, 50) for index, position in enumerate(positions))
    state = SquadState(players, 10, 2, chips, gameweek, "2026/27", rules.version, AT)
    pool = players + (SquadPlayer("candidate_fwd", "FWD", "new", 50, 50),)
    projections = {
        player.player_id: _projection(player.player_id, tuple(2.0 + (index % 5) + offset * .1 for offset in range(6)))
        for index, player in enumerate(players)
    }
    projections["p14"] = _projection("p14", (12.0, 2.0, 2.0, 2.0, 2.0, 2.0))
    projections["candidate_fwd"] = _projection("candidate_fwd", (15.0, 3.0, 3.0, 3.0, 3.0, 3.0))
    context = SimpleNamespace(prediction_timestamp=AT.isoformat())
    return SimpleNamespace(state=state, rules=rules, projections=projections, player_pool=pool,
                           context_id=context_id, bundle_identity="run-a", planning_context=context)


def _rows(forecast, chip):
    return [row for row in forecast.opportunities if row.chip_type == chip]


def test_used_chip_is_explicitly_unavailable_and_available_chip_is_forecast():
    chips = ChipState(wildcard_h1=False, wildcard_h2=True)
    forecast = build_chip_opportunity_forecast(_input(chips=chips), generated_at=AT)
    assert forecast.status is ChipForecastStatus.AVAILABLE
    assert all(not row.chip_available and row.method == "CHIP_UNAVAILABLE" for row in _rows(forecast, "wildcard"))
    assert all(row.chip_available for row in _rows(forecast, "triple_captain"))


def test_half_season_boundary_uses_existing_canonical_chip_availability():
    chips = ChipState(wildcard_h1=False, wildcard_h2=True)
    first_half = build_chip_opportunity_forecast(
        _input(gameweek=19, chips=chips), config=ChipOpportunityForecastConfig(horizon_gameweeks=2), generated_at=AT,
    )
    assert first_half.forecast_end_gw == 19
    assert _rows(first_half, "wildcard")[0].chip_available is False
    second_half = build_chip_opportunity_forecast(
        _input(gameweek=20, chips=chips), config=ChipOpportunityForecastConfig(horizon_gameweeks=1), generated_at=AT,
    )
    assert _rows(second_half, "wildcard")[0].chip_available is True


def test_tc_and_static_bench_boost_use_existing_lineup_semantics():
    forecast = build_chip_opportunity_forecast(_input(), generated_at=AT)
    tc = _rows(forecast, "triple_captain")
    assert tc[0].candidate_captain_id == "p14"
    assert tc[0].estimated_incremental_ev > tc[1].estimated_incremental_ev
    bb = _rows(forecast, "bench_boost")[0]
    assert bb.method == "STATIC_SQUAD_APPROXIMATION"
    assert bb.estimated_incremental_ev == pytest.approx(bb.chip_value - bb.baseline_value)


def test_free_hit_screens_then_runs_at_most_one_exact_static_evaluation_and_wc_is_diagnostic_only():
    forecast = build_chip_opportunity_forecast(_input(), generated_at=AT)
    fh = _rows(forecast, "free_hit")
    exact = [row for row in fh if row.method == "SCREENED_EXACT_STATIC_SQUAD"]
    assert len(exact) <= 1
    assert exact and exact[0].estimated_incremental_ev is not None
    assert all(row.estimated_incremental_ev is None for row in fh if row not in exact)
    assert {row.method for row in _rows(forecast, "wildcard")} == {"DIAGNOSTIC_ONLY"}
    assert forecast.metrics["exact_evaluations"] == len(exact)
    assert set(forecast.metrics["per_chip_runtime_seconds"]) == {"triple_captain", "bench_boost", "free_hit", "wildcard"}
    assert all(value >= 0.0 for value in forecast.metrics["per_chip_runtime_seconds"].values())


def test_context_scoped_cache_and_mismatch_protection():
    cache = ChipOpportunityForecastCache()
    first = build_chip_opportunity_forecast(_input(context_id="a"), cache=cache, generated_at=AT)
    second = build_chip_opportunity_forecast(_input(context_id="a"), cache=cache, generated_at=AT)
    other = build_chip_opportunity_forecast(_input(context_id="b"), cache=cache, generated_at=AT)
    assert cache.hits == 1
    assert second.opportunities == first.opportunities
    assert second.metrics["cache_hits"] == 1
    assert first.context_id == second.context_id and other.context_id != first.context_id
    with pytest.raises(ChipOpportunityForecastError, match="chip state"):
        build_chip_opportunity_forecast(_input(), chip_state=ChipState(wildcard_h1=False), generated_at=AT)


def test_partial_coverage_never_imputes_missing_target_gameweek_as_zero():
    input_value = _input()
    broken = dict(input_value.projections)
    row = broken["p0"]
    broken["p0"] = replace(row, gameweeks=row.gameweeks[1:])
    partial = SimpleNamespace(**{**input_value.__dict__, "projections": broken})
    forecast = build_chip_opportunity_forecast(partial, generated_at=AT)
    assert forecast.status is ChipForecastStatus.PARTIAL
    assert _rows(forecast, "triple_captain")[0].estimated_incremental_ev is None
    assert all(row.realised_incremental_ev is None and row.timing_regret is None for row in forecast.opportunities)
