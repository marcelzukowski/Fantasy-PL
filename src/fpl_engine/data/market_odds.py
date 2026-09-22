from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from statistics import median, pstdev
from typing import Iterable


class MarketOddsError(ValueError):
    """Invalid bookmaker market data or market contract."""


class MarketOddsLeakageError(MarketOddsError):
    """A market signal contains information unavailable at prediction time."""


class MarketKind(str, Enum):
    ANYTIME_GOAL = "ANYTIME_GOAL"
    ASSIST = "ASSIST"
    SHOTS = "SHOTS"
    SHOTS_ON_TARGET = "SHOTS_ON_TARGET"


class MarketSide(str, Enum):
    YES = "YES"
    NO = "NO"
    OVER = "OVER"
    UNDER = "UNDER"


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketOddsError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(timezone.utc)


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketOddsError(
            f"{name} must be non-empty"
        )

    return value.strip()


@dataclass(frozen=True)
class MarketQuote:
    provider: str
    bookmaker: str
    fixture_id: str
    player_id: str
    market: MarketKind
    side: MarketSide
    decimal_odds: float
    quoted_at: datetime
    line: float | None = None
    source_record_id: str | None = None
    raw_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            _non_empty(
                self.provider,
                "provider",
            ),
        )
        object.__setattr__(
            self,
            "bookmaker",
            _non_empty(
                self.bookmaker,
                "bookmaker",
            ),
        )
        object.__setattr__(
            self,
            "fixture_id",
            _non_empty(
                self.fixture_id,
                "fixture_id",
            ),
        )
        object.__setattr__(
            self,
            "player_id",
            _non_empty(
                self.player_id,
                "player_id",
            ),
        )

        try:
            market = MarketKind(self.market)
        except ValueError as exc:
            raise MarketOddsError(
                f"unsupported market: {self.market!r}"
            ) from exc

        try:
            side = MarketSide(self.side)
        except ValueError as exc:
            raise MarketOddsError(
                f"unsupported market side: {self.side!r}"
            ) from exc

        object.__setattr__(
            self,
            "market",
            market,
        )
        object.__setattr__(
            self,
            "side",
            side,
        )
        object.__setattr__(
            self,
            "quoted_at",
            _utc(
                self.quoted_at,
                "quoted_at",
            ),
        )

        if (
            type(self.decimal_odds)
            not in (int, float)
            or not math.isfinite(
                self.decimal_odds
            )
            or self.decimal_odds <= 1
        ):
            raise MarketOddsError(
                "decimal_odds must be finite and > 1"
            )

        object.__setattr__(
            self,
            "decimal_odds",
            float(self.decimal_odds),
        )

        if market == MarketKind.ANYTIME_GOAL:
            if self.line is not None:
                raise MarketOddsError(
                    "ANYTIME_GOAL must not have a line"
                )

            if side not in {
                MarketSide.YES,
                MarketSide.NO,
            }:
                raise MarketOddsError(
                    "ANYTIME_GOAL requires YES/NO sides"
                )

        elif (
            market == MarketKind.ASSIST
            and side in {
                MarketSide.YES,
                MarketSide.NO,
            }
        ):
            if self.line is not None:
                raise MarketOddsError(
                    "binary ASSIST must not have a line"
                )

        else:
            if market not in {
                MarketKind.ASSIST,
                MarketKind.SHOTS,
                MarketKind.SHOTS_ON_TARGET,
            }:
                raise MarketOddsError(
                    f"unsupported market semantics: {market.value}"
                )

            if (
                type(self.line)
                not in (int, float)
                or not math.isfinite(self.line)
                or self.line < 0
            ):
                raise MarketOddsError(
                    f"{market.value} requires "
                    "a finite non-negative line"
                )

            line = float(self.line)

            # Only half-lines are two-outcome markets.
            # Whole-number lines may push.
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
                raise MarketOddsError(
                    f"{market.value} V1 requires "
                    "a half-integer line such as 0.5, 1.5 or 2.5"
                )

            if side not in {
                MarketSide.OVER,
                MarketSide.UNDER,
            }:
                raise MarketOddsError(
                    f"{market.value} count market "
                    "requires OVER/UNDER sides"
                )

            object.__setattr__(
                self,
                "line",
                line,
            )

        for name in (
            "source_record_id",
            "raw_snapshot_id",
        ):
            value = getattr(self, name)

            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _non_empty(
                        value,
                        name,
                    ),
                )

    @property
    def implied_probability(self) -> float:
        return 1.0 / self.decimal_odds

    @property
    def quote_key(self) -> tuple:
        return (
            self.provider,
            self.bookmaker,
            self.fixture_id,
            self.player_id,
            self.market.value,
            self.line,
            self.side.value,
        )

    @property
    def book_market_key(self) -> tuple:
        return (
            self.provider,
            self.bookmaker,
            self.fixture_id,
            self.player_id,
            self.market.value,
            self.line,
        )


@dataclass(frozen=True)
class MarketQuoteSelection:
    prediction_timestamp: datetime
    quotes: tuple[MarketQuote, ...]
    rejected_future: int
    rejected_stale: int


