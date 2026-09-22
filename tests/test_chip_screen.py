from types import SimpleNamespace

import pytest

import fpl_engine.decision.chip_screen as screen_module

from fpl_engine.decision.chip_screen import (
    ExactUnlimitedCandidate,
    rank_unlimited_candidates_exact,
    screen_chips_exact,
)


def _projection(
    player_id,
    values,
    first_gameweek=5,
):

    return SimpleNamespace(
        player_id=player_id,

        gameweeks=tuple(
            SimpleNamespace(
                gameweek=(
                    first_gameweek
                    + index
                ),

                expected_points=float(
                    value
                ),
            )
            for index, value
            in enumerate(
                values
            )
        ),
    )


def _squad_data():

    positions = {
        "g1": "GK",
        "g2": "GK",

        "d1": "DEF",
        "d2": "DEF",
        "d3": "DEF",
        "d4": "DEF",
        "d5": "DEF",

        "m1": "MID",
        "m2": "MID",
        "m3": "MID",
        "m4": "MID",
        "m5": "MID",

        "f1": "FWD",
        "f2": "FWD",
        "f3": "FWD",
    }


    squad = tuple(
        positions
    )


    values = {
        player_id:
            (
                6.0
                - 0.1
                * index,
                5.0
                - 0.05
                * index,
            )
        for index, player_id
        in enumerate(
            squad
        )
    }


    projections = {
        player_id:
            _projection(
                player_id,
                value,
            )
        for player_id, value
        in values.items()
    }


    papp = {
        (
            player_id,
            gameweek,
        ):
            0.95
        for player_id
        in squad
        for gameweek
        in (
            5,
            6,
        )
    }


    return (
        squad,
        positions,
        projections,
        papp,
    )


def test_screen_current_squad_tc_and_bb_are_exact(
    monkeypatch,
):

    (
        squad,
        positions,
        projections,
        papp,
    ) = _squad_data()


    class FakeRanking:

        def __init__(
            self,
            chip,
        ):

            from fpl_engine.decision.chip_screen_exact import (
                evaluate_exact_chip_squad,
            )

            exact = evaluate_exact_chip_squad(
                squad_player_ids=squad,

                positions=positions,

                projections_by_id=(
                    projections
                ),

                p_appearance_by_gameweek=(
                    papp
                ),

                first_gameweek=5,

                horizon=(
                    1
                    if chip == "free_hit"
                    else 2
                ),

                weights=(
                    (1.0,)
                    if chip == "free_hit"
                    else (
                        1.0,
                        0.95,
                    )
                ),

                chip=chip,
            )


            self.selected = (
                ExactUnlimitedCandidate(
                    player_ids=(
                        frozenset(
                            squad
                        )
                    ),

                    generator_weighted_xi_ev=0.0,

                    exact=exact,
                )
            )

            self.unique_count = 1


    monkeypatch.setattr(
        screen_module,
        "rank_unlimited_candidates_exact",
        lambda **kwargs:
            FakeRanking(
                kwargs[
                    "chip"
                ]
            ),
    )


    screen = screen_chips_exact(
        player_rows=(),

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        current_player_ids=squad,

        selling_prices_tenths={
            player_id:
                50
            for player_id
            in squad
        },

        bank_tenths=0,

        first_gameweek=5,

        wildcard_horizon=2,

        wildcard_weights=(
            1.0,
            0.95,
        ),
    )


    assert (
        screen
        .triple_captain
        .incremental_ev
        > 0.0
    )

    assert (
        screen
        .bench_boost
        .incremental_ev
        > 0.0
    )

    assert (
        screen
        .triple_captain
        .captain_id
        in squad
    )

    assert (
        screen
        .triple_captain
        .vice_id
        in squad
    )


def test_used_wildcard_is_not_ranked_or_reported_as_evaluating(monkeypatch):
    squad, positions, projections, papp = _squad_data()
    calls = []
    progress = []

    def fake_ranking(*, chip, **_):
        calls.append(chip)
        from fpl_engine.decision.chip_screen_exact import evaluate_exact_chip_squad

        exact = evaluate_exact_chip_squad(
            squad_player_ids=squad, positions=positions, projections_by_id=projections,
            p_appearance_by_gameweek=papp, first_gameweek=5, horizon=1,
            weights=(1.0,), chip="normal",
        )
        return screen_module.ExactUnlimitedCandidateRanking(
            chip=chip, generated_count=1, unique_count=1,
            selected=ExactUnlimitedCandidate(frozenset(squad), 0.0, exact), candidates=(),
        )

    monkeypatch.setattr(screen_module, "rank_unlimited_candidates_exact", fake_ranking)
    result = screen_chips_exact(
        player_rows=(), positions=positions, projections_by_id=projections,
        p_appearance_by_gameweek=papp, current_player_ids=squad,
        selling_prices_tenths={player_id: 50 for player_id in squad}, bank_tenths=0,
        first_gameweek=5, wildcard_horizon=2, wildcard_weights=(1.0, 0.95),
        available_chips=("triple_captain", "bench_boost", "free_hit"), progress=progress.append,
    )

    assert calls == ["free_hit"]
    assert "evaluating Wildcard" not in progress
    assert "skipping Wildcard (already used)" in progress
    assert result.wildcard.candidate_count == 0


def test_unlimited_ranking_uses_exact_score_not_generator_score(
    monkeypatch,
):

    (
        squad,
        positions,
        projections,
        papp,
    ) = _squad_data()


    squad_a = frozenset(
        squad
    )

    squad_b = frozenset(
        squad
    )


    class Plan:

        def __init__(
            self,
            ids,
            generator_ev,
        ):

            self.player_ids = ids

            self.weighted_xi_ev = (
                generator_ev
            )


    #
    # Two synthetic candidates.
    # We differentiate their exact result by monkeypatching
    # the exact scorer below.
    #
    plans = (
        Plan(
            squad_a,
            100.0,
        ),

        Plan(
            squad_b,
            90.0,
        ),
    )


    monkeypatch.setattr(
        screen_module,
        "_generate_unlimited_portfolio",
        lambda **kwargs:
            plans,
    )


    counter = {
        "value": 0,
    }


    class Exact:

        def __init__(
            self,
            ev,
        ):

            self.weighted_total_ev = ev


    def fake_exact(
        **kwargs,
    ):

        counter[
            "value"
        ] += 1

        return Exact(
            10.0
            if counter[
                "value"
            ] == 1
            else 20.0
        )


    monkeypatch.setattr(
        screen_module,
        "evaluate_exact_chip_squad",
        fake_exact,
    )


    result = (
        rank_unlimited_candidates_exact(
            chip="free_hit",

            player_rows=(),

            positions=positions,

            projections_by_id=(
                projections
            ),

            p_appearance_by_gameweek=(
                papp
            ),

            current_player_ids=squad,

            selling_prices_tenths={
                player_id:
                    50
                for player_id
                in squad
            },

            bank_tenths=0,

            first_gameweek=5,

            horizon=1,

            weights=(1.0,),
        )
    )


    assert (
        result
        .selected
        .exact
        .weighted_total_ev
        == pytest.approx(
            20.0
        )
    )

    assert (
        result
        .selected
        .generator_weighted_xi_ev
        == pytest.approx(
            90.0
        )
    )
