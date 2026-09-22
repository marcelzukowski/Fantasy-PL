from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from fpl_engine.data.market_odds import (
    MarketQuote,
    aggregate_market_probabilities,
    devig_selected_quotes,
    select_pit_quotes,
)
from fpl_engine.models.events.market_blend import (
    BlendedPlayerEventExpectation,
    MarketBlendConfig,
    ModelEventExpectation,
    blend_player_event_expectation,
    market_blend_candidate_grid,
)
from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
    build_player_market_priors,
)
from fpl_engine.models.events.model import (
    FixtureEventProjection,
)


class MarketShadowError(ValueError):
    """Invalid bookmaker shadow evaluation input."""


def _utc(
    value: datetime,
    name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketShadowError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(
        timezone.utc
    )


@dataclass(frozen=True)
class MarketShadowPlayer:
    fixture_id: str
    player_id: str
    model_prediction_timestamp: datetime
    model: ModelEventExpectation
    market: PlayerMarketPrior | None
    candidates: tuple[
        BlendedPlayerEventExpectation,
        ...,
    ]


@dataclass(frozen=True)
class MarketShadowReport:
    prediction_timestamp: datetime
    model_prediction_timestamp: datetime
    selected_quote_count: int
    rejected_future_quotes: int
    rejected_stale_quotes: int
    unmatched_bookmaker_groups: int
    skewed_bookmaker_groups: int
    one_sided_bookmaker_groups: int
    consensus_count: int
    prior_count: int
    players_with_market_prior: int
    players_without_market_prior: int
    candidates: tuple[str, ...]
    players: tuple[
        MarketShadowPlayer,
        ...,
    ]


def build_market_shadow_report(
    event_projections: Iterable[
        FixtureEventProjection
    ],
    quotes: Iterable[MarketQuote],
    *,
    prediction_timestamp: datetime,
    model_prediction_timestamp: datetime | None = None,
    max_quote_age: timedelta | None = timedelta(
        hours=6
    ),
    configs: Sequence[
        MarketBlendConfig
    ] | None = None,
) -> MarketShadowReport:
    """Evaluate bookmaker priors as a shadow challenger."""

    at = _utc(
        prediction_timestamp,
        "prediction_timestamp",
    )

    model_at = (
        at
        if model_prediction_timestamp is None
        else _utc(model_prediction_timestamp, "model_prediction_timestamp")
    )
    if model_at > at:
        raise MarketShadowError(
            "model_prediction_timestamp cannot be later than shadow prediction_timestamp"
        )

    projections = tuple(
        event_projections
    )

    for projection in projections:
        if not isinstance(
            projection,
            FixtureEventProjection,
        ):
            raise MarketShadowError(
                "event_projections must contain "
                "FixtureEventProjection records"
            )

        if projection.prediction_timestamp != model_at:
            raise MarketShadowError(
                "event projection "
                "prediction_timestamp mismatch"
            )

    selected = select_pit_quotes(
        quotes,
        prediction_timestamp=at,
        max_age=max_quote_age,
    )

    fair = devig_selected_quotes(
        selected.quotes,
        allow_one_sided=True,
    )

    consensuses = (
        aggregate_market_probabilities(
            fair.probabilities,
            prediction_timestamp=at,
            max_age=max_quote_age,
        )
    )

    priors = build_player_market_priors(
        consensuses,
        prediction_timestamp=at,
    )

    prior_by_key = {
        (
            item.fixture_id,
            item.player_id,
        ): item
        for item in priors
    }

    blend_configs = (
        tuple(configs)
        if configs is not None
        else market_blend_candidate_grid()
    )

    if not blend_configs:
        raise MarketShadowError(
            "at least one market blend "
            "config is required"
        )

    if not all(
        isinstance(
            item,
            MarketBlendConfig,
        )
        for item in blend_configs
    ):
        raise MarketShadowError(
            "configs must contain "
            "MarketBlendConfig records"
        )

    rows: list[
        MarketShadowPlayer
    ] = []

    with_market = 0
    without_market = 0

    for projection in projections:
        player_predictions = (
            *projection.home.players,
            *projection.away.players,
        )

        for prediction in player_predictions:
            source_model = (
                ModelEventExpectation
                .from_prediction(
                    prediction
                )
            )

            # The model values are immutable V22 values from ``model_at``.
            # The blend itself is a new observation at ``at``; normalising the
            # in-memory expectation to that observation keeps the existing
            # blend contract coherent without claiming V22 ran at that time.
            model = replace(
                source_model,
                prediction_timestamp=at,
            )

            market = prior_by_key.get(
                (
                    model.fixture_id,
                    model.player_id,
                )
            )

            if market is None:
                without_market += 1
            else:
                with_market += 1

            candidates = tuple(
                blend_player_event_expectation(
                    model,
                    market,
                    config=config,
                )
                for config in blend_configs
            )

            rows.append(
                MarketShadowPlayer(
                    fixture_id=(
                        model.fixture_id
                    ),
                    player_id=(
                        model.player_id
                    ),
                    model_prediction_timestamp=model_at,
                    model=model,
                    market=market,
                    candidates=candidates,
                )
            )

    rows.sort(
        key=lambda item: (
            item.fixture_id,
            item.player_id,
        )
    )

    return MarketShadowReport(
        prediction_timestamp=at,
        model_prediction_timestamp=model_at,
        selected_quote_count=len(
            selected.quotes
        ),
        rejected_future_quotes=(
            selected.rejected_future
        ),
        rejected_stale_quotes=(
            selected.rejected_stale
        ),
        unmatched_bookmaker_groups=(
            fair.unmatched_groups
        ),
        skewed_bookmaker_groups=(
            fair.skewed_groups
        ),
        one_sided_bookmaker_groups=(
            fair.one_sided_groups
        ),
        consensus_count=len(
            consensuses
        ),
        prior_count=len(
            priors
        ),
        players_with_market_prior=(
            with_market
        ),
        players_without_market_prior=(
            without_market
        ),
        candidates=tuple(
            config.candidate_id
            for config in blend_configs
        ),
        players=tuple(
            rows
        ),
    )
