from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable

from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
)
from fpl_engine.models.events.model import (
    PlayerFixtureEvents,
)


MARKET_BLEND_VERSION = "event_market_blend_v1"


class MarketBlendError(ValueError):
    """Invalid model/market fusion contract."""


def _utc(
    value: datetime,
    name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketBlendError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(
        timezone.utc
    )


def _non_negative_optional(
    value: float | None,
    name: str,
) -> float | None:
    if value is None:
        return None

    if (
        not math.isfinite(value)
        or value < 0
    ):
        raise MarketBlendError(
            f"{name} must be finite "
            "and non-negative"
        )

    return float(value)


def _weight(
    value: float,
    name: str,
) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise MarketBlendError(
            f"{name} must be in [0, 1]"
        )

    return float(value)


@dataclass(frozen=True)
class ModelEventExpectation:
    fixture_id: str
    player_id: str
    prediction_timestamp: datetime

    expected_goals: float
    expected_assists: float
    expected_shots: float
    expected_shots_on_target: float | None

    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prediction_timestamp",
            _utc(
                self.prediction_timestamp,
                "prediction_timestamp",
            ),
        )

        if (
            not self.fixture_id
            or not self.player_id
            or not self.model_version
        ):
            raise MarketBlendError(
                "fixture_id, player_id and "
                "model_version are required"
            )

        for name in (
            "expected_goals",
            "expected_assists",
            "expected_shots",
            "expected_shots_on_target",
        ):
            value = _non_negative_optional(
                getattr(self, name),
                name,
            )

            object.__setattr__(
                self,
                name,
                value,
            )

    @classmethod
    def from_prediction(
        cls,
        prediction: PlayerFixtureEvents,
    ) -> "ModelEventExpectation":

        if not isinstance(
            prediction,
            PlayerFixtureEvents,
        ):
            raise MarketBlendError(
                "prediction must be "
                "PlayerFixtureEvents"
            )

        rates = prediction.rates

        minutes = (
            rates.expected_minutes
        )

        shots = (
            rates.fixture_shots_per90
            * minutes
            / 90.0
        )

        if (
            rates.fixture_shots_on_target_per90
            is None
        ):
            shots_on_target = None
        else:
            shots_on_target = (
                rates.fixture_shots_on_target_per90
                * minutes
                / 90.0
            )

        return cls(
            fixture_id=rates.fixture_id,
            player_id=rates.player_id,
            prediction_timestamp=(
                rates.prediction_timestamp
            ),
            expected_goals=(
                prediction.goals.expected_goals
            ),
            expected_assists=(
                prediction.assists.expected_assists
            ),
            expected_shots=shots,
            expected_shots_on_target=(
                shots_on_target
            ),
            model_version=(
                prediction.model_version
            ),
        )


@dataclass(frozen=True)
class MarketBlendConfig:
    goal_market_weight: float = 0.0
    assist_market_weight: float = 0.0
    shots_market_weight: float = 0.0
    shots_on_target_market_weight: float = 0.0

    version: str = MARKET_BLEND_VERSION

    def __post_init__(self) -> None:

        for name in (
            "goal_market_weight",
            "assist_market_weight",
            "shots_market_weight",
            "shots_on_target_market_weight",
        ):
            object.__setattr__(
                self,
                name,
                _weight(
                    getattr(self, name),
                    name,
                ),
            )

    @classmethod
    def shared(
        cls,
        market_weight: float,
    ) -> "MarketBlendConfig":

        weight = _weight(
            market_weight,
            "market_weight",
        )

        return cls(
            goal_market_weight=weight,
            assist_market_weight=weight,
            shots_market_weight=weight,
            shots_on_target_market_weight=weight,
        )

    @property
    def candidate_id(self) -> str:
        return (
            f"{self.version}"
            f"_g{self.goal_market_weight:.2f}"
            f"_a{self.assist_market_weight:.2f}"
            f"_s{self.shots_market_weight:.2f}"
            f"_t{self.shots_on_target_market_weight:.2f}"
        )


@dataclass(frozen=True)
class EventBlendValue:
    value: float | None
    model_value: float | None
    market_value: float | None
    requested_market_weight: float
    effective_market_weight: float
    source: str

    def __post_init__(self) -> None:

        for name in (
            "value",
            "model_value",
            "market_value",
        ):
            value = getattr(
                self,
                name,
            )

            if value is not None:
                _non_negative_optional(
                    value,
                    name,
                )

        _weight(
            self.requested_market_weight,
            "requested_market_weight",
        )

        _weight(
            self.effective_market_weight,
            "effective_market_weight",
        )

        if self.source not in {
            "MODEL_ONLY",
            "MARKET_ONLY",
            "MODEL_MARKET",
            "UNAVAILABLE",
        }:
            raise MarketBlendError(
                f"invalid blend source: "
                f"{self.source!r}"
            )