def select_pit_quotes(
    quotes: Iterable[MarketQuote],
    *,
    prediction_timestamp: datetime,
    max_age: timedelta | None = None,
) -> MarketQuoteSelection:
    """Select the latest quote per market side known at prediction time."""

    at = _utc(
        prediction_timestamp,
        "prediction_timestamp",
    )

    if max_age is not None:
        if (
            not isinstance(max_age, timedelta)
            or max_age < timedelta(0)
        ):
            raise MarketOddsError(
                "max_age must be a non-negative timedelta"
            )

    latest: dict[tuple, MarketQuote] = {}

    rejected_future = 0
    rejected_stale = 0

    for quote in quotes:
        if not isinstance(quote, MarketQuote):
            raise MarketOddsError(
                "quotes must contain MarketQuote records"
            )

        if quote.quoted_at > at:
            rejected_future += 1
            continue

        if (
            max_age is not None
            and at - quote.quoted_at > max_age
        ):
            rejected_stale += 1
            continue

        key = quote.quote_key
        previous = latest.get(key)

        if previous is None:
            latest[key] = quote
            continue

        if quote.quoted_at > previous.quoted_at:
            latest[key] = quote
            continue

        if quote.quoted_at < previous.quoted_at:
            continue

        if (
            quote.decimal_odds
            != previous.decimal_odds
            or quote.source_record_id
            != previous.source_record_id
            or quote.raw_snapshot_id
            != previous.raw_snapshot_id
        ):
            raise MarketOddsError(
                "conflicting quotes share the same "
                "market key and quoted_at"
            )

    selected = tuple(
        sorted(
            latest.values(),
            key=lambda q: (
                q.fixture_id,
                q.player_id,
                q.market.value,
                -1.0 if q.line is None else q.line,
                q.provider,
                q.bookmaker,
                q.side.value,
            ),
        )
    )

    return MarketQuoteSelection(
        prediction_timestamp=at,
        quotes=selected,
        rejected_future=rejected_future,
        rejected_stale=rejected_stale,
    )


