"""Regression tests for the isolated SIM-V2 challenger."""

from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from fpl_engine.simulation.v2 import FixtureSimulatorV2


ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "_v1_fixture_tests",
    ROOT / "tests" / "test_fixture_simulation.py",
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError(
        "cannot load V1 fixture simulation helpers"
    )

BASE = importlib.util.module_from_spec(
    SPEC
)

SPEC.loader.exec_module(
    BASE
)


def simulator_v2(
    count=300,
    seed=42,
    retain=True,
):
    return FixtureSimulatorV2(
        BASE.FPLScoringEngine.from_project(
            ROOT
        ),
        BASE.SimulationConfig(
            count,
            seed,
            retain,
        ),
    )


def challenger_squad():
    target = BASE.player(
        "home_target",
        "home",
        "FWD",
        p_start=.8,
    )

    target = replace(
        target,
        rates=replace(
            target.rates,
            p_appearance=.8,
            p_start=.8,
        ),
    )

    flexible = BASE.player(
        "home_flexible",
        "home",
        "MID",
        p_start=.4,
    )

    flexible = replace(
        flexible,
        rates=replace(
            flexible.rates,
            p_appearance=.7,
            p_start=.4,
        ),
    )

    squad = tuple(
        [
            BASE.player(
                "home_gk_1",
                "home",
                "GK",
                p_start=.9,
            ),
            BASE.player(
                "home_gk_2",
                "home",
                "GK",
                p_start=.2,
            ),
            target,
            flexible,
        ]
        + [
            BASE.player(
                f"home_out_{index}",
                "home",
                "MID",
                p_start=.9,
            )
            for index in range(10)
        ]
    )

    return squad


def test_v2_reconciliation_has_legal_mass_and_preserves_locked_player():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    squad = challenger_squad()

    team = replace(
        events.home,
        players=squad,
    )

    reconciled = (
        FixtureSimulatorV2
        ._reconcile_start_probabilities(
            team
        )
    )

    assert reconciled is not None

    goalkeeper_mass = sum(
        reconciled[
            player.rates.player_id
        ]
        for player in squad
        if player.rates.position == "GK"
    )

    outfield_mass = sum(
        reconciled[
            player.rates.player_id
        ]
        for player in squad
        if player.rates.position != "GK"
    )

    assert goalkeeper_mass == pytest.approx(
        1.0,
        abs=1e-8,
    )

    assert outfield_mass == pytest.approx(
        10.0,
        abs=1e-8,
    )

    assert sum(
        reconciled.values()
    ) == pytest.approx(
        11.0,
        abs=1e-8,
    )

    # If target appears, V1 Minutes says it starts.
    assert reconciled[
        "home_target"
    ] == pytest.approx(
        .8,
        abs=1e-10,
    )

    for player in squad:
        assert (
            reconciled[
                player.rates.player_id
            ]
            <= player.rates.p_appearance
            + 1e-10
        )


def test_v2_fixed_size_sampler_preserves_reconciled_marginals():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    squad = challenger_squad()

    team = replace(
        events.home,
        players=squad,
    )

    reconciled = (
        FixtureSimulatorV2
        ._reconcile_start_probabilities(
            team
        )
    )

    assert reconciled is not None

    goalkeeper_ids = [
        player.rates.player_id
        for player in squad
        if player.rates.position == "GK"
    ]

    outfield_ids = [
        player.rates.player_id
        for player in squad
        if player.rates.position != "GK"
    ]

    rng = np.random.default_rng(
        20260911
    )

    draws = 50_000

    counts = {
        player.rates.player_id: 0
        for player in squad
    }

    for _ in range(draws):
        selected = (
            FixtureSimulatorV2
            ._sample_fixed_size(
                reconciled,
                goalkeeper_ids,
                rng,
            )
            | FixtureSimulatorV2
            ._sample_fixed_size(
                reconciled,
                outfield_ids,
                rng,
            )
        )

        assert len(selected) == 11

        assert sum(
            player_id in selected
            for player_id in goalkeeper_ids
        ) == 1

        for player_id in selected:
            counts[player_id] += 1

    errors = [
        abs(
            counts[player_id] / draws
            - reconciled[player_id]
        )
        for player_id in counts
    ]

    assert max(errors) < .015


def test_v2_simulation_preserves_appearance_and_no_fake_target_bench_role():
    events, strength = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    squad = challenger_squad()

    events = replace(
        events,
        home=replace(
            events.home,
            players=squad,
        ),
    )

    result = simulator_v2(
        count=3_000,
        seed=812,
        retain=True,
    ).simulate(
        events,
        strength,
    )

    target_rows = [
        row
        for row in result.player_rows
        if (
            row.team_id == "home"
            and row.player_id
            == "home_target"
        )
    ]

    flexible_rows = [
        row
        for row in result.player_rows
        if (
            row.team_id == "home"
            and row.player_id
            == "home_flexible"
        )
    ]

    target_start = (
        sum(
            row.started
            for row in target_rows
        )
        / len(target_rows)
    )

    flexible_appearance = (
        sum(
            row.minutes > 0
            for row in flexible_rows
        )
        / len(flexible_rows)
    )

    assert target_start == pytest.approx(
        .8,
        abs=.04,
    )

    # p_start == p_appearance:
    # a non-start must remain a true zero-minute outcome.
    assert all(
        row.minutes == 0
        for row in target_rows
        if not row.started
    )

    # Reconciliation must not destroy original appearance probability.
    assert flexible_appearance == pytest.approx(
        .7,
        abs=.04,
    )

    for simulation_id in range(
        3_000
    ):
        rows = [
            row
            for row in result.player_rows
            if (
                row.team_id == "home"
                and row.simulation_id
                == simulation_id
            )
        ]

        assert sum(
            row.started
            for row in rows
        ) == 11

        assert sum(
            row.started
            and row.player_id.startswith(
                "home_gk"
            )
            for row in rows
        ) == 1

    assert {
        summary.simulator_version
        for summary in result.summaries
    } == {
        FixtureSimulatorV2.VERSION
    }

    assert result.simulator_version == (
        FixtureSimulatorV2.VERSION
    )



def test_v2_tolerates_machine_precision_start_above_appearance():
    events, _ = BASE.fixture(
        home_goals=0,
        away_goals=0,
    )

    epsilon_player = BASE.player(
        "epsilon_player",
        "home",
        "MID",
        p_start=.2,
    )

    p_app = 0.20605653144082048
    p_start = 0.20605653144082056

    assert p_start > p_app
    assert p_start - p_app < 1e-12

    epsilon_player = replace(
        epsilon_player,
        rates=replace(
            epsilon_player.rates,
            p_appearance=p_app,
            p_start=p_start,
        ),
    )

    squad = tuple(
        [
            BASE.player(
                "epsilon_gk_1",
                "home",
                "GK",
                p_start=.9,
            ),
            BASE.player(
                "epsilon_gk_2",
                "home",
                "GK",
                p_start=.2,
            ),
            epsilon_player,
        ]
        + [
            BASE.player(
                f"epsilon_out_{index}",
                "home",
                "MID",
                p_start=.9,
            )
            for index in range(11)
        ]
    )

    team = replace(
        events.home,
        players=squad,
    )

    reconciled = (
        FixtureSimulatorV2
        ._reconcile_start_probabilities(
            team
        )
    )

    assert reconciled is not None

    assert (
        reconciled[
            "epsilon_player"
        ]
        <= p_app + 1e-12
    )

    assert sum(
        reconciled.values()
    ) == pytest.approx(
        11.0,
        abs=1e-8,
    )
