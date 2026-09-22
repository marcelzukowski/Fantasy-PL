from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from statistics import median
from typing import Iterable

from fpl_engine.data.market_odds import (
    MarketConsensus,
    MarketKind,
    MarketOddsError,
    MarketOddsLeakageError,
)


MARKET_PRIOR_VERSION = (
    "player_market_prior_v1_poisson_inversion"
)


class MarketPriorError(ValueError):
    """Invalid market-prior construction."""


def _utc(
    value: datetime,
    name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketPriorError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _strict_probability(
    value: float,
) -> float:
    if (
        not math.isfinite(value)
        or not 0 < value < 1
    ):
        raise MarketPriorError(
            "market probability must be strictly "
            "between 0 and 1"
        )

    return float(value)


def binary_probability_to_poisson_mean(
    probability: float,
) -> float:
    """Infer Poisson mean from P(X >= 1)."""

    p = _strict_probability(
        probability
    )

    return -math.log1p(-p)


def _poisson_cdf(
    maximum: int,
    mean: float,
) -> float:
    if maximum < 0:
        return 0.0

    if mean < 0 or not math.isfinite(mean):
        raise MarketPriorError(
            "Poisson mean must be finite "
            "and non-negative"
        )

    term = math.exp(-mean)
    total = term

    for count in range(
        1,
        maximum + 1,
    ):
        term *= mean / count
        total += term

    return min(
        1.0,
        max(0.0, total),
    )


def poisson_over_probability(
    mean: float,
    line: float,
) -> float:
    """P(X > line) for a half-integer count line."""

    if (
        not math.isfinite(line)
        or line < 0
    ):
        raise MarketPriorError(
            "line must be finite and non-negative"
        )

    doubled = line * 2.0

    if (
        not math.isclose(
            doubled,
            round(doubled),
            rel_tol=0,
            abs_tol=1e-12,
        )
        or int(round(doubled)) % 2 == 0
    ):
        raise MarketPriorError(
            "Poisson count inversion V1 "
            "requires a half-integer line"
        )

    threshold = (
        math.floor(line)
        + 1
    )

    return max(
        0.0,
        min(
            1.0,
            1.0
            - _poisson_cdf(
                threshold - 1,
                mean,
            ),
        ),
    )


def over_probability_to_poisson_mean(
    probability: float,
    line: float,
) -> float:
    """Infer lambda from a half-line over probability."""

    target = _strict_probability(
        probability
    )

    # Validate line using the same semantics
    # as poisson_over_probability.
    poisson_over_probability(
        1.0,
        line,
    )

    low = 0.0
    high = 1.0

    while (
        poisson_over_probability(
            high,
            line,
        )
        < target
    ):
        high *= 2.0

        if high > 100.0:
            raise MarketPriorError(
                "could not bracket Poisson "
                "mean for market probability"
            )

    for _ in range(80):
        middle = (
            low + high
        ) / 2.0

        value = (
            poisson_over_probability(
                middle,
                line,
            )
        )

        if value < target:
            low = middle
        else:
            high = middle

    return (
        low + high
    ) / 2.0


@dataclass(frozen=True)
class MarketEventSignal:
    fixture_id: str
    player_id: str
    market: MarketKind
    line: float | None
    fair_probability: float
    implied_event_mean: float
    book_count: int
    dispersion: float
    median_quote_age_seconds: float
    max_quote_age_seconds: float
    known_at: datetime
    method: str

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "known_at",
            _utc(
                self.known_at,
                "known_at",
            ),
        )

        if (
            not math.isfinite(
                self.implied_event_mean
            )
            or self.implied_event_mean < 0
        ):
            raise MarketPriorError(
                "implied_event_mean must "
                "be finite and non-negative"
            )


def consensus_to_event_signal(
    consensus: MarketConsensus,
) -> MarketEventSignal:
    if not isinstance(
        consensus,
        MarketConsensus,
    ):
        raise MarketPriorError(
            "expected MarketConsensus"
        )

    probability = (
        _strict_probability(
            consensus.fair_probability
        )
    )

    if (
        consensus.market
        == MarketKind.ANYTIME_GOAL
        or (
            consensus.market
            == MarketKind.ASSIST
            and consensus.line is None
        )
    ):
        implied_mean = (
            binary_probability_to_poisson_mean(
                probability
            )
        )

        method = (
            "binary_at_least_one_"
            "poisson_inversion_v1"
        )

    elif consensus.market in {
        MarketKind.ASSIST,
        MarketKind.SHOTS,
        MarketKind.SHOTS_ON_TARGET,
    }:
        if consensus.line is None:
            raise MarketPriorError(
                "count market consensus "
                "requires line"
            )

        implied_mean = (
            over_probability_to_poisson_mean(
                probability,
                consensus.line,
            )
        )

        method = (
            "half_line_over_"
            "poisson_inversion_v1"
        )

    else:
        raise MarketPriorError(
            f"unsupported market "
            f"{consensus.market!r}"
        )

    return MarketEventSignal(
        fixture_id=consensus.fixture_id,
        player_id=consensus.player_id,
        market=consensus.market,
        line=consensus.line,
        fair_probability=probability,
        implied_event_mean=implied_mean,
        book_count=consensus.book_count,
        dispersion=consensus.dispersion,
        median_quote_age_seconds=(
            consensus.median_quote_age_seconds
        ),
        max_quote_age_seconds=(
            consensus.max_quote_age_seconds
        ),
        known_at=consensus.known_at,
        method=method,
    )


