from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.data.market_odds import (
    FairMarketProbability,
    MarketKind,
    MarketOddsError,
    MarketOddsLeakageError,
    MarketQuote,
    MarketSide,
    aggregate_market_probabilities,
    devig_selected_quotes,
    select_pit_quotes,
)


AT = datetime(
    2026,
    9,
    11,
    12,
    0,
    tzinfo=timezone.utc,
)


def quote(
    *,
    bookmaker="book-a",
    market=MarketKind.ANYTIME_GOAL,
    side=MarketSide.YES,
    odds=2.0,
    quoted_at=AT - timedelta(minutes=10),
    line=None,
):
    return MarketQuote(
        provider="provider-a",
        bookmaker=bookmaker,
        fixture_id="fixture-1",
        player_id="player-1",
        market=market,
        side=side,
        decimal_odds=odds,
        quoted_at=quoted_at,
        line=line,
        source_record_id=(
            f"{bookmaker}-{side.value}"
        ),
        raw_snapshot_id="snapshot-1",
    )


def test_market_quote_contract_rejects_invalid_semantics():
    with pytest.raises(MarketOddsError):
        quote(
            market=MarketKind.ANYTIME_GOAL,
            side=MarketSide.OVER,
            line=0.5,
        )

    with pytest.raises(MarketOddsError):
        quote(
            market=MarketKind.SHOTS,
            side=MarketSide.OVER,
            line=None,
        )

    with pytest.raises(MarketOddsError):
        quote(
            odds=1.0,
        )


def test_select_pit_quotes_excludes_future_and_keeps_latest():
    old = quote(
        odds=2.20,
        quoted_at=AT - timedelta(hours=2),
    )

    latest = quote(
        odds=2.00,
        quoted_at=AT - timedelta(minutes=10),
    )

    future = quote(
        odds=1.80,
        quoted_at=AT + timedelta(minutes=1),
    )

    stale_other_book = quote(
        bookmaker="book-b",
        odds=2.10,
        quoted_at=AT - timedelta(hours=8),
    )

    result = select_pit_quotes(
        (
            old,
            latest,
            future,
            stale_other_book,
        ),
        prediction_timestamp=AT,
        max_age=timedelta(hours=6),
    )

    assert result.quotes == (latest,)
    assert result.rejected_future == 1
    assert result.rejected_stale == 1


def test_select_pit_quotes_rejects_conflicting_same_timestamp():
    first = quote(
        odds=2.0,
    )

    second = quote(
        odds=2.1,
    )

    with pytest.raises(MarketOddsError):
        select_pit_quotes(
            (first, second),
            prediction_timestamp=AT,
        )


def test_proportional_devig_anytime_goal():
    yes = quote(
        side=MarketSide.YES,
        odds=2.0,
    )

    no = quote(
        side=MarketSide.NO,
        odds=1.8,
    )

    built = devig_selected_quotes(
        (yes, no)
    )

    assert built.unmatched_groups == 0
    assert built.skewed_groups == 0
    assert len(built.probabilities) == 1

    result = built.probabilities[0]

    raw_yes = 1 / 2.0
    raw_no = 1 / 1.8

    expected = (
        raw_yes
        / (raw_yes + raw_no)
    )

    assert result.positive_probability == pytest.approx(
        expected
    )

    assert (
        result.positive_probability
        + result.negative_probability
    ) == pytest.approx(1.0)


def test_devig_count_market_requires_matching_line_and_pair():
    over = quote(
        market=MarketKind.SHOTS,
        side=MarketSide.OVER,
        odds=1.90,
        line=2.5,
    )

    under = quote(
        market=MarketKind.SHOTS,
        side=MarketSide.UNDER,
        odds=1.95,
        line=2.5,
    )

    unmatched = quote(
        bookmaker="book-b",
        market=MarketKind.SHOTS,
        side=MarketSide.OVER,
        odds=2.10,
        line=3.5,
    )

    built = devig_selected_quotes(
        (over, under, unmatched)
    )

    assert len(built.probabilities) == 1
    assert built.unmatched_groups == 1

    result = built.probabilities[0]

    assert result.market == MarketKind.SHOTS
    assert result.line == 2.5


