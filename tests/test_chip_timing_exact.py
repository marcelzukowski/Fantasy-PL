from types import SimpleNamespace

import pytest

import fpl_engine.decision.chip_timing as timing_module

from fpl_engine.decision.chip_screen import (
    ExactChipScreenEntry,
)

from fpl_engine.decision.chip_timing import (
    ExactChipTimingConfig,
    ExactChipTimingPolicy,
    ExactFutureChipOpportunity,
    future_fixed_squad_chip_opportunities_exact,
)


def _entry(
    chip,
    delta,
):

    return ExactChipScreenEntry(
        chip=chip,

        baseline_ev=100.0,

        chip_ev=(
            100.0
            + delta
        ),

        incremental_ev=delta,

        squad_player_ids=(
            frozenset({
                "a",
            })
        ),

        captain_id="a",

        vice_id="b",

        formation="3-4-3",

        candidate_count=1,
    )


def _screen(
    *,
    tc=5.0,
    bb=6.0,
    fh=7.0,
    wc=8.0,
):

    return SimpleNamespace(
        triple_captain=_entry(
            "triple_captain",
            tc,
        ),

        bench_boost=_entry(
            "bench_boost",
            bb,
        ),

        free_hit=_entry(
            "free_hit",
            fh,
        ),

        wildcard=_entry(
            "wildcard",
            wc,
        ),
    )


def _config():

    return ExactChipTimingConfig(
        evaluation_horizon_gameweeks=6,

        minimum_incremental_ev=4.0,

        future_opportunity_tolerance=0.5,

        wildcard_minimum_weighted_gain=7.0,

        free_hit_minimum_single_gameweek_gain=6.0,
    )


def test_exact_timing_applies_thresholds():

    policy = ExactChipTimingPolicy(
        _config()
    )


    decision = policy.decide(
        screen=_screen(
            tc=3.0,
            bb=4.5,
            fh=5.5,
            wc=6.5,
        )
    )


    by_chip = {
        row.chip:
            row
        for row in decision.evaluations
    }


    assert not by_chip[
        "triple_captain"
    ].use_now

    assert by_chip[
        "bench_boost"
    ].use_now

    assert not by_chip[
        "free_hit"
    ].use_now

    assert not by_chip[
        "wildcard"
    ].use_now


def test_exact_timing_respects_future_opportunity():

    policy = ExactChipTimingPolicy(
        _config()
    )


    future = {
        "triple_captain": (
            ExactFutureChipOpportunity(
                chip="triple_captain",

                gameweek=7,

                baseline_ev=40.0,

                chip_ev=46.0,

                incremental_ev=6.0,
            ),
        ),
    }


    decision = policy.decide(
        screen=_screen(
            tc=5.0,
            bb=0.0,
            fh=0.0,
            wc=0.0,
        ),

        future_opportunities=(
            future
        ),
    )


    tc = next(
        row
        for row
        in decision.evaluations
        if row.chip
        == "triple_captain"
    )


    assert (
        tc.clears_threshold
    )

    assert not (
        tc.competitive_with_future
    )

    assert not tc.use_now


def test_exact_timing_tolerance_can_make_now_competitive():

    policy = ExactChipTimingPolicy(
        _config()
    )


    future = {
        "triple_captain": (
            ExactFutureChipOpportunity(
                chip="triple_captain",

                gameweek=7,

                baseline_ev=40.0,

                chip_ev=45.4,

                incremental_ev=5.4,
            ),
        ),
    }


    decision = policy.decide(
        screen=_screen(
            tc=5.0,
            bb=0.0,
            fh=0.0,
            wc=0.0,
        ),

        future_opportunities=(
            future
        ),
    )


    tc = next(
        row
        for row
        in decision.evaluations
        if row.chip
        == "triple_captain"
    )


    assert (
        tc.competitive_with_future
    )

    assert tc.use_now


def test_exact_timing_respects_availability():

    policy = ExactChipTimingPolicy(
        _config()
    )


    decision = policy.decide(
        screen=_screen(),

        available_chips=(
            "triple_captain",
        ),
    )


    assert (
        decision.chosen_chip
        == "triple_captain"
    )


    by_chip = {
        row.chip:
            row
        for row
        in decision.evaluations
    }


    assert not by_chip[
        "wildcard"
    ].available

    assert not by_chip[
        "wildcard"
    ].use_now


def test_future_opportunity_builder_uses_only_known_future_gws(
    monkeypatch,
):

    squad = tuple(
        f"p{index}"
        for index
        in range(
            15
        )
    )


    projections = {
        player_id:
            SimpleNamespace(
                gameweeks=tuple(
                    SimpleNamespace(
                        gameweek=gw
                    )
                    for gw in (
                        5,
                        6,
                        7,
                    )
                )
            )
        for player_id
        in squad
    }


    papp = {
        (
            player_id,
            gw,
        ):
            0.9
        for player_id
        in squad
        for gw in (
            5,
            6,
            7,
        )
    }


    calls = []


    def fake_evaluate(
        *,
        first_gameweek,
        chip,
        **kwargs,
    ):

        calls.append(
            (
                first_gameweek,
                chip,
            )
        )


        bonus = {
            "normal": 0.0,
            "triple_captain": 5.0,
            "bench_boost": 7.0,
        }[
            chip
        ]


        return SimpleNamespace(
            weighted_total_ev=(
                40.0
                + first_gameweek
                + bonus
            )
        )


    monkeypatch.setattr(
        timing_module,
        "evaluate_exact_chip_squad",
        fake_evaluate,
    )


    result = (
        future_fixed_squad_chip_opportunities_exact(
            squad_player_ids=squad,

            positions={
                player_id:
                    (
                        "GK"
                        if index < 2
                        else "DEF"
                    )
                for index, player_id
                in enumerate(
                    squad
                )
            },

            projections_by_id=(
                projections
            ),

            p_appearance_by_gameweek=(
                papp
            ),

            first_gameweek=5,

            evaluation_horizon_gameweeks=6,
        )
    )


    assert [
        row.gameweek
        for row
        in result[
            "triple_captain"
        ]
    ] == [
        6,
        7,
    ]


    assert [
        row.incremental_ev
        for row
        in result[
            "triple_captain"
        ]
    ] == pytest.approx([
        5.0,
        5.0,
    ])


    assert [
        row.incremental_ev
        for row
        in result[
            "bench_boost"
        ]
    ] == pytest.approx([
        7.0,
        7.0,
    ])


    assert all(
        chip
        in {
            "normal",
            "triple_captain",
            "bench_boost",
        }
        for _gw, chip
        in calls
    )