@dataclass(frozen=True)
class PlayerMarketPrior:
    fixture_id: str
    player_id: str
    prediction_timestamp: datetime
    expected_goals: float | None
    expected_assists: float | None
    expected_shots: float | None
    expected_shots_on_target: float | None
    signals: tuple[
        MarketEventSignal,
        ...
    ]
    known_at: datetime
    warnings: tuple[str, ...] = ()
    version: str = MARKET_PRIOR_VERSION

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "prediction_timestamp",
            _utc(
                self.prediction_timestamp,
                "prediction_timestamp",
            ),
        )

        object.__setattr__(
            self,
            "known_at",
            _utc(
                self.known_at,
                "known_at",
            ),
        )

        if self.known_at > self.prediction_timestamp:
            raise MarketOddsLeakageError(
                "market prior became known "
                "after prediction_timestamp"
            )

        for name in (
            "expected_goals",
            "expected_assists",
            "expected_shots",
            "expected_shots_on_target",
        ):
            value = getattr(
                self,
                name,
            )

            if value is not None and (
                not math.isfinite(value)
                or value < 0
            ):
                raise MarketPriorError(
                    f"{name} must be finite "
                    "and non-negative"
                )

    @property
    def available_markets(
        self,
    ) -> tuple[MarketKind, ...]:
        return tuple(
            sorted(
                {
                    signal.market
                    for signal
                    in self.signals
                },
                key=lambda item: item.value,
            )
        )


def _median_for_market(
    signals: tuple[
        MarketEventSignal,
        ...
    ],
    market: MarketKind,
) -> float | None:
    values = [
        signal.implied_event_mean
        for signal in signals
        if signal.market == market
    ]

    if not values:
        return None

    return float(
        median(values)
    )


def build_player_market_priors(
    consensuses: Iterable[
        MarketConsensus
    ],
    *,
    prediction_timestamp: datetime,
) -> tuple[
    PlayerMarketPrior,
    ...
]:
    """Build unconditional fixture-level player market priors.

    These values deliberately do not divide by expected minutes.
    Player prop prices already embed bookmaker beliefs about
    appearance/start/minutes, so the market prior remains an
    unconditional fixture-level signal.
    """

    at = _utc(
        prediction_timestamp,
        "prediction_timestamp",
    )

    grouped: dict[
        tuple[str, str],
        list[MarketEventSignal],
    ] = {}

    for consensus in consensuses:
        if not isinstance(
            consensus,
            MarketConsensus,
        ):
            raise MarketPriorError(
                "consensuses must contain "
                "MarketConsensus records"
            )

        if consensus.known_at > at:
            raise MarketOddsLeakageError(
                "market consensus became known "
                "after prediction_timestamp"
            )

        signal = (
            consensus_to_event_signal(
                consensus
            )
        )

        grouped.setdefault(
            (
                signal.fixture_id,
                signal.player_id,
            ),
            [],
        ).append(
            signal
        )

    output: list[
        PlayerMarketPrior
    ] = []

    for (
        fixture_id,
        player_id,
    ), raw_signals in sorted(
        grouped.items()
    ):
        signals = tuple(
            sorted(
                raw_signals,
                key=lambda item: (
                    item.market.value,
                    -1.0
                    if item.line is None
                    else item.line,
                ),
            )
        )

        goals = _median_for_market(
            signals,
            MarketKind.ANYTIME_GOAL,
        )

        assists = _median_for_market(
            signals,
            MarketKind.ASSIST,
        )

        shots = _median_for_market(
            signals,
            MarketKind.SHOTS,
        )

        shots_on_target = (
            _median_for_market(
                signals,
                MarketKind.SHOTS_ON_TARGET,
            )
        )

        warnings: list[str] = []

        if (
            shots is not None
            and shots_on_target is not None
            and shots_on_target
            > shots + 1e-12
        ):
            warnings.append(
                "market SOT expectation exceeds "
                "market shots expectation"
            )

        output.append(
            PlayerMarketPrior(
                fixture_id=fixture_id,
                player_id=player_id,
                prediction_timestamp=at,
                expected_goals=goals,
                expected_assists=assists,
                expected_shots=shots,
                expected_shots_on_target=(
                    shots_on_target
                ),
                signals=signals,
                known_at=max(
                    signal.known_at
                    for signal in signals
                ),
                warnings=tuple(
                    warnings
                ),
            )
        )

    return tuple(output)
