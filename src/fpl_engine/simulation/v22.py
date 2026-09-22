"""CAPTAIN-068G lineup-coherent fixture simulator challenger.

This module deliberately leaves frozen FixtureSimulator V1 unchanged.

The challenger:
- reconciles unconditional marginal p_start to exactly
  1 goalkeeper + 10 outfield starters via the historically
  validated logit-shift transformation;
- samples a fixed-size lineup with dependent rounding, preserving
  those reconciled marginal inclusion probabilities;
- enforces starter => appearance;
- minimally raises p_appearance only when required by that logical
  constraint;
- reconstructs starter/bench minute distributions so their mixture
  matches the calibrated full minute PMF.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

from fpl_engine.models.events import TeamEventProjection
from fpl_engine.simulation.fixture import (
    FixtureSimulator,
    PitchState,
    on_pitch_interval,
)


_EPS = 1e-12
_PROB_TOL = 1e-10


@dataclass(frozen=True)
class CoherentPlayerMinutePlan:
    player_id: str

    raw_p_start: float
    raw_p_appearance: float

    p_start: float
    p_appearance: float

    starter_minutes_distribution: tuple[float, ...]
    bench_minutes_distribution: tuple[float, ...]

    adjusted_minute_distribution: tuple[float, ...]

    raw_expected_minutes: float
    adjusted_expected_minutes: float


def _clip_probability(
    value: float,
) -> float:

    return min(
        1.0,
        max(
            0.0,
            float(value),
        ),
    )


def _positive_shape(
    values: Sequence[float],
) -> np.ndarray | None:

    array = np.asarray(
        values,
        dtype=float,
    )

    if array.shape != (91,):
        raise ValueError(
            "minute distributions must "
            "contain minutes 0..90"
        )

    positive = np.maximum(
        array[1:],
        0.0,
    )

    total = float(
        positive.sum()
    )

    if total <= _EPS:
        return None

    return (
        positive
        / total
    )


def _fallback_positive_shape(
    *,
    full,
    starter,
    bench,
) -> np.ndarray:

    for values in (
        full,
        starter,
        bench,
    ):

        shape = _positive_shape(
            values
        )

        if shape is not None:
            return shape

    raise ValueError(
        "positive-minute distribution "
        "is unavailable"
    )


def _sigmoid(
    value: np.ndarray | float,
):

    value = np.clip(
        value,
        -60.0,
        60.0,
    )

    return (
        1.0
        / (
            1.0
            + np.exp(
                -value
            )
        )
    )


def _logit_shift_probabilities(
    probabilities: Sequence[float],
    *,
    target: int,
) -> np.ndarray:
    """Reconcile unconditional marginals to an exact integer sum."""

    raw = np.asarray(
        probabilities,
        dtype=float,
    )

    if raw.ndim != 1:
        raise ValueError(
            "probabilities must be one-dimensional"
        )

    if target < 0 or target > len(raw):
        raise ValueError(
            "invalid fixed-size target"
        )

    if target == 0:
        return np.zeros_like(
            raw
        )

    if target == len(raw):
        return np.ones_like(
            raw
        )

    clipped = np.clip(
        raw,
        _EPS,
        1.0 - _EPS,
    )

    logits = np.log(
        clipped
        / (
            1.0
            - clipped
        )
    )

    lo = -60.0
    hi = 60.0

    for _ in range(120):

        mid = (
            lo + hi
        ) / 2.0

        total = float(
            _sigmoid(
                logits + mid
            ).sum()
        )

        if total < target:
            lo = mid
        else:
            hi = mid

    output = np.asarray(
        _sigmoid(
            logits
            + (
                lo + hi
            )
            / 2.0
        ),
        dtype=float,
    )

    if not math.isclose(
        float(
            output.sum()
        ),
        float(target),
        abs_tol=1e-9,
        rel_tol=0.0,
    ):
        raise RuntimeError(
            "logit reconciliation did not "
            "reach fixed-size target"
        )

    return output


def _dependent_round(
    probabilities: Sequence[float],
    *,
    target: int,
    rng: np.random.Generator,
) -> tuple[int, ...]:
    """Fixed-size dependent rounding preserving inclusion marginals."""

    values = np.asarray(
        probabilities,
        dtype=float,
    ).copy()

    if values.ndim != 1:
        raise ValueError(
            "probabilities must be one-dimensional"
        )

    if np.any(
        values < -_PROB_TOL
    ) or np.any(
        values > 1.0 + _PROB_TOL
    ):
        raise ValueError(
            "invalid inclusion probability"
        )

    if not math.isclose(
        float(
            values.sum()
        ),
        float(target),
        abs_tol=1e-8,
        rel_tol=0.0,
    ):
        raise ValueError(
            "fixed-size probabilities "
            "must sum to target"
        )

    values = np.clip(
        values,
        0.0,
        1.0,
    )

    while True:

        fractional = np.flatnonzero(
            (values > _PROB_TOL)
            & (
                values
                < 1.0
                - _PROB_TOL
            )
        )

        if len(
            fractional
        ) == 0:
            break

        if len(
            fractional
        ) == 1:

            index = int(
                fractional[
                    0
                ]
            )

            values[
                index
            ] = (
                1.0
                if values[index] >= 0.5
                else 0.0
            )

            break

        i = int(
            fractional[
                0
            ]
        )

        j = int(
            fractional[
                1
            ]
        )

        alpha = min(
            1.0
            - values[i],
            values[j],
        )

        beta = min(
            values[i],
            1.0
            - values[j],
        )

        denominator = (
            alpha + beta
        )

        if denominator <= _EPS:
            raise RuntimeError(
                "dependent rounding stalled"
            )

        probability_up = (
            beta
            / denominator
        )

        if (
            rng.random()
            < probability_up
        ):

            values[i] += alpha
            values[j] -= alpha

        else:

            values[i] -= beta
            values[j] += beta

        values[
            np.abs(
                values
            )
            < _PROB_TOL
        ] = 0.0

        values[
            np.abs(
                values
                - 1.0
            )
            < _PROB_TOL
        ] = 1.0


    selected = tuple(
        int(index)
        for index in np.flatnonzero(
            values > 0.5
        )
    )

    if len(
        selected
    ) != target:
        raise RuntimeError(
            "dependent rounding produced "
            f"{len(selected)} selections; "
            f"expected {target}"
        )

    return selected


def _state_minute_distributions(
    rates,
    *,
    adjusted_p_start: float,
    adjusted_p_appearance: float,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    float,
]:
    """Build coherent starter/bench PMFs.

    The adjusted full marginal keeps the original positive-minute
    shape and changes only total positive mass when p_appearance
    itself had to be raised.
    """

    raw_full = np.asarray(
        rates.minute_distribution,
        dtype=float,
    )

    if raw_full.shape != (91,):
        raise ValueError(
            "minute_distribution must "
            "have length 91"
        )

    positive_shape = (
        _fallback_positive_shape(
            full=(
                rates
                .minute_distribution
            ),
            starter=(
                rates
                .starter_minutes_distribution
            ),
            bench=(
                rates
                .bench_minutes_distribution
            ),
        )
    )

    adjusted_full = np.zeros(
        91,
        dtype=float,
    )

    adjusted_full[0] = (
        1.0
        - adjusted_p_appearance
    )

    adjusted_full[1:] = (
        adjusted_p_appearance
        * positive_shape
    )

    if adjusted_p_appearance <= _EPS:

        neutral = np.zeros(
            91,
            dtype=float,
        )

        neutral[1] = 1.0

        return (
            tuple(
                neutral.tolist()
            ),
            tuple(
                neutral.tolist()
            ),
            tuple(
                adjusted_full.tolist()
            ),
            0.0,
        )


    target_start_share = (
        adjusted_p_start
        / adjusted_p_appearance
    )

    target_start_share = min(
        1.0,
        max(
            0.0,
            target_start_share,
        ),
    )


    starter_shape = _positive_shape(
        rates.starter_minutes_distribution
    )

    bench_shape = _positive_shape(
        rates.bench_minutes_distribution
    )

    if starter_shape is None:
        starter_shape = (
            positive_shape.copy()
        )

    if bench_shape is None:
        bench_shape = (
            positive_shape.copy()
        )


    raw_p_start = _clip_probability(
        rates.p_start
    )

    raw_p_appearance = _clip_probability(
        rates.p_appearance
    )

    raw_p_bench = max(
        0.0,
        raw_p_appearance
        - raw_p_start,
    )


    numerator = (
        raw_p_start
        * starter_shape
    )

    denominator = (
        numerator
        + raw_p_bench
        * bench_shape
    )


    if raw_p_appearance > _EPS:

        fallback_start_share = min(
            1.0,
            max(
                0.0,
                raw_p_start
                / raw_p_appearance,
            ),
        )

    else:

        fallback_start_share = (
            target_start_share
        )


    prior = np.full(
        90,
        fallback_start_share,
        dtype=float,
    )

    mask = (
        denominator
        > _EPS
    )

    prior[
        mask
    ] = (
        numerator[
            mask
        ]
        / denominator[
            mask
        ]
    )

    prior = np.clip(
        prior,
        _EPS,
        1.0 - _EPS,
    )


    if target_start_share <= _EPS:

        posterior = np.zeros(
            90,
            dtype=float,
        )

    elif (
        target_start_share
        >= 1.0 - _EPS
    ):

        posterior = np.ones(
            90,
            dtype=float,
        )

    else:

        logits = np.log(
            prior
            / (
                1.0
                - prior
            )
        )

        lo = -60.0
        hi = 60.0

        for _ in range(120):

            mid = (
                lo + hi
            ) / 2.0

            candidate = _sigmoid(
                logits + mid
            )

            weighted_share = float(
                np.dot(
                    positive_shape,
                    candidate,
                )
            )

            if (
                weighted_share
                < target_start_share
            ):
                lo = mid
            else:
                hi = mid

        posterior = np.asarray(
            _sigmoid(
                logits
                + (
                    lo + hi
                )
                / 2.0
            ),
            dtype=float,
        )


    starter = np.zeros(
        91,
        dtype=float,
    )

    bench = np.zeros(
        91,
        dtype=float,
    )


    if target_start_share > _EPS:

        starter[1:] = (
            positive_shape
            * posterior
            / target_start_share
        )

    else:

        starter[1:] = (
            starter_shape
        )


    bench_share = (
        1.0
        - target_start_share
    )

    if bench_share > _EPS:

        bench[1:] = (
            positive_shape
            * (
                1.0
                - posterior
            )
            / bench_share
        )

    else:

        bench[1:] = (
            bench_shape
        )


    starter /= float(
        starter.sum()
    )

    bench /= float(
        bench.sum()
    )


    reconstructed = (
        (
            1.0
            - adjusted_p_appearance
        )
        * np.eye(
            1,
            91,
            0,
        )[0]
        + adjusted_p_start
        * starter
        + (
            adjusted_p_appearance
            - adjusted_p_start
        )
        * bench
    )


    if float(
        np.max(
            np.abs(
                reconstructed
                - adjusted_full
            )
        )
    ) > 1e-9:

        raise RuntimeError(
            "coherent minute mixture "
            "does not reconstruct marginal PMF"
        )


    minute_axis = np.arange(
        91,
        dtype=float,
    )

    expected_minutes = float(
        np.dot(
            minute_axis,
            adjusted_full,
        )
    )


    return (
        tuple(
            starter.tolist()
        ),
        tuple(
            bench.tolist()
        ),
        tuple(
            adjusted_full.tolist()
        ),
        expected_minutes,
    )


class FixtureSimulatorV22(
    FixtureSimulator
):
    """Lineup-coherent Minutes V2.1 simulator challenger."""

    VERSION = (
        "fixture_simulator_v22_"
        "lineup_coherent_logit"
    )


    def simulate(
        self,
        *args,
        **kwargs,
    ):

        self._v22_team_plan_cache = {}

        return super().simulate(
            *args,
            **kwargs,
        )


    def _build_team_plan(
        self,
        team: TeamEventProjection,
    ) -> dict[
        str,
        CoherentPlayerMinutePlan,
    ]:

        players = tuple(
            team.players
        )

        goalkeepers = [
            player
            for player in players
            if player.rates.position
            == "GK"
        ]

        outfield = [
            player
            for player in players
            if player.rates.position
            != "GK"
        ]


        if len(
            goalkeepers
        ) < 1:

            raise ValueError(
                "V22 requires at least "
                "one goalkeeper"
            )

        if len(
            outfield
        ) < 10:

            raise ValueError(
                "V22 requires at least "
                "10 outfield players"
            )


        corrected: dict[
            str,
            float,
        ] = {}


        for group, target in (
            (
                goalkeepers,
                1,
            ),
            (
                outfield,
                10,
            ),
        ):

            reconciled = (
                _logit_shift_probabilities(
                    [
                        player.rates.p_start
                        for player
                        in group
                    ],
                    target=target,
                )
            )

            for player, probability in zip(
                group,
                reconciled,
            ):

                corrected[
                    player.rates.player_id
                ] = float(
                    probability
                )


        result = {}


        for player in players:

            rates = (
                player.rates
            )

            player_id = (
                rates.player_id
            )

            adjusted_p_start = (
                corrected[
                    player_id
                ]
            )

            adjusted_p_appearance = min(
                1.0,
                max(
                    float(
                        rates.p_appearance
                    ),
                    adjusted_p_start,
                ),
            )


            (
                starter_distribution,
                bench_distribution,
                adjusted_distribution,
                adjusted_expected_minutes,
            ) = (
                _state_minute_distributions(
                    rates,
                    adjusted_p_start=(
                        adjusted_p_start
                    ),
                    adjusted_p_appearance=(
                        adjusted_p_appearance
                    ),
                )
            )


            result[
                player_id
            ] = (
                CoherentPlayerMinutePlan(
                    player_id=player_id,

                    raw_p_start=float(
                        rates.p_start
                    ),

                    raw_p_appearance=float(
                        rates.p_appearance
                    ),

                    p_start=(
                        adjusted_p_start
                    ),

                    p_appearance=(
                        adjusted_p_appearance
                    ),

                    starter_minutes_distribution=(
                        starter_distribution
                    ),

                    bench_minutes_distribution=(
                        bench_distribution
                    ),

                    adjusted_minute_distribution=(
                        adjusted_distribution
                    ),

                    raw_expected_minutes=float(
                        rates.expected_minutes
                    ),

                    adjusted_expected_minutes=(
                        adjusted_expected_minutes
                    ),
                )
            )


        return result


    def _team_plan(
        self,
        team: TeamEventProjection,
    ):

        cache = getattr(
            self,
            "_v22_team_plan_cache",
            None,
        )

        if cache is None:

            cache = {}

            self._v22_team_plan_cache = (
                cache
            )


        key = id(
            team
        )

        plan = cache.get(
            key
        )

        if plan is None:

            plan = self._build_team_plan(
                team
            )

            cache[
                key
            ] = plan


        return plan


    @staticmethod
    def _draw_pmf(
        distribution,
        rng: np.random.Generator,
    ) -> int:

        values = np.asarray(
            distribution,
            dtype=float,
        )

        total = float(
            values.sum()
        )

        if total <= 0.0:
            raise RuntimeError(
                "empty minute PMF"
            )

        values = (
            values
            / total
        )

        return int(
            rng.choice(
                np.arange(
                    len(
                        values
                    )
                ),
                p=values,
            )
        )


    def _sample_team_minutes(
        self,
        team: TeamEventProjection,
        rng: np.random.Generator,
    ) -> dict[
        str,
        PitchState,
    ]:

        players = tuple(
            team.players
        )

        plan = self._team_plan(
            team
        )


        goalkeepers = [
            player
            for player in players
            if player.rates.position
            == "GK"
        ]

        outfield = [
            player
            for player in players
            if player.rates.position
            != "GK"
        ]


        starter_ids: set[str] = set()


        for group, target in (
            (
                goalkeepers,
                1,
            ),
            (
                outfield,
                10,
            ),
        ):

            probabilities = [
                plan[
                    player.rates.player_id
                ].p_start
                for player in group
            ]

            selected = _dependent_round(
                probabilities,
                target=target,
                rng=rng,
            )

            starter_ids.update(
                group[
                    index
                ].rates.player_id
                for index
                in selected
            )


        result = {}


        for player in players:

            player_id = (
                player.rates.player_id
            )

            player_plan = (
                plan[
                    player_id
                ]
            )

            started = (
                player_id
                in starter_ids
            )


            if started:

                appeared = True

            else:

                denominator = (
                    1.0
                    - player_plan.p_start
                )

                if denominator <= _EPS:

                    bench_appearance = 0.0

                else:

                    bench_appearance = (
                        (
                            player_plan.p_appearance
                            - player_plan.p_start
                        )
                        / denominator
                    )

                bench_appearance = min(
                    1.0,
                    max(
                        0.0,
                        bench_appearance,
                    ),
                )

                appeared = (
                    rng.random()
                    < bench_appearance
                )


            if not appeared:

                minutes = 0

            elif started:

                minutes = self._draw_pmf(
                    player_plan
                    .starter_minutes_distribution,
                    rng,
                )

            else:

                minutes = self._draw_pmf(
                    player_plan
                    .bench_minutes_distribution,
                    rng,
                )


            if (
                appeared
                and minutes <= 0
            ):

                raise RuntimeError(
                    "appearing player sampled "
                    "zero minutes"
                )


            entry, exit_minute = (
                on_pitch_interval(
                    minutes,
                    started,
                )
            )

            result[
                player_id
            ] = PitchState(
                started,
                entry,
                exit_minute,
                minutes,
            )


        if sum(
            state.started
            for state
            in result.values()
        ) != 11:

            raise RuntimeError(
                "V22 did not produce "
                "exactly 11 starters"
            )


        goalkeeper_starters = sum(
            result[
                player.rates.player_id
            ].started
            for player
            in goalkeepers
        )

        if goalkeeper_starters != 1:

            raise RuntimeError(
                "V22 did not produce "
                "exactly one starting GK"
            )


        return result
