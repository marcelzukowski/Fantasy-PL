from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable

from fpl_engine.models.events.market_blend import (
    MarketBlendConfig,
    ModelEventExpectation,
    blend_player_event_expectation,
    market_blend_candidate_grid,
)
from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
)


MARKET_VALIDATION_VERSION = (
    "market_blend_walk_forward_v1"
)


class MarketValidationError(ValueError):
    """Invalid market blend validation contract."""


class MarketValidationLeakageError(
    MarketValidationError
):
    """Outcome or market information leaks past prediction time."""


def _utc(
    value: datetime,
    name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MarketValidationError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(
        timezone.utc
    )


@dataclass(frozen=True)
class MarketBlendOutcome:
    model: ModelEventExpectation
    market: PlayerMarketPrior
    outcome_known_at: datetime
    goals: int
    assists: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.model,
            ModelEventExpectation,
        ):
            raise MarketValidationError(
                "model must be ModelEventExpectation"
            )

        if not isinstance(
            self.market,
            PlayerMarketPrior,
        ):
            raise MarketValidationError(
                "market must be PlayerMarketPrior"
            )

        known = _utc(
            self.outcome_known_at,
            "outcome_known_at",
        )

        object.__setattr__(
            self,
            "outcome_known_at",
            known,
        )

        if (
            self.model.fixture_id
            != self.market.fixture_id
            or self.model.player_id
            != self.market.player_id
        ):
            raise MarketValidationError(
                "model and market identity mismatch"
            )

        if (
            self.model.prediction_timestamp
            != self.market.prediction_timestamp
        ):
            raise MarketValidationError(
                "model and market prediction "
                "timestamps must match"
            )

        if (
            self.market.known_at
            > self.model.prediction_timestamp
        ):
            raise MarketValidationLeakageError(
                "market prior became known "
                "after prediction"
            )

        if (
            known
            <= self.model.prediction_timestamp
        ):
            raise MarketValidationLeakageError(
                "outcome must become known "
                "after prediction"
            )

        if (
            type(self.goals) is not int
            or self.goals < 0
            or type(self.assists) is not int
            or self.assists < 0
        ):
            raise MarketValidationError(
                "goals and assists must be "
                "non-negative integers"
            )


@dataclass(frozen=True)
class MarketBlendCandidateMetrics:
    candidate_id: str
    market_weight: float

    goal_observations: int
    goal_brier: float | None
    goal_log_loss: float | None
    goal_poisson_deviance: float | None
    goal_calibration_error: float | None

    assist_observations: int
    assist_brier: float | None
    assist_log_loss: float | None
    assist_calibration_error: float | None


@dataclass(frozen=True)
class MarketBlendWalkForwardReport:
    version: str
    candidates: tuple[
        MarketBlendCandidateMetrics,
        ...
    ]

    goal_champion_market_weight: float
    assist_champion_market_weight: float

    goal_promoted: bool
    assist_promoted: bool

    goal_market_observations: int
    assist_market_observations: int

    prediction_order: tuple[
        tuple[str, str],
        ...
    ]

    warnings: tuple[str, ...] = ()

    @property
    def recommended_config(
        self,
    ) -> MarketBlendConfig:
        return MarketBlendConfig(
            goal_market_weight=(
                self.goal_champion_market_weight
            ),
            assist_market_weight=(
                self.assist_champion_market_weight
            ),
            shots_market_weight=0.0,
            shots_on_target_market_weight=0.0,
        )


def _binary_metrics(
    rows: list[
        tuple[float, bool]
    ],
) -> tuple[
    float,
    float,
    float,
]:
    if not rows:
        raise MarketValidationError(
            "cannot score empty binary rows"
        )

    eps = 1e-12

    brier = 0.0
    log_loss = 0.0

    for probability, outcome in rows:

        p = min(
            1.0 - eps,
            max(
                eps,
                probability,
            ),
        )

        y = float(outcome)

        brier += (
            p - y
        ) ** 2

        log_loss += -(
            y * math.log(p)
            + (1.0 - y)
            * math.log(1.0 - p)
        )

    n = len(rows)

    return (
        brier / n,
        log_loss / n,
        _ece(rows),
    )


def _ece(
    rows: list[
        tuple[float, bool]
    ],
    bins: int = 5,
) -> float:
    buckets: list[
        list[tuple[float, bool]]
    ] = [
        []
        for _ in range(bins)
    ]

    for probability, outcome in rows:

        index = min(
            bins - 1,
            int(
                probability
                * bins
            ),
        )

        buckets[index].append(
            (
                probability,
                outcome,
            )
        )

    total = len(rows)

    error = 0.0

    for bucket in buckets:
        if not bucket:
            continue

        mean_probability = (
            sum(
                row[0]
                for row in bucket
            )
            / len(bucket)
        )

        mean_outcome = (
            sum(
                float(row[1])
                for row in bucket
            )
            / len(bucket)
        )

        error += (
            len(bucket)
            / total
            * abs(
                mean_probability
                - mean_outcome
            )
        )

    return error