def test_devig_rejects_excessively_skewed_pair():
    yes = quote(
        side=MarketSide.YES,
        quoted_at=AT - timedelta(hours=2),
    )

    no = quote(
        side=MarketSide.NO,
        quoted_at=AT - timedelta(minutes=5),
    )

    built = devig_selected_quotes(
        (yes, no),
        max_pair_skew=timedelta(minutes=10),
    )

    assert built.probabilities == ()
    assert built.skewed_groups == 1


def test_consensus_uses_book_median_and_reports_diagnostics():
    probabilities = (
        FairMarketProbability(
            provider="provider-a",
            bookmaker="book-a",
            fixture_id="fixture-1",
            player_id="player-1",
            market=MarketKind.ANYTIME_GOAL,
            line=None,
            positive_probability=0.40,
            negative_probability=0.60,
            overround=1.06,
            known_at=AT - timedelta(minutes=5),
        ),
        FairMarketProbability(
            provider="provider-a",
            bookmaker="book-b",
            fixture_id="fixture-1",
            player_id="player-1",
            market=MarketKind.ANYTIME_GOAL,
            line=None,
            positive_probability=0.50,
            negative_probability=0.50,
            overround=1.05,
            known_at=AT - timedelta(minutes=10),
        ),
        FairMarketProbability(
            provider="provider-a",
            bookmaker="book-c",
            fixture_id="fixture-1",
            player_id="player-1",
            market=MarketKind.ANYTIME_GOAL,
            line=None,
            positive_probability=0.90,
            negative_probability=0.10,
            overround=1.08,
            known_at=AT - timedelta(minutes=15),
        ),
    )

    result = aggregate_market_probabilities(
        probabilities,
        prediction_timestamp=AT,
    )

    assert len(result) == 1

    consensus = result[0]

    assert consensus.fair_probability == 0.50
    assert consensus.book_count == 3
    assert consensus.dispersion > 0
    assert consensus.median_quote_age_seconds == 600
    assert consensus.max_quote_age_seconds == 900


def test_consensus_rejects_future_market_information():
    future = FairMarketProbability(
        provider="provider-a",
        bookmaker="book-a",
        fixture_id="fixture-1",
        player_id="player-1",
        market=MarketKind.ASSIST,
        line=None,
        positive_probability=0.25,
        negative_probability=0.75,
        overround=1.05,
        known_at=AT + timedelta(seconds=1),
    )

    with pytest.raises(MarketOddsLeakageError):
        aggregate_market_probabilities(
            (future,),
            prediction_timestamp=AT,
        )



def test_count_market_rejects_whole_number_push_line():
    with pytest.raises(MarketOddsError):
        quote(
            market=MarketKind.SHOTS,
            side=MarketSide.OVER,
            odds=1.90,
            line=2.0,
        )



def test_assist_market_supports_half_line_over_under():
    over = quote(
        market=MarketKind.ASSIST,
        side=MarketSide.OVER,
        odds=2.10,
        line=0.5,
    )

    under = quote(
        market=MarketKind.ASSIST,
        side=MarketSide.UNDER,
        odds=1.75,
        line=0.5,
    )

    built = devig_selected_quotes(
        (over, under)
    )

    assert len(built.probabilities) == 1

    result = built.probabilities[0]

    assert result.market == MarketKind.ASSIST
    assert result.line == 0.5



def test_one_sided_market_is_opt_in_and_explicitly_not_devigged():
    quote = MarketQuote(
        provider="the_odds_api",
        bookmaker="book-a",
        fixture_id="fixture-1",
        player_id="player-1",
        market=MarketKind.ANYTIME_GOAL,
        side=MarketSide.YES,
        decimal_odds=2.5,
        quoted_at=AT,
    )

    strict = devig_selected_quotes((quote,))
    assert strict.probabilities == ()
    assert strict.unmatched_groups == 1
    assert strict.one_sided_groups == 0

    diagnostic = devig_selected_quotes(
        (quote,),
        allow_one_sided=True,
    )

    assert diagnostic.unmatched_groups == 0
    assert diagnostic.one_sided_groups == 1
    assert len(diagnostic.probabilities) == 1

    probability = diagnostic.probabilities[0]

    assert probability.positive_probability == pytest.approx(0.4)
    assert probability.negative_probability == pytest.approx(0.6)
    assert probability.method == "one_sided_raw_implied_v1"
