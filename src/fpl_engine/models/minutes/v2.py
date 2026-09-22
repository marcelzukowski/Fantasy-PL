from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from fpl_engine.features.minutes_dataset import (
    MinutesObservation,
    eligible_history,
)

from .model import (
    MinutesContext,
    MinutesModel,
    MinutesModelConfig,
    MinutesPrediction,
)


DEFAULT_MINUTES_V2_MODEL_CONFIG = MinutesModelConfig(
    history_matches=20,
    match_half_life=5.0,

    # Same means as the V1 priors, but lower pseudo-count strength.
    #
    # appearance:
    #   V1 Beta(2,1)   mean = 2/3, strength = 3
    #   V2 Beta(1,.5)  mean = 2/3, strength = 1.5
    #
    # start:
    #   V1 Beta(2,2)   mean = .5, strength = 4
    #   V2 Beta(1,1)   mean = .5, strength = 2
    appearance_prior_alpha=1.0,
    appearance_prior_beta=0.5,
    start_prior_alpha=1.0,
    start_prior_beta=1.0,

    distribution_prior_weight=3.0,
    unknown_availability_prior=0.85,

    model_version="minutes_hurdle_v2",
    dataset_version="minutes_dataset_v1",
    feature_version="minutes_features_v2",
)


@dataclass(frozen=True)
class MinutesV2TimeConfig:
    """Calendar-time weighting used by the V2 appearance/start hurdle."""

    half_life_days: float = 30.0
    offseason_gap_days: float = 60.0
    offseason_carryover: float = 0.50

    def __post_init__(self) -> None:

        if self.half_life_days <= 0:
            raise ValueError(
                "half_life_days must be positive"
            )

        if self.offseason_gap_days <= 0:
            raise ValueError(
                "offseason_gap_days must be positive"
            )

        if not (
            0.0
            < self.offseason_carryover
            <= 1.0
        ):
            raise ValueError(
                "offseason_carryover must be in (0, 1]"
            )


_WeightContext = tuple[
    tuple[MinutesObservation, ...],
    datetime,
]


class HurdleTimeDecayMinutesModel(
    MinutesModel
):
    """Minutes V2.1.

    Changes only the evidence weighting used by the appearance/start
    hurdle:

    * evidence decays by actual calendar time;
    * observations before the most recent long break receive an
      additional off-season carry-over penalty;
    * weaker priors allow fresh evidence to move the hurdle faster.

    The conditional starter and substitute minute distributions remain
    V1-style: last 10 fixtures with the original match-index weighting.

    No player-specific overrides are used.
    """

    def __init__(
        self,
        config: MinutesModelConfig = (
            DEFAULT_MINUTES_V2_MODEL_CONFIG
        ),
        *,
        time_config: MinutesV2TimeConfig = (
            MinutesV2TimeConfig()
        ),
    ) -> None:

        super().__init__(
            config
        )

        self.time_config = (
            time_config
        )

        # ContextVar avoids mutable shared instance state if predictions
        # are ever executed concurrently.
        self._weight_context: ContextVar[
            _WeightContext | None
        ] = ContextVar(
            "minutes_v2_weight_context",
            default=None,
        )


    def predict(
        self,
        observations,
        context: MinutesContext,
        *,
        calibration=None,
    ) -> MinutesPrediction:

        prediction = (
            context.prediction_timestamp
        )

        rows = eligible_history(
            observations,
            player_id=context.player_id,
            target_fixture_id=(
                context.fixture_id
            ),
            prediction_timestamp=(
                prediction
            ),
        )[
            -self.config.history_matches:
        ]

        token = (
            self._weight_context.set(
                (
                    tuple(rows),
                    prediction,
                )
            )
        )

        try:

            return super().predict(
                observations,
                context,
                calibration=calibration,
            )

        finally:

            self._weight_context.reset(
                token
            )


    def _weights(
        self,
        size: int,
    ) -> list[float]:

        state = (
            self._weight_context.get()
        )

        if state is None:
            raise RuntimeError(
                "Minutes V2 time-weight "
                "context is unavailable"
            )

        rows, prediction = state

        if len(rows) != size:
            raise RuntimeError(
                "Minutes V2 history size mismatch"
            )

        return self._time_decay_weights(
            rows,
            prediction,
        )


    def _time_decay_weights(
        self,
        rows: tuple[
            MinutesObservation,
            ...
        ],
        prediction_timestamp: datetime,
    ) -> list[float]:

        if not rows:
            return []

        config = (
            self.time_config
        )

        weights: list[float] = []

        for row in rows:

            age_days = max(
                0.0,
                (
                    prediction_timestamp
                    - row.kickoff
                ).total_seconds()
                / 86400.0,
            )

            weights.append(
                0.5 ** (
                    age_days
                    / config.half_life_days
                )
            )


        # Minutes observations include zero-minute team fixtures.
        # Therefore a long gap in this sequence generally represents
        # a competition / season break rather than a normal injury
        # absence.
        #
        # Only the most recent such boundary matters.
        boundary: int | None = None

        for index, row in enumerate(
            rows
        ):

            if (
                index + 1
                < len(rows)
            ):

                next_timestamp = (
                    rows[
                        index + 1
                    ].kickoff
                )

            else:

                next_timestamp = (
                    prediction_timestamp
                )

            gap_days = (
                next_timestamp
                - row.kickoff
            ).total_seconds() / 86400.0

            if (
                gap_days
                >= config.offseason_gap_days
            ):

                boundary = (
                    index + 1
                )


        if boundary is not None:

            for index in range(
                boundary
            ):

                weights[index] *= (
                    config
                    .offseason_carryover
                )


        return weights


    def starter_minutes_distribution(
        self,
        rows,
        weights,
        context: MinutesContext,
    ) -> list[float]:

        # Deliberately preserve the V1 conditional minute model.
        v1_rows = list(
            rows[-10:]
        )

        v1_weights = (
            MinutesModel._weights(
                self,
                len(v1_rows),
            )
        )

        return (
            MinutesModel
            .starter_minutes_distribution(
                self,
                v1_rows,
                v1_weights,
                context,
            )
        )


    def bench_minutes_distribution(
        self,
        rows,
        weights,
    ) -> list[float]:

        # Deliberately preserve the V1 conditional substitute model.
        v1_rows = list(
            rows[-10:]
        )

        v1_weights = (
            MinutesModel._weights(
                self,
                len(v1_rows),
            )
        )

        return (
            MinutesModel
            .bench_minutes_distribution(
                self,
                v1_rows,
                v1_weights,
            )
        )