def _poisson_deviance(
    expected: float,
    observed: int,
) -> float:

    if (
        not math.isfinite(expected)
        or expected < 0
    ):
        raise MarketValidationError(
            "expected event count must be "
            "finite and non-negative"
        )

    safe = max(
        expected,
        1e-12,
    )

    if observed == 0:
        return 2.0 * expected

    return 2.0 * (
        observed
        * math.log(
            observed / safe
        )
        - (
            observed
            - expected
        )
    )


def _candidate_metrics(
    config: MarketBlendConfig,
    outcomes: tuple[
        MarketBlendOutcome,
        ...
    ],
) -> MarketBlendCandidateMetrics:

    goal_binary = []
    goal_deviance = []

    assist_binary = []

    for outcome in outcomes:

        blended = (
            blend_player_event_expectation(
                outcome.model,
                outcome.market,
                config=config,
            )
        )

        # Important:
        # compare MODEL_ONLY and MARKET candidates
        # only on rows where the corresponding market
        # actually existed.
        if (
            outcome.market.expected_goals
            is not None
        ):
            expected = (
                blended.goals.value
            )

            if expected is None:
                raise MarketValidationError(
                    "goal blend unexpectedly unavailable"
                )

            probability = (
                1.0
                - math.exp(
                    -expected
                )
            )

            goal_binary.append(
                (
                    probability,
                    outcome.goals > 0,
                )
            )

            goal_deviance.append(
                _poisson_deviance(
                    expected,
                    outcome.goals,
                )
            )

        if (
            outcome.market.expected_assists
            is not None
        ):
            expected = (
                blended.assists.value
            )

            if expected is None:
                raise MarketValidationError(
                    "assist blend unexpectedly unavailable"
                )

            probability = (
                1.0
                - math.exp(
                    -expected
                )
            )

            assist_binary.append(
                (
                    probability,
                    outcome.assists > 0,
                )
            )

    if goal_binary:
        (
            goal_brier,
            goal_log_loss,
            goal_ece,
        ) = _binary_metrics(
            goal_binary
        )

        goal_poisson = (
            sum(goal_deviance)
            / len(goal_deviance)
        )

    else:
        goal_brier = None
        goal_log_loss = None
        goal_poisson = None
        goal_ece = None

    if assist_binary:
        (
            assist_brier,
            assist_log_loss,
            assist_ece,
        ) = _binary_metrics(
            assist_binary
        )

    else:
        assist_brier = None
        assist_log_loss = None
        assist_ece = None

    return MarketBlendCandidateMetrics(
        candidate_id=(
            config.candidate_id
        ),
        market_weight=(
            config.goal_market_weight
        ),
        goal_observations=(
            len(goal_binary)
        ),
        goal_brier=goal_brier,
        goal_log_loss=goal_log_loss,
        goal_poisson_deviance=(
            goal_poisson
        ),
        goal_calibration_error=(
            goal_ece
        ),
        assist_observations=(
            len(assist_binary)
        ),
        assist_brier=assist_brier,
        assist_log_loss=assist_log_loss,
        assist_calibration_error=(
            assist_ece
        ),
    )


def _baseline(
    candidates: tuple[
        MarketBlendCandidateMetrics,
        ...
    ],
) -> MarketBlendCandidateMetrics:

    matches = [
        candidate
        for candidate in candidates
        if math.isclose(
            candidate.market_weight,
            0.0,
            rel_tol=0,
            abs_tol=1e-12,
        )
    ]

    if len(matches) != 1:
        raise MarketValidationError(
            "candidate grid must contain "
            "exactly one MODEL_ONLY weight 0"
        )

    return matches[0]


def _goal_champion(
    candidates: tuple[
        MarketBlendCandidateMetrics,
        ...
    ],
    *,
    minimum_observations: int,
    minimum_relative_improvement: float,
) -> tuple[
    float,
    bool,
]:

    baseline = _baseline(
        candidates
    )

    if (
        baseline.goal_observations
        < minimum_observations
        or baseline.goal_log_loss
        is None
        or baseline.goal_poisson_deviance
        is None
    ):
        return 0.0, False

    eligible = [
        candidate
        for candidate in candidates
        if (
            candidate.goal_observations
            == baseline.goal_observations
            and candidate.goal_log_loss
            is not None
            and candidate.goal_poisson_deviance
            is not None
        )
    ]

    best = min(
        eligible,
        key=lambda candidate: (
            candidate.goal_log_loss,
            candidate.goal_poisson_deviance,
            candidate.market_weight,
        ),
    )

    threshold = (
        baseline.goal_log_loss
        * (
            1.0
            - minimum_relative_improvement
        )
    )

    promoted = (
        best.market_weight > 0
        and best.goal_log_loss
        < threshold
        and best.goal_poisson_deviance
        <= baseline.goal_poisson_deviance
    )

    if not promoted:
        return 0.0, False

    return (
        best.market_weight,
        True,
    )