@dataclass(frozen=True)
class BlendedPlayerEventExpectation:
    fixture_id: str
    player_id: str
    prediction_timestamp: datetime

    goals: EventBlendValue
    assists: EventBlendValue
    shots: EventBlendValue
    shots_on_target: EventBlendValue

    candidate_id: str
    model_version: str
    market_prior_version: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prediction_timestamp",
            _utc(
                self.prediction_timestamp,
                "prediction_timestamp",
            ),
        )


def _blend(
    model_value: float | None,
    market_value: float | None,
    weight: float,
) -> EventBlendValue:

    requested = _weight(
        weight,
        "market_weight",
    )

    model_value = (
        _non_negative_optional(
            model_value,
            "model_value",
        )
    )

    market_value = (
        _non_negative_optional(
            market_value,
            "market_value",
        )
    )

    if (
        model_value is None
        and market_value is None
    ):
        return EventBlendValue(
            value=None,
            model_value=None,
            market_value=None,
            requested_market_weight=requested,
            effective_market_weight=0.0,
            source="UNAVAILABLE",
        )

    if market_value is None:
        return EventBlendValue(
            value=model_value,
            model_value=model_value,
            market_value=None,
            requested_market_weight=requested,
            effective_market_weight=0.0,
            source="MODEL_ONLY",
        )

    if model_value is None:
        return EventBlendValue(
            value=market_value,
            model_value=None,
            market_value=market_value,
            requested_market_weight=requested,
            effective_market_weight=1.0,
            source="MARKET_ONLY",
        )

    if requested == 0.0:
        return EventBlendValue(
            value=model_value,
            model_value=model_value,
            market_value=market_value,
            requested_market_weight=requested,
            effective_market_weight=0.0,
            source="MODEL_ONLY",
        )

    if requested == 1.0:
        return EventBlendValue(
            value=market_value,
            model_value=model_value,
            market_value=market_value,
            requested_market_weight=requested,
            effective_market_weight=1.0,
            source="MARKET_ONLY",
        )

    value = (
        (1.0 - requested)
        * model_value
        + requested
        * market_value
    )

    return EventBlendValue(
        value=value,
        model_value=model_value,
        market_value=market_value,
        requested_market_weight=requested,
        effective_market_weight=requested,
        source="MODEL_MARKET",
    )


def blend_player_event_expectation(
    model: ModelEventExpectation,
    market: PlayerMarketPrior | None,
    *,
    config: MarketBlendConfig,
) -> BlendedPlayerEventExpectation:

    if not isinstance(
        model,
        ModelEventExpectation,
    ):
        raise MarketBlendError(
            "model must be ModelEventExpectation"
        )

    if not isinstance(
        config,
        MarketBlendConfig,
    ):
        raise MarketBlendError(
            "config must be MarketBlendConfig"
        )

    if market is not None:

        if not isinstance(
            market,
            PlayerMarketPrior,
        ):
            raise MarketBlendError(
                "market must be "
                "PlayerMarketPrior or None"
            )

        if (
            market.fixture_id
            != model.fixture_id
            or market.player_id
            != model.player_id
        ):
            raise MarketBlendError(
                "model and market identity mismatch"
            )

        if (
            market.prediction_timestamp
            != model.prediction_timestamp
        ):
            raise MarketBlendError(
                "model and market prediction "
                "timestamps must match"
            )

        market_goals = (
            market.expected_goals
        )

        market_assists = (
            market.expected_assists
        )

        market_shots = (
            market.expected_shots
        )

        market_sot = (
            market.expected_shots_on_target
        )

        market_version = (
            market.version
        )

    else:
        market_goals = None
        market_assists = None
        market_shots = None
        market_sot = None
        market_version = None

    return BlendedPlayerEventExpectation(
        fixture_id=model.fixture_id,
        player_id=model.player_id,
        prediction_timestamp=(
            model.prediction_timestamp
        ),
        goals=_blend(
            model.expected_goals,
            market_goals,
            config.goal_market_weight,
        ),
        assists=_blend(
            model.expected_assists,
            market_assists,
            config.assist_market_weight,
        ),
        shots=_blend(
            model.expected_shots,
            market_shots,
            config.shots_market_weight,
        ),
        shots_on_target=_blend(
            model.expected_shots_on_target,
            market_sot,
            config.shots_on_target_market_weight,
        ),
        candidate_id=(
            config.candidate_id
        ),
        model_version=(
            model.model_version
        ),
        market_prior_version=(
            market_version
        ),
    )


def market_blend_candidate_grid(
    weights: Iterable[float] = (
        0.0,
        0.25,
        0.50,
        0.75,
        1.0,
    ),
) -> tuple[MarketBlendConfig, ...]:

    output = []

    seen = set()

    for raw in weights:
        weight = _weight(
            raw,
            "market_weight",
        )

        if weight in seen:
            continue

        seen.add(weight)

        output.append(
            MarketBlendConfig.shared(
                weight
            )
        )

    if not output:
        raise MarketBlendError(
            "candidate grid cannot be empty"
        )

    return tuple(output)
