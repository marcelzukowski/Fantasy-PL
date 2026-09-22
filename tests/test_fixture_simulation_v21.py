"""Regression tests for SIM-V2.1."""

from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from fpl_engine.simulation.v21 import (
    FixtureSimulatorV21,
)


ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "_v1_fixture_tests_v21",
    ROOT / "tests" / "test_fixture_simulation.py",
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError(
        "cannot load V1 fixture simulation helpers"
    )

BASE = importlib.util.module_from_spec(
    SPEC
)

SPEC.loader.exec_module(BASE)


def simulator_v21(
    count=300,
    seed=42,
    retain=True,
):
    return FixtureSimulatorV21(
        BASE.FPLScoringEngine.from_project(
            ROOT
        ),
        BASE.SimulationConfig(
            count,
            seed,
            retain,
        ),
    )


def distribution(**masses):
    values = [0.0] * 91

    for minute, probability in masses.items():
        values[int(minute)] = float(
            probability
        )

    assert sum(values) == pytest.approx(
        1.0
    )

    return tuple(values)


def with_minutes(
    player,
    *,
    p_appearance,
    p_start,
    marginal,
    starter,
    bench,
):
    expected = sum(
        minute * probability
        for minute, probability
        in enumerate(marginal)
    )

    return replace(
        player,
        rates=replace(
            player.rates,
            p_appearance=p_appearance,
            p_start=p_start,
            expected_minutes=expected,
            minute_distribution=marginal,
            starter_minutes_distribution=starter,
            bench_minutes_distribution=bench,
        ),
    )


def test_v21_under_capacity_does_not_inflate_real_start_probabilities():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    goalkeepers = tuple(
        BASE.player(
            f"gk_{index}",
            "home",
            "GK",
            p_start=p_start,
        )
        for index, p_start
        in enumerate((.4, .2))
    )

    outfield = tuple(
        BASE.player(
            f"out_{index}",
            "home",
            "MID",
            p_start=.6,
        )
        for index in range(11)
    )

    team = replace(
        events.home,
        players=goalkeepers + outfield,
    )

    plan = simulator_v21(
        count=1
    )._build_team_plan(team)

    assert sum(
        plan.goalkeeper
        .real_start_probabilities
        .values()
    ) == pytest.approx(.6)

    assert sum(
        plan.outfield
        .real_start_probabilities
        .values()
    ) == pytest.approx(6.6)

    assert sum(
        plan.goalkeeper
        .selection_probabilities
        .values()
    ) == pytest.approx(1.0)

    assert sum(
        plan.outfield
        .selection_probabilities
        .values()
    ) == pytest.approx(10.0)

    assert sum(
        plan.goalkeeper
        .selection_probabilities[pid]
        for pid in plan.goalkeeper
        .ghost_player_ids
    ) == pytest.approx(.4)

    assert sum(
        plan.outfield
        .selection_probabilities[pid]
        for pid in plan.outfield
        .ghost_player_ids
    ) == pytest.approx(3.4)

    for player in team.players:
        assert (
            plan.real_start_probabilities[
                player.rates.player_id
            ]
            == pytest.approx(
                player.rates.p_start
            )
        )


def test_v21_over_capacity_only_shrinks_real_start_probabilities():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    goalkeepers = tuple(
        BASE.player(
            f"gk_{index}",
            "home",
            "GK",
            p_start=p_start,
        )
        for index, p_start
        in enumerate((.8, .6))
    )

    outfield = tuple(
        BASE.player(
            f"out_{index}",
            "home",
            "MID",
            p_start=.9,
        )
        for index in range(12)
    )

    team = replace(
        events.home,
        players=goalkeepers + outfield,
    )

    plan = simulator_v21(
        count=1
    )._build_team_plan(team)

    assert sum(
        plan.goalkeeper
        .real_start_probabilities
        .values()
    ) == pytest.approx(1.0)

    assert sum(
        plan.outfield
        .real_start_probabilities
        .values()
    ) == pytest.approx(10.0)

    assert not (
        plan.goalkeeper
        .ghost_player_ids
    )

    assert not (
        plan.outfield
        .ghost_player_ids
    )

    for player in team.players:
        reconciled = (
            plan.real_start_probabilities[
                player.rates.player_id
            ]
        )

        assert (
            reconciled
            <= player.rates.p_start
            + 1e-12
        )


def test_v21_conditional_split_exactly_reconstructs_calibrated_marginal():
    player = BASE.player(
        "target",
        "home",
        "FWD",
        p_start=.5,
    )

    marginal = distribution(
        **{
            "0": .2,
            "20": .3,
            "90": .5,
        }
    )

    player = with_minutes(
        player,
        p_appearance=.8,
        p_start=.5,
        marginal=marginal,
        starter=distribution(
            **{"90": 1.0}
        ),
        bench=distribution(
            **{"20": 1.0}
        ),
    )

    q = .5

    starter, nonstarter = (
        FixtureSimulatorV21
        ._conditional_minute_distributions(
            player,
            q,
        )
    )

    assert starter[0] == pytest.approx(
        0.0,
        abs=1e-12,
    )

    assert sum(starter) == pytest.approx(
        1.0
    )

    assert sum(nonstarter) == pytest.approx(
        1.0
    )

    reconstructed = [
        q * starter[minute]
        + (1.0 - q)
        * nonstarter[minute]
        for minute in range(91)
    ]

    assert reconstructed == pytest.approx(
        marginal,
        abs=1e-10,
    )

    expected_original = sum(
        minute * marginal[minute]
        for minute in range(91)
    )

    expected_reconstructed = sum(
        minute * reconstructed[minute]
        for minute in range(91)
    )

    assert expected_reconstructed == pytest.approx(
        expected_original,
        abs=1e-10,
    )


