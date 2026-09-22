from datetime import datetime, timedelta, timezone
import math

import pytest

from fpl_engine.data.market_odds import (
    MarketConsensus,
    MarketKind,
    MarketOddsLeakageError,
)
from fpl_engine.models.events.market_prior import (
    MARKET_PRIOR_VERSION,
    binary_probability_to_poisson_mean,
    build_player_market_priors,
    consensus_to_event_signal,
    over_probability_to_poisson_mean,
    poisson_over_probability,
)


AT = datetime(
    2026,
    9,
    11,
    12,
    0,
    tzinfo=timezone.utc,
)


def consensus(
    *,
    player_id="player-1",
    fixture_id="fixture-1",
    market=MarketKind.ANYTIME_GOAL,
    probability=0.40,
    line=None,
    known_at=AT - timedelta(minutes=10),
):
    return MarketConsensus(
        fixture_id=fixture_id,
        player_id=player_id,
        market=market,
        line=line,
        fair_probability=probability,
        book_count=3,
        dispersion=0.03,
        median_quote_age_seconds=600,
        max_quote_age_seconds=900,
        known_at=known_at,
    )


def test_binary_market_probability_maps_to_poisson_mean():
    result = (
        binary_probability_to_poisson_mean(
            0.5
        )
    )

    assert result == pytest.approx(
        math.log(2)
    )


def test_count_market_poisson_inversion_recovers_mean():
    expected_mean = 3.2

    probability = (
        poisson_over_probability(
            expected_mean,
            2.5,
        )
    )

    recovered = (
        over_probability_to_poisson_mean(
            probability,
            2.5,
        )
    )

    assert recovered == pytest.approx(
        expected_mean,
        abs=1e-9,
    )


def test_goal_consensus_creates_unconditional_goal_signal():
    item = consensus(
        market=MarketKind.ANYTIME_GOAL,
        probability=0.50,
    )

    signal = (
        consensus_to_event_signal(
            item
        )
    )

    assert signal.market == MarketKind.ANYTIME_GOAL
    assert signal.implied_event_mean == pytest.approx(
        math.log(2)
    )
    assert (
        signal.method
        == "binary_at_least_one_poisson_inversion_v1"
    )


def test_build_player_prior_uses_all_four_market_families():
    goal = consensus(
        market=MarketKind.ANYTIME_GOAL,
        probability=0.45,
    )

    assist = consensus(
        market=MarketKind.ASSIST,
        probability=0.30,
    )

    shots_mean = 3.0
    sot_mean = 1.4

    shots = consensus(
        market=MarketKind.SHOTS,
        probability=poisson_over_probability(
            shots_mean,
            2.5,
        ),
        line=2.5,
    )

    sot = consensus(
        market=MarketKind.SHOTS_ON_TARGET,
        probability=poisson_over_probability(
            sot_mean,
            1.5,
        ),
        line=1.5,
    )

    result = build_player_market_priors(
        (
            goal,
            assist,
            shots,
            sot,
        ),
        prediction_timestamp=AT,
    )

    assert len(result) == 1

    prior = result[0]

    assert prior.version == MARKET_PRIOR_VERSION

    assert prior.expected_goals == pytest.approx(
        -math.log1p(-0.45)
    )

    assert prior.expected_assists == pytest.approx(
        -math.log1p(-0.30)
    )

    assert prior.expected_shots == pytest.approx(
        shots_mean,
        abs=1e-9,
    )

    assert (
        prior.expected_shots_on_target
        == pytest.approx(
            sot_mean,
            abs=1e-9,
        )
    )

    assert set(
        prior.available_markets
    ) == {
        MarketKind.ANYTIME_GOAL,
        MarketKind.ASSIST,
        MarketKind.SHOTS,
        MarketKind.SHOTS_ON_TARGET,
    }


def test_multiple_count_lines_are_combined_after_inversion():
    expected_mean = 2.7

    line_15 = consensus(
        market=MarketKind.SHOTS,
        probability=poisson_over_probability(
            expected_mean,
            1.5,
        ),
        line=1.5,
    )

    line_25 = consensus(
        market=MarketKind.SHOTS,
        probability=poisson_over_probability(
            expected_mean,
            2.5,
        ),
        line=2.5,
    )

    prior = build_player_market_priors(
        (
            line_15,
            line_25,
        ),
        prediction_timestamp=AT,
    )[0]

    assert prior.expected_shots == pytest.approx(
        expected_mean,
        abs=1e-9,
    )

    assert len(prior.signals) == 2


def test_priors_are_grouped_by_fixture_and_player():
    result = build_player_market_priors(
        (
            consensus(
                player_id="p1",
                fixture_id="f1",
            ),
            consensus(
                player_id="p2",
                fixture_id="f1",
            ),
            consensus(
                player_id="p1",
                fixture_id="f2",
            ),
        ),
        prediction_timestamp=AT,
    )

    assert {
        (
            item.fixture_id,
            item.player_id,
        )
        for item in result
    } == {
        ("f1", "p1"),
        ("f1", "p2"),
        ("f2", "p1"),
    }


def test_future_consensus_is_rejected():
    future = consensus(
        known_at=AT
        + timedelta(seconds=1),
    )

    with pytest.raises(
        MarketOddsLeakageError
    ):
        build_player_market_priors(
            (future,),
            prediction_timestamp=AT,
        )


def test_incoherent_shot_markets_are_flagged_not_silently_changed():
    shots = consensus(
        market=MarketKind.SHOTS,
        probability=poisson_over_probability(
            1.0,
            0.5,
        ),
        line=0.5,
    )

    sot = consensus(
        market=MarketKind.SHOTS_ON_TARGET,
        probability=poisson_over_probability(
            1.5,
            0.5,
        ),
        line=0.5,
    )

    prior = build_player_market_priors(
        (shots, sot),
        prediction_timestamp=AT,
    )[0]

    assert prior.expected_shots == pytest.approx(
        1.0,
        abs=1e-9,
    )

    assert prior.expected_shots_on_target == pytest.approx(
        1.5,
        abs=1e-9,
    )

    assert prior.warnings == (
        "market SOT expectation exceeds "
        "market shots expectation",
    )



def test_assist_half_line_is_inverted_as_count_market():
    expected_mean = 0.42

    item = consensus(
        market=MarketKind.ASSIST,
        probability=poisson_over_probability(
            expected_mean,
            0.5,
        ),
        line=0.5,
    )

    signal = consensus_to_event_signal(
        item
    )

    assert signal.implied_event_mean == pytest.approx(
        expected_mean,
        abs=1e-9,
    )

    assert (
        signal.method
        == "half_line_over_poisson_inversion_v1"
    )
