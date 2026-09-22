import pytest

from fpl_engine.decision.autosubs import (
    evaluate_autosub_lineup,
)


POSITIONS = {
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


def base_maps():

    ev = {
        player_id: 0.0
        for player_id in POSITIONS
    }

    app = {
        player_id: 1.0
        for player_id in POSITIONS
    }

    return ev, app


def test_goalkeeper_autosub():

    ev, app = base_maps()

    starters = (
        "g1",
        "d1",
        "d2",
        "d3",
        "m1",
        "m2",
        "m3",
        "m4",
        "f1",
        "f2",
        "f3",
    )

    app["g1"] = 0.0
    ev["g2"] = 4.0

    result = evaluate_autosub_lineup(
        gameweek=4,
        starter_ids=starters,
        bench_gk_id="g2",
        bench_outfield_ids=(
            "d4",
            "d5",
            "m5",
        ),
        positions=POSITIONS,
        expected_points=ev,
        p_appearance=app,
    )

    assert (
        result.expected_gk_autosub_ev
        == pytest.approx(4.0)
    )


def test_invalid_first_bench_is_skipped_for_defender():

    ev, app = base_maps()

    starters = (
        "g1",
        "d1",
        "d2",
        "d3",
        "m1",
        "m2",
        "m3",
        "m4",
        "f1",
        "f2",
        "f3",
    )

    #
    # d1 does not play.
    # m5 cannot replace him:
    # 2-5-3 would be illegal.
    # d4 therefore enters.
    #

    app["d1"] = 0.0

    ev["m5"] = 10.0
    ev["d4"] = 3.0

    result = evaluate_autosub_lineup(
        gameweek=4,
        starter_ids=starters,
        bench_gk_id="g2",
        bench_outfield_ids=(
            "m5",
            "d4",
            "d5",
        ),
        positions=POSITIONS,
        expected_points=ev,
        p_appearance=app,
    )

    assert (
        result.expected_outfield_autosub_ev
        == pytest.approx(3.0)
    )


def test_probabilistic_autosub_value():

    ev, app = base_maps()

    starters = (
        "g1",
        "d1",
        "d2",
        "d3",
        "d4",
        "m1",
        "m2",
        "m3",
        "m4",
        "f1",
        "f2",
    )

    #
    # m1 has 20% DNP risk.
    # m5 has 50% appearance chance
    # and unconditional EV=2,
    # so conditional EV=4.
    #
    # Expected autosub:
    # .20 * .50 * 4 = .40
    #

    app["m1"] = 0.8
    app["m5"] = 0.5

    ev["m5"] = 2.0

    result = evaluate_autosub_lineup(
        gameweek=4,
        starter_ids=starters,
        bench_gk_id="g2",
        bench_outfield_ids=(
            "m5",
            "d5",
            "f3",
        ),
        positions=POSITIONS,
        expected_points=ev,
        p_appearance=app,
    )

    assert (
        result.expected_outfield_autosub_ev
        == pytest.approx(0.4)
    )