def test_v21_pstart_equal_pappearance_has_no_positive_nonstart_minutes():
    player = BASE.player(
        "locked",
        "home",
        "FWD",
        p_start=.8,
    )

    marginal = distribution(
        **{
            "0": .2,
            "20": .3,
            "80": .5,
        }
    )

    player = with_minutes(
        player,
        p_appearance=.8,
        p_start=.8,
        marginal=marginal,
        starter=distribution(
            **{"80": 1.0}
        ),
        bench=distribution(
            **{"20": 1.0}
        ),
    )

    starter, nonstarter = (
        FixtureSimulatorV21
        ._conditional_minute_distributions(
            player,
            .8,
        )
    )

    assert starter[0] == pytest.approx(0)
    assert nonstarter[0] == pytest.approx(1)
    assert sum(
        nonstarter[1:]
    ) == pytest.approx(
        0.0,
        abs=1e-10,
    )


def test_v21_can_preserve_long_nonstarter_mass_when_p60_exceeds_pstart():
    player = BASE.player(
        "target",
        "home",
        "FWD",
        p_start=.3,
    )

    marginal = distribution(
        **{
            "0": .2,
            "20": .2,
            "70": .3,
            "90": .3,
        }
    )

    player = with_minutes(
        player,
        p_appearance=.8,
        p_start=.3,
        marginal=marginal,
        starter=distribution(
            **{"90": 1.0}
        ),
        bench=distribution(
            **{"20": 1.0}
        ),
    )

    starter, nonstarter = (
        FixtureSimulatorV21
        ._conditional_minute_distributions(
            player,
            .3,
        )
    )

    reconstructed = [
        .3 * starter[minute]
        + .7 * nonstarter[minute]
        for minute in range(91)
    ]

    assert reconstructed == pytest.approx(
        marginal,
        abs=1e-10,
    )

    # The calibrated contract is authoritative,
    # even if it implies long substitute appearances.
    assert sum(
        nonstarter[60:]
    ) > 0.0


def test_v21_fixed_size_lineup_including_ghosts_is_always_one_plus_ten():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    squad = tuple(
        [
            BASE.player(
                "gk",
                "home",
                "GK",
                p_start=.45,
            )
        ]
        + [
            BASE.player(
                f"out_{index}",
                "home",
                "MID",
                p_start=.55,
            )
            for index in range(8)
        ]
    )

    team = replace(
        events.home,
        players=squad,
    )

    sim = simulator_v21(
        count=1
    )

    plan = sim._build_team_plan(
        team
    )

    rng = np.random.default_rng(
        20260911
    )

    for _ in range(2_000):
        keepers = sim._sample_fixed_size(
            plan.goalkeeper
            .selection_probabilities,
            tuple(
                plan.goalkeeper
                .selection_probabilities
                .keys()
            ),
            rng,
        )

        outfield = sim._sample_fixed_size(
            plan.outfield
            .selection_probabilities,
            tuple(
                plan.outfield
                .selection_probabilities
                .keys()
            ),
            rng,
        )

        assert len(keepers) == 1
        assert len(outfield) == 10


def test_v21_monte_carlo_preserves_player_minute_marginal():
    events, strength = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    target = events.home.players[1]

    marginal = distribution(
        **{
            "0": .3,
            "20": .3,
            "80": .4,
        }
    )

    target = with_minutes(
        target,
        p_appearance=.7,
        p_start=.4,
        marginal=marginal,
        starter=distribution(
            **{"80": 1.0}
        ),
        bench=distribution(
            **{"20": 1.0}
        ),
    )

    events = replace(
        events,
        home=replace(
            events.home,
            players=(
                events.home.players[0],
                target,
                events.home.players[2],
            ),
        ),
    )

    result = simulator_v21(
        count=5_000,
        seed=921,
        retain=True,
    ).simulate(
        events,
        strength,
    )

    rows = [
        row
        for row in result.player_rows
        if row.player_id
        == "home_scorer"
    ]

    assert (
        sum(row.started for row in rows)
        / len(rows)
    ) == pytest.approx(
        .4,
        abs=.03,
    )

    assert (
        sum(row.minutes > 0 for row in rows)
        / len(rows)
    ) == pytest.approx(
        .7,
        abs=.03,
    )

    expected = (
        .3 * 0
        + .3 * 20
        + .4 * 80
    )

    observed = (
        sum(row.minutes for row in rows)
        / len(rows)
    )

    assert observed == pytest.approx(
        expected,
        abs=1.2,
    )

    summary = next(
        row
        for row in result.summaries
        if row.player_id
        == "home_scorer"
    )

    assert (
        summary.simulated_expected_minutes
        == pytest.approx(
            expected,
            abs=1.2,
        )
    )

    assert (
        result.simulator_version
        == FixtureSimulatorV21.VERSION
    )


def test_v21_partial_known_squad_uses_ghosts_instead_of_v1_fallback():
    events, strength = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    # Standard V1 helper fixture has only
    # three known players per team.
    result = simulator_v21(
        count=20,
        seed=11,
        retain=True,
    ).simulate(
        events,
        strength,
    )

    assert (
        result.simulator_version
        == FixtureSimulatorV21.VERSION
    )

    assert all(
        summary.simulator_version
        == FixtureSimulatorV21.VERSION
        for summary in result.summaries
    )