def _assist_champion(
    candidates: tuple[
        MarketBlendCandidateMetrics,
        ...
    ],
    *,
    minimum_observations: int,
    minimum_relative_improvement: float,
) -> tuple[
    float,
    bool,
]:

    baseline = _baseline(
        candidates
    )

    if (
        baseline.assist_observations
        < minimum_observations
        or baseline.assist_log_loss
        is None
    ):
        return 0.0, False

    eligible = [
        candidate
        for candidate in candidates
        if (
            candidate.assist_observations
            == baseline.assist_observations
            and candidate.assist_log_loss
            is not None
        )
    ]

    best = min(
        eligible,
        key=lambda candidate: (
            candidate.assist_log_loss,
            candidate.market_weight,
        ),
    )

    threshold = (
        baseline.assist_log_loss
        * (
            1.0
            - minimum_relative_improvement
        )
    )

    promoted = (
        best.market_weight > 0
        and best.assist_log_loss
        < threshold
    )

    if not promoted:
        return 0.0, False

    return (
        best.market_weight,
        True,
    )


def walk_forward_market_blend(
    outcomes: Iterable[
        MarketBlendOutcome
    ],
    *,
    weights: Iterable[float] = (
        0.0,
        0.25,
        0.50,
        0.75,
        1.0,
    ),
    minimum_observations: int = 200,
    minimum_relative_improvement: float = 0.01,
) -> MarketBlendWalkForwardReport:
    """Evaluate fixed market weights on chronological PIT-safe outcomes.

    Candidate weights themselves have no fitted parameters. The chronological
    ordering exists to preserve and audit the point-in-time contract; the
    returned champion is model-selection evidence and still requires an
    independent season before production promotion.
    """

    if (
        type(minimum_observations)
        is not int
        or minimum_observations < 1
    ):
        raise MarketValidationError(
            "minimum_observations must "
            "be a positive integer"
        )

    if (
        type(minimum_relative_improvement)
        not in (int, float)
        or not math.isfinite(
            minimum_relative_improvement
        )
        or not 0
        <= minimum_relative_improvement
        < 1
    ):
        raise MarketValidationError(
            "minimum_relative_improvement "
            "must be in [0, 1)"
        )

    ordered = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.model.prediction_timestamp,
                item.model.fixture_id,
                item.model.player_id,
            ),
        )
    )

    if not ordered:
        raise MarketValidationError(
            "outcomes cannot be empty"
        )

    configs = (
        market_blend_candidate_grid(
            weights
        )
    )

    candidates = tuple(
        _candidate_metrics(
            config,
            ordered,
        )
        for config in configs
    )

    baseline = _baseline(
        candidates
    )

    for candidate in candidates:
        if (
            candidate.goal_observations
            != baseline.goal_observations
            or candidate.assist_observations
            != baseline.assist_observations
        ):
            raise MarketValidationError(
                "candidate coverage mismatch"
            )

    (
        goal_weight,
        goal_promoted,
    ) = _goal_champion(
        candidates,
        minimum_observations=(
            minimum_observations
        ),
        minimum_relative_improvement=(
            minimum_relative_improvement
        ),
    )

    (
        assist_weight,
        assist_promoted,
    ) = _assist_champion(
        candidates,
        minimum_observations=(
            minimum_observations
        ),
        minimum_relative_improvement=(
            minimum_relative_improvement
        ),
    )

    warnings = []

    if (
        baseline.goal_observations
        < minimum_observations
    ):
        warnings.append(
            "insufficient goal market observations"
        )

    if (
        baseline.assist_observations
        < minimum_observations
    ):
        warnings.append(
            "insufficient assist market observations"
        )

    return MarketBlendWalkForwardReport(
        version=MARKET_VALIDATION_VERSION,
        candidates=candidates,
        goal_champion_market_weight=(
            goal_weight
        ),
        assist_champion_market_weight=(
            assist_weight
        ),
        goal_promoted=(
            goal_promoted
        ),
        assist_promoted=(
            assist_promoted
        ),
        goal_market_observations=(
            baseline.goal_observations
        ),
        assist_market_observations=(
            baseline.assist_observations
        ),
        prediction_order=tuple(
            (
                item.model.fixture_id,
                item.model.player_id,
            )
            for item in ordered
        ),
        warnings=tuple(
            warnings
        ),
    )
