from datetime import datetime, timedelta, timezone
import math

import pytest

from fpl_engine.models.events.market_blend import (
    ModelEventExpectation,
)
from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
)
from fpl_engine.models.events.market_validation import (
    MarketBlendOutcome,
    MarketValidationError,
    MarketValidationLeakageError,
    walk_forward_market_blend,
)


BASE = datetime(
    2026,
    1,
    1,
    12,
    0,
    tzinfo=timezone.utc,
)


def _lambda(probability):
    return -math.log1p(
        -probability
    )


def make_outcome(
    index,
    *,
    model_goal_p=0.50,
    market_goal_p=0.50,
    model_assist_p=0.30,
    market_assist_p=0.30,
    goals=0,
    assists=0,
    market_goals=True,
    market_assists=True,
):
    at = BASE + timedelta(
        days=index
    )

    fixture_id = f"f-{index}"
    player_id = f"p-{index}"

    model = ModelEventExpectation(
        fixture_id=fixture_id,
        player_id=player_id,
        prediction_timestamp=at,
        expected_goals=_lambda(
            model_goal_p
        ),
        expected_assists=_lambda(
            model_assist_p
        ),
        expected_shots=2.0,
        expected_shots_on_target=1.0,
        model_version="event_models_v1",
    )

    market = PlayerMarketPrior(
        fixture_id=fixture_id,
        player_id=player_id,
        prediction_timestamp=at,
        expected_goals=(
            _lambda(
                market_goal_p
            )
            if market_goals
            else None
        ),
        expected_assists=(
            _lambda(
                market_assist_p
            )
            if market_assists
            else None
        ),
        expected_shots=None,
        expected_shots_on_target=None,
        signals=(),
        known_at=(
            at
            - timedelta(minutes=30)
        ),
    )

    return MarketBlendOutcome(
        model=model,
        market=market,
        outcome_known_at=(
            at
            + timedelta(hours=4)
        ),
        goals=goals,
        assists=assists,
    )


def test_future_outcome_is_rejected_as_leakage():
    at = BASE

    model = ModelEventExpectation(
        fixture_id="f",
        player_id="p",
        prediction_timestamp=at,
        expected_goals=0.3,
        expected_assists=0.2,
        expected_shots=2.0,
        expected_shots_on_target=1.0,
        model_version="event_models_v1",
    )

    market = PlayerMarketPrior(
        fixture_id="f",
        player_id="p",
        prediction_timestamp=at,
        expected_goals=0.4,
        expected_assists=0.2,
        expected_shots=None,
        expected_shots_on_target=None,
        signals=(),
        known_at=(
            at
            - timedelta(minutes=1)
        ),
    )

    with pytest.raises(
        MarketValidationLeakageError
    ):
        MarketBlendOutcome(
            model=model,
            market=market,
            outcome_known_at=at,
            goals=0,
            assists=0,
        )


def test_identity_mismatch_is_rejected():
    outcome = make_outcome(
        1
    )

    wrong_market = PlayerMarketPrior(
        fixture_id="WRONG",
        player_id=(
            outcome.model.player_id
        ),
        prediction_timestamp=(
            outcome.model.prediction_timestamp
        ),
        expected_goals=0.4,
        expected_assists=0.2,
        expected_shots=None,
        expected_shots_on_target=None,
        signals=(),
        known_at=(
            outcome.model.prediction_timestamp
            - timedelta(minutes=1)
        ),
    )

    with pytest.raises(
        MarketValidationError
    ):
        MarketBlendOutcome(
            model=outcome.model,
            market=wrong_market,
            outcome_known_at=(
                outcome.outcome_known_at
            ),
            goals=0,
            assists=0,
        )


