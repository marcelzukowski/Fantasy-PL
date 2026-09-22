from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.data.market_odds import (
    MarketKind,
    MarketQuote,
    MarketSide,
)
from fpl_engine.models.events.market_shadow import (
    build_market_shadow_report,
)
from fpl_engine.models.events.model import (
    AssistEvents,
    BaseBpsParameters,
    CardEvents,
    CleanSheetEvents,
    DefensiveContributionEvents,
    FixtureEventProjection,
    GoalEvents,
    GoalkeeperEvents,
    PenaltyProcess,
    PlayerFixtureEvents,
    PlayerFixtureRate,
    TeamEventProjection,
)


AT = datetime(
    2026,
    9,
    11,
    12,
    0,
    tzinfo=timezone.utc,
)


def _player(
    player_id="player-1",
):
    rate = PlayerFixtureRate(
        player_id=player_id,
        team_id="team-1",
        fixture_id="fixture-1",
        prediction_timestamp=AT,
        position="MID",
        p_appearance=1.0,
        p_start=1.0,
        expected_minutes=90.0,
        minute_distribution=((90, 1.0),),
        starter_minutes_distribution=((90, 1.0),),
        bench_minutes_distribution=((0, 1.0),),
        fixture_npxg_per90=0.4,
        fixture_penalty_xg_per90=0.0,
        fixture_xa_per90=0.2,
        fixture_shots_per90=2.0,
        fixture_shots_on_target_per90=1.0,
        fixture_defcon_per90=None,
        raw_expected_npxg=0.4,
        raw_expected_xa=0.2,
        uncertainty=0.1,
        confidence=0.9,
    )

    return PlayerFixtureEvents(
        rates=rate,
        penalty=PenaltyProcess(
            0.0,
            0.0,
            0.78,
            0.22,
            0.0,
        ),
        goals=GoalEvents(
            0.4,
            0.4,
            0.0,
            0.33,
            (
                0.67,
                0.27,
                0.06,
            ),
        ),
        assists=AssistEvents(
            0.2,
            0.18,
            (
                0.82,
                0.16,
                0.02,
            ),
        ),
        clean_sheet=CleanSheetEvents(
            0.3,
            0.3,
            1.0,
            1.0,
        ),
        goalkeeper=GoalkeeperEvents(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        ),
        defensive_contributions=(
            DefensiveContributionEvents(
                None,
                None,
            )
        ),
        cards=CardEvents(
            0.1,
            0.01,
            "prior",
            "prior",
        ),
        bps=BaseBpsParameters(
            0.4,
            0.2,
            0.3,
            None,
            None,
            0.1,
            0.01,
            90.0,
            None,
            1.0,
            1.0,
            1,
        ),
        uncertainty=0.1,
        confidence=0.9,
        model_version="event_models_v1",
        dataset_version="event_dataset_v1",
        feature_version="event_features_v1",
    )


def _fixture():
    player = _player()

    home = TeamEventProjection(
        "fixture-1",
        "team-1",
        AT,
        1.5,
        0.4,
        1.1,
        0.0,
        0.2,
        0.8,
        1.0,
        (player,),
    )

    away = TeamEventProjection(
        "fixture-1",
        "team-2",
        AT,
        1.0,
        0.0,
        1.0,
        0.0,
        0.0,
        1.0,
        1.0,
        (),
    )

    return FixtureEventProjection(
        "fixture-1",
        AT,
        home,
        away,
    )


def _quote(
    bookmaker,
    side,
    odds,
):
    return MarketQuote(
        provider="the_odds_api",
        bookmaker=bookmaker,
        fixture_id="fixture-1",
        player_id="player-1",
        market=MarketKind.ANYTIME_GOAL,
        side=side,
        decimal_odds=odds,
        quoted_at=(
            AT
            - timedelta(minutes=5)
        ),
    )


def test_shadow_builds_market_prior_and_candidate_grid_without_mutating_projection():
    projection = _fixture()

    quotes = (
        _quote(
            "book-a",
            MarketSide.YES,
            2.0,
        ),
        _quote(
            "book-a",
            MarketSide.NO,
            1.8,
        ),
        _quote(
            "book-b",
            MarketSide.YES,
            2.1,
        ),
        _quote(
            "book-b",
            MarketSide.NO,
            1.75,
        ),
    )

    report = build_market_shadow_report(
        (projection,),
        quotes,
        prediction_timestamp=AT,
    )

    assert report.selected_quote_count == 4
    assert report.consensus_count == 1
    assert report.prior_count == 1
    assert (
        report.players_with_market_prior
        == 1
    )

    assert report.candidates[0].endswith(
        "_g0.00_a0.00_s0.00_t0.00"
    )

    assert report.candidates[-1].endswith(
        "_g1.00_a1.00_s1.00_t1.00"
    )

    row = report.players[0]

    assert (
        row.model.expected_goals
        == pytest.approx(0.4)
    )

    assert row.market is not None

    assert (
        row.candidates[0].goals.value
        == pytest.approx(0.4)
    )

    assert (
        row.candidates[-1].goals.value
        == pytest.approx(
            row.market.expected_goals
        )
    )

    assert (
        projection.home.players[0]
        .goals.expected_goals
        == pytest.approx(0.4)
    )


def test_shadow_rejects_future_quotes_but_keeps_model_fallback():
    projection = _fixture()

    future = MarketQuote(
        provider="the_odds_api",
        bookmaker="book-a",
        fixture_id="fixture-1",
        player_id="player-1",
        market=MarketKind.ANYTIME_GOAL,
        side=MarketSide.YES,
        decimal_odds=2.0,
        quoted_at=(
            AT
            + timedelta(minutes=1)
        ),
    )

    report = build_market_shadow_report(
        (projection,),
        (future,),
        prediction_timestamp=AT,
    )

    assert (
        report.rejected_future_quotes
        == 1
    )

    assert report.prior_count == 0

    assert (
        report.players_without_market_prior
        == 1
    )

    assert all(
        candidate.goals.source
        == "MODEL_ONLY"
        for candidate
        in report.players[0].candidates
    )


def test_shadow_accepts_live_style_one_sided_yes_quote_as_diagnostic_signal():
    projection = _fixture()

    quote = _quote(
        "book-a",
        MarketSide.YES,
        2.5,
    )

    report = build_market_shadow_report(
        (projection,),
        (quote,),
        prediction_timestamp=AT,
    )

    assert (
        report.one_sided_bookmaker_groups
        == 1
    )

    assert report.prior_count == 1

    assert (
        report.players_with_market_prior
        == 1
    )

    assert (
        report.players[0].market
        is not None
    )
