from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.models.events.market_blend import (
    MARKET_BLEND_VERSION,
    MarketBlendConfig,
    MarketBlendError,
    ModelEventExpectation,
    blend_player_event_expectation,
    market_blend_candidate_grid,
)
from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
)


AT = datetime(
    2026,
    9,
    11,
    12,
    0,
    tzinfo=timezone.utc,
)


def model(
    *,
    sot=1.0,
):
    return ModelEventExpectation(
        fixture_id="fixture-1",
        player_id="player-1",
        prediction_timestamp=AT,
        expected_goals=0.40,
        expected_assists=0.20,
        expected_shots=2.00,
        expected_shots_on_target=sot,
        model_version="event_models_v1",
    )


def market(
    *,
    goals=0.80,
    assists=0.40,
    shots=4.00,
    sot=2.00,
):
    return PlayerMarketPrior(
        fixture_id="fixture-1",
        player_id="player-1",
        prediction_timestamp=AT,
        expected_goals=goals,
        expected_assists=assists,
        expected_shots=shots,
        expected_shots_on_target=sot,
        signals=(),
        known_at=AT - timedelta(minutes=5),
    )


def test_model_only_is_exact_identity():
    result = blend_player_event_expectation(
        model(),
        market(),
        config=MarketBlendConfig.shared(0.0),
    )

    assert result.goals.value == pytest.approx(
        0.40
    )
    assert result.assists.value == pytest.approx(
        0.20
    )
    assert result.shots.value == pytest.approx(
        2.00
    )
    assert result.shots_on_target.value == pytest.approx(
        1.00
    )

    assert result.goals.source == "MODEL_ONLY"


def test_market_only_is_exact_market_forecast():
    result = blend_player_event_expectation(
        model(),
        market(),
        config=MarketBlendConfig.shared(1.0),
    )

    assert result.goals.value == pytest.approx(
        0.80
    )
    assert result.assists.value == pytest.approx(
        0.40
    )
    assert result.shots.value == pytest.approx(
        4.00
    )
    assert result.shots_on_target.value == pytest.approx(
        2.00
    )

    assert result.goals.source == "MARKET_ONLY"


def test_half_blend_is_convex_average():
    result = blend_player_event_expectation(
        model(),
        market(),
        config=MarketBlendConfig.shared(0.5),
    )

    assert result.goals.value == pytest.approx(
        0.60
    )
    assert result.assists.value == pytest.approx(
        0.30
    )
    assert result.shots.value == pytest.approx(
        3.00
    )
    assert result.shots_on_target.value == pytest.approx(
        1.50
    )

    assert result.goals.source == "MODEL_MARKET"
    assert (
        result.goals.effective_market_weight
        == 0.5
    )


def test_missing_market_signal_falls_back_to_model():
    result = blend_player_event_expectation(
        model(),
        market(
            goals=None,
        ),
        config=MarketBlendConfig.shared(0.75),
    )

    assert result.goals.value == pytest.approx(
        0.40
    )

    assert result.goals.source == "MODEL_ONLY"

    assert (
        result.goals.effective_market_weight
        == 0.0
    )


def test_missing_market_prior_is_full_model_fallback():
    result = blend_player_event_expectation(
        model(),
        None,
        config=MarketBlendConfig.shared(0.75),
    )

    assert result.goals.value == pytest.approx(
        0.40
    )

    assert result.assists.value == pytest.approx(
        0.20
    )

    assert result.goals.source == "MODEL_ONLY"
    assert result.market_prior_version is None


def test_market_can_fill_model_missing_sot():
    result = blend_player_event_expectation(
        model(
            sot=None,
        ),
        market(
            sot=1.7,
        ),
        config=MarketBlendConfig.shared(0.25),
    )

    assert (
        result.shots_on_target.value
        == pytest.approx(1.7)
    )

    assert (
        result.shots_on_target.source
        == "MARKET_ONLY"
    )

    assert (
        result.shots_on_target
        .effective_market_weight
        == 1.0
    )


def test_event_specific_weights_are_supported():
    config = MarketBlendConfig(
        goal_market_weight=0.75,
        assist_market_weight=0.25,
        shots_market_weight=0.50,
        shots_on_target_market_weight=1.0,
    )

    result = blend_player_event_expectation(
        model(),
        market(),
        config=config,
    )

    assert result.goals.value == pytest.approx(
        0.70
    )

    assert result.assists.value == pytest.approx(
        0.25
    )

    assert result.shots.value == pytest.approx(
        3.00
    )

    assert (
        result.shots_on_target.value
        == pytest.approx(2.00)
    )


def test_identity_mismatch_is_rejected():
    wrong = PlayerMarketPrior(
        fixture_id="fixture-X",
        player_id="player-1",
        prediction_timestamp=AT,
        expected_goals=0.5,
        expected_assists=None,
        expected_shots=None,
        expected_shots_on_target=None,
        signals=(),
        known_at=AT - timedelta(minutes=5),
    )

    with pytest.raises(
        MarketBlendError
    ):
        blend_player_event_expectation(
            model(),
            wrong,
            config=MarketBlendConfig.shared(0.5),
        )


def test_prediction_timestamp_mismatch_is_rejected():
    wrong = PlayerMarketPrior(
        fixture_id="fixture-1",
        player_id="player-1",
        prediction_timestamp=(
            AT - timedelta(minutes=1)
        ),
        expected_goals=0.5,
        expected_assists=None,
        expected_shots=None,
        expected_shots_on_target=None,
        signals=(),
        known_at=AT - timedelta(minutes=5),
    )

    with pytest.raises(
        MarketBlendError
    ):
        blend_player_event_expectation(
            model(),
            wrong,
            config=MarketBlendConfig.shared(0.5),
        )


def test_candidate_grid_contains_baseline_and_market_only():
    grid = market_blend_candidate_grid()

    assert [
        item.goal_market_weight
        for item in grid
    ] == [
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
    ]

    assert (
        grid[0].candidate_id
        == (
            f"{MARKET_BLEND_VERSION}"
            "_g0.00_a0.00_s0.00_t0.00"
        )
    )

    assert (
        grid[-1].candidate_id
        == (
            f"{MARKET_BLEND_VERSION}"
            "_g1.00_a1.00_s1.00_t1.00"
        )
    )


def test_invalid_weight_is_rejected():
    with pytest.raises(
        MarketBlendError
    ):
        MarketBlendConfig.shared(
            1.01
        )