def test_goal_market_can_be_promoted_when_clearly_better():
    rows = []

    for i in range(40):
        positive = (
            i % 2 == 0
        )

        rows.append(
            make_outcome(
                i,
                model_goal_p=0.50,
                market_goal_p=(
                    0.90
                    if positive
                    else 0.10
                ),
                goals=(
                    1
                    if positive
                    else 0
                ),
                market_assists=False,
            )
        )

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=20,
        )
    )

    assert report.goal_promoted
    assert (
        report.goal_champion_market_weight
        > 0
    )

    assert (
        report.goal_champion_market_weight
        == 1.0
    )


def test_assist_champion_is_selected_independently():
    rows = []

    for i in range(40):
        positive = (
            i % 4 == 0
        )

        rows.append(
            make_outcome(
                i,
                model_goal_p=(
                    0.90
                    if i % 2 == 0
                    else 0.10
                ),
                market_goal_p=0.50,
                goals=(
                    1
                    if i % 2 == 0
                    else 0
                ),
                model_assist_p=0.30,
                market_assist_p=(
                    0.85
                    if positive
                    else 0.08
                ),
                assists=(
                    1
                    if positive
                    else 0
                ),
            )
        )

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=20,
        )
    )

    assert not report.goal_promoted
    assert (
        report.goal_champion_market_weight
        == 0.0
    )

    assert report.assist_promoted
    assert (
        report.assist_champion_market_weight
        == 1.0
    )


def test_market_coverage_is_identical_for_every_candidate():
    rows = [
        make_outcome(
            1,
            market_goals=True,
            market_assists=False,
        ),
        make_outcome(
            2,
            market_goals=False,
            market_assists=True,
        ),
        make_outcome(
            3,
            market_goals=True,
            market_assists=True,
        ),
    ]

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=1,
        )
    )

    assert (
        report.goal_market_observations
        == 2
    )

    assert (
        report.assist_market_observations
        == 2
    )

    assert {
        item.goal_observations
        for item in report.candidates
    } == {2}

    assert {
        item.assist_observations
        for item in report.candidates
    } == {2}


def test_insufficient_observations_cannot_promote():
    rows = [
        make_outcome(
            i,
            model_goal_p=0.50,
            market_goal_p=(
                0.99
                if i % 2 == 0
                else 0.01
            ),
            goals=(
                1
                if i % 2 == 0
                else 0
            ),
        )
        for i in range(10)
    ]

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=20,
        )
    )

    assert not report.goal_promoted
    assert (
        report.goal_champion_market_weight
        == 0.0
    )

    assert (
        "insufficient goal market observations"
        in report.warnings
    )


def test_no_material_improvement_keeps_model_only():
    rows = []

    for i in range(40):
        positive = (
            i % 2 == 0
        )

        rows.append(
            make_outcome(
                i,
                model_goal_p=(
                    0.80
                    if positive
                    else 0.20
                ),
                market_goal_p=(
                    0.805
                    if positive
                    else 0.195
                ),
                goals=(
                    1
                    if positive
                    else 0
                ),
                market_assists=False,
            )
        )

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=20,
            minimum_relative_improvement=0.01,
        )
    )

    assert not report.goal_promoted
    assert (
        report.goal_champion_market_weight
        == 0.0
    )


def test_prediction_order_is_chronological():
    rows = [
        make_outcome(3),
        make_outcome(1),
        make_outcome(2),
    ]

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=1,
        )
    )

    assert report.prediction_order == (
        ("f-1", "p-1"),
        ("f-2", "p-2"),
        ("f-3", "p-3"),
    )


def test_recommended_config_keeps_unvalidated_shot_weights_zero():
    rows = [
        make_outcome(
            i,
            market_goals=False,
            market_assists=False,
        )
        for i in range(3)
    ]

    report = (
        walk_forward_market_blend(
            rows,
            minimum_observations=1,
        )
    )

    config = (
        report.recommended_config
    )

    assert (
        config.shots_market_weight
        == 0.0
    )

    assert (
        config.shots_on_target_market_weight
        == 0.0
    )