@dataclass(frozen=True)
class FairMarketProbability:
    provider: str
    bookmaker: str
    fixture_id: str
    player_id: str
    market: MarketKind
    line: float | None
    positive_probability: float
    negative_probability: float
    overround: float
    known_at: datetime
    method: str = "proportional_devig_v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "known_at",
            _utc(
                self.known_at,
                "known_at",
            ),
        )

        for name in (
            "positive_probability",
            "negative_probability",
        ):
            value = getattr(self, name)

            if (
                not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise MarketOddsError(
                    f"{name} must be in [0, 1]"
                )

        if not math.isclose(
            self.positive_probability
            + self.negative_probability,
            1.0,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise MarketOddsError(
                "fair probabilities must sum to 1"
            )

        if (
            not math.isfinite(self.overround)
            or self.overround <= 0
        ):
            raise MarketOddsError(
                "overround must be finite and positive"
            )


@dataclass(frozen=True)
class FairMarketBuild:
    probabilities: tuple[FairMarketProbability, ...]
    unmatched_groups: int
    skewed_groups: int
    one_sided_groups: int = 0


def devig_selected_quotes(
    quotes: Iterable[MarketQuote],
    *,
    max_pair_skew: timedelta = timedelta(minutes=10),
    allow_one_sided: bool = False,
) -> FairMarketBuild:
    """Build bookmaker probabilities for selected point-in-time quotes.

    Two-way markets use proportional de-vig. When ``allow_one_sided`` is
    explicitly enabled, a lone Yes/Over (or No/Under) quote is retained as a
    raw implied probability and tagged ``one_sided_raw_implied_v1``. This is
    intentionally not described as de-vigged and is suitable only for
    diagnostic/shadow evaluation until calibrated out of sample.
    """

    if (
        not isinstance(max_pair_skew, timedelta)
        or max_pair_skew < timedelta(0)
    ):
        raise MarketOddsError(
            "max_pair_skew must be a non-negative timedelta"
        )

    groups: dict[
        tuple,
        dict[MarketSide, MarketQuote],
    ] = {}

    for quote in quotes:
        if not isinstance(quote, MarketQuote):
            raise MarketOddsError(
                "quotes must contain MarketQuote records"
            )

        sides = groups.setdefault(
            quote.book_market_key,
            {},
        )

        if quote.side in sides:
            raise MarketOddsError(
                "selected quotes contain duplicate side "
                "for one bookmaker market"
            )

        sides[quote.side] = quote

    probabilities: list[
        FairMarketProbability
    ] = []

    unmatched = 0
    skewed = 0
    one_sided = 0

    for key in sorted(
        groups,
        key=lambda value: str(value),
    ):
        sides = groups[key]
        market = MarketKind(key[4])

        if (
            market == MarketKind.ANYTIME_GOAL
            or (
                market == MarketKind.ASSIST
                and key[5] is None
            )
        ):
            positive_side = MarketSide.YES
            negative_side = MarketSide.NO
        else:
            positive_side = MarketSide.OVER
            negative_side = MarketSide.UNDER

        positive = sides.get(
            positive_side
        )
        negative = sides.get(
            negative_side
        )

        if positive is None or negative is None:
            if not allow_one_sided:
                unmatched += 1
                continue

            present = positive if positive is not None else negative

            if present is None:
                unmatched += 1
                continue

            raw = present.implied_probability

            if positive is not None:
                fair_positive = raw
            else:
                fair_positive = 1.0 - raw

            probabilities.append(
                FairMarketProbability(
                    provider=present.provider,
                    bookmaker=present.bookmaker,
                    fixture_id=present.fixture_id,
                    player_id=present.player_id,
                    market=market,
                    line=present.line,
                    positive_probability=fair_positive,
                    negative_probability=1.0 - fair_positive,
                    overround=1.0,
                    known_at=present.quoted_at,
                    method="one_sided_raw_implied_v1",
                )
            )

            one_sided += 1
            continue

        if abs(
            positive.quoted_at
            - negative.quoted_at
        ) > max_pair_skew:
            skewed += 1
            continue

        positive_raw = (
            positive.implied_probability
        )
        negative_raw = (
            negative.implied_probability
        )

        overround = (
            positive_raw
            + negative_raw
        )

        fair_positive = (
            positive_raw
            / overround
        )

        fair_negative = (
            negative_raw
            / overround
        )

        probabilities.append(
            FairMarketProbability(
                provider=positive.provider,
                bookmaker=positive.bookmaker,
                fixture_id=positive.fixture_id,
                player_id=positive.player_id,
                market=market,
                line=positive.line,
                positive_probability=fair_positive,
                negative_probability=fair_negative,
                overround=overround,
                known_at=max(
                    positive.quoted_at,
                    negative.quoted_at,
                ),
            )
        )

    return FairMarketBuild(
        probabilities=tuple(
            probabilities
        ),
        unmatched_groups=unmatched,
        skewed_groups=skewed,
        one_sided_groups=one_sided,
    )


@dataclass(frozen=True)
class MarketConsensus:
    fixture_id: str
    player_id: str
    market: MarketKind
    line: float | None
    fair_probability: float
    book_count: int
    dispersion: float
    median_quote_age_seconds: float
    max_quote_age_seconds: float
    known_at: datetime
    method: str = "median_books_v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "known_at",
            _utc(
                self.known_at,
                "known_at",
            ),
        )

        if not 0 <= self.fair_probability <= 1:
            raise MarketOddsError(
                "fair_probability must be in [0, 1]"
            )

        if self.book_count < 1:
            raise MarketOddsError(
                "book_count must be positive"
            )

        if (
            self.dispersion < 0
            or self.median_quote_age_seconds < 0
            or self.max_quote_age_seconds < 0
        ):
            raise MarketOddsError(
                "market diagnostics cannot be negative"
            )


def aggregate_market_probabilities(
    probabilities: Iterable[FairMarketProbability],
    *,
    prediction_timestamp: datetime,
    max_age: timedelta | None = None,
) -> tuple[MarketConsensus, ...]:
    """Aggregate independent bookmaker fair probabilities by median."""

    at = _utc(
        prediction_timestamp,
        "prediction_timestamp",
    )

    if max_age is not None:
        if (
            not isinstance(max_age, timedelta)
            or max_age < timedelta(0)
        ):
            raise MarketOddsError(
                "max_age must be a non-negative timedelta"
            )

    grouped: dict[
        tuple,
        dict[tuple[str, str], FairMarketProbability],
    ] = {}

    for probability in probabilities:
        if not isinstance(
            probability,
            FairMarketProbability,
        ):
            raise MarketOddsError(
                "probabilities must contain "
                "FairMarketProbability records"
            )

        if probability.known_at > at:
            raise MarketOddsLeakageError(
                "market probability became known "
                "after prediction_timestamp"
            )

        if (
            max_age is not None
            and at - probability.known_at > max_age
        ):
            continue

        key = (
            probability.fixture_id,
            probability.player_id,
            probability.market.value,
            probability.line,
        )

        book_key = (
            probability.provider,
            probability.bookmaker,
        )

        books = grouped.setdefault(
            key,
            {},
        )

        previous = books.get(
            book_key
        )

        if (
            previous is None
            or probability.known_at
            > previous.known_at
        ):
            books[book_key] = probability

    output: list[MarketConsensus] = []

    for key in sorted(
        grouped,
        key=lambda value: str(value),
    ):
        books = tuple(
            grouped[key].values()
        )

        values = [
            item.positive_probability
            for item in books
        ]

        ages = [
            (
                at
                - item.known_at
            ).total_seconds()
            for item in books
        ]

        output.append(
            MarketConsensus(
                fixture_id=key[0],
                player_id=key[1],
                market=MarketKind(key[2]),
                line=key[3],
                fair_probability=float(
                    median(values)
                ),
                book_count=len(books),
                dispersion=(
                    float(
                        pstdev(values)
                    )
                    if len(values) > 1
                    else 0.0
                ),
                median_quote_age_seconds=float(
                    median(ages)
                ),
                max_quote_age_seconds=float(
                    max(ages)
                ),
                known_at=max(
                    item.known_at
                    for item in books
                ),
            )
        )

    return tuple(output)
