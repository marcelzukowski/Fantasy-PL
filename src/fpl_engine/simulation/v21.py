"""SIM-V2.1 challenger.

Team-coherent lineup sampling without upward inflation of player start
probabilities. Missing lineup mass is represented by anonymous ghost starters.

The calibrated player minute_distribution is authoritative.  Starter/non-starter
conditional minute distributions are reconstructed so their mixture reproduces
that marginal distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np

from fpl_engine.models.events import (
    FixtureEventProjection,
    PlayerFixtureEvents,
    TeamEventProjection,
)
from fpl_engine.models.team_strength import TeamStrengthResult
from fpl_engine.simulation.fixture import (
    FixtureSimulationResult,
    FixtureSimulator,
    PitchState,
    on_pitch_interval,
)
from fpl_engine.simulation.v2 import FixtureSimulatorV2


@dataclass(frozen=True)
class LineupGroupPlan:
    target_slots: int
    real_start_probabilities: Mapping[str, float]
    selection_probabilities: Mapping[str, float]
    real_player_ids: tuple[str, ...]
    ghost_player_ids: tuple[str, ...]


@dataclass(frozen=True)
class TeamLineupPlan:
    goalkeeper: LineupGroupPlan
    outfield: LineupGroupPlan
    real_start_probabilities: Mapping[str, float]
    conditional_minutes: Mapping[
        str,
        tuple[tuple[float, ...], tuple[float, ...]],
    ]


class FixtureSimulatorV21(FixtureSimulatorV2):
    """Distribution-preserving coherent-lineup challenger."""

    VERSION = "fixture_simulator_v21_distribution_preserving_lineup"

    def __init__(self, scoring, config):
        super().__init__(scoring, config)
        self._v21_lineup_plans: (
            dict[str, TeamLineupPlan] | None
        ) = None

    def simulate(
        self,
        events: FixtureEventProjection,
        team_strength: TeamStrengthResult,
    ) -> FixtureSimulationResult:
        if self._v21_lineup_plans is not None:
            raise RuntimeError(
                "FixtureSimulatorV21 does not support re-entrant simulate()"
            )

        self._v21_lineup_plans = {
            events.home.team_id: self._build_team_plan(
                events.home
            ),
            events.away.team_id: self._build_team_plan(
                events.away
            ),
        }

        try:
            # Deliberately bypass FixtureSimulatorV2.simulate().
            # V2's upward start-probability reconciliation is not used.
            return FixtureSimulator.simulate(
                self,
                events,
                team_strength,
            )
        finally:
            self._v21_lineup_plans = None

    @staticmethod
    def _normalised_start_probability(
        player: PlayerFixtureEvents,
    ) -> tuple[float, float]:
        tolerance = 1e-12

        p_app = float(
            player.rates.p_appearance
        )
        p_start = float(
            player.rates.p_start
        )

        if (
            not math.isfinite(p_app)
            or not math.isfinite(p_start)
            or p_app < -tolerance
            or p_start < -tolerance
            or p_app > 1.0 + tolerance
            or p_start > 1.0 + tolerance
            or p_start > p_app + tolerance
        ):
            raise ValueError(
                "invalid appearance/start probability for "
                f"{player.rates.player_id}: "
                f"p_start={p_start!r}, "
                f"p_appearance={p_app!r}"
            )

        p_app = min(
            1.0,
            max(0.0, p_app),
        )

        p_start = min(
            p_app,
            min(
                1.0,
                max(0.0, p_start),
            ),
        )

        return p_app, p_start

    @classmethod
    def _build_group_plan(
        cls,
        players: Sequence[PlayerFixtureEvents],
        target_slots: int,
        ghost_prefix: str,
    ) -> LineupGroupPlan:
        if target_slots < 0:
            raise ValueError(
                "target_slots must be non-negative"
            )

        tolerance = 1e-12

        original: dict[str, float] = {}

        for player in players:
            pid = player.rates.player_id
            _, p_start = (
                cls._normalised_start_probability(
                    player
                )
            )
            original[pid] = p_start

        original_mass = sum(
            original.values()
        )

        # IMPORTANT:
        # - never increase a real player's p_start;
        # - only reconcile downward when real start mass
        #   exceeds physical lineup capacity.
        if (
            original_mass
            > target_slots + tolerance
        ):
            factor = (
                float(target_slots)
                / original_mass
                if original_mass > 0.0
                else 0.0
            )

            real = {
                pid: probability * factor
                for pid, probability
                in original.items()
            }
        else:
            real = dict(original)

        selection = dict(real)

        deficit = max(
            0.0,
            float(target_slots)
            - sum(real.values()),
        )

        ghost_ids: list[str] = []
        index = 0

        while deficit > tolerance:
            probability = min(
                1.0,
                deficit,
            )

            ghost_id = (
                f"__v21_ghost__:"
                f"{ghost_prefix}:{index}"
            )

            selection[ghost_id] = probability
            ghost_ids.append(ghost_id)

            deficit -= probability
            index += 1

        total = sum(
            selection.values()
        )

        drift = (
            float(target_slots)
            - total
        )

        if abs(drift) > 1e-10:
            raise RuntimeError(
                "unable to construct exact lineup "
                f"mass: target={target_slots}, "
                f"actual={total}"
            )

        # Remove numerical drift without changing
        # real-player marginals whenever ghosts exist.
        if abs(drift) > 0.0:
            if ghost_ids:
                key = ghost_ids[-1]
                selection[key] += drift
            elif real:
                key = max(
                    real,
                    key=real.get,
                )

                updated = (
                    real[key] + drift
                )

                if (
                    updated < -tolerance
                    or updated
                    > original[key] + tolerance
                ):
                    raise RuntimeError(
                        "numerical reconciliation "
                        "violated real-player bound"
                    )

                updated = min(
                    original[key],
                    max(0.0, updated),
                )

                real[key] = updated
                selection[key] = updated

        for pid, probability in real.items():
            if (
                probability
                > original[pid] + tolerance
            ):
                raise RuntimeError(
                    "V2.1 increased a real-player "
                    "start probability"
                )

        if abs(
            sum(selection.values())
            - target_slots
        ) > 1e-7:
            raise RuntimeError(
                "lineup selection probabilities "
                "do not sum to slot count"
            )

        return LineupGroupPlan(
            target_slots=target_slots,
            real_start_probabilities=real,
            selection_probabilities=selection,
            real_player_ids=tuple(
                original.keys()
            ),
            ghost_player_ids=tuple(
                ghost_ids
            ),
        )

    @staticmethod
    def _conditional_minute_distributions(
        player: PlayerFixtureEvents,
        reconciled_p_start: float,
    ) -> tuple[
        tuple[float, ...],
        tuple[float, ...],
    ]:
        """Split calibrated marginal D(minutes).

        Returns:
            P(minutes | start),
            P(minutes | non-start)

        Their mixture under reconciled_p_start reconstructs
        the original calibrated minute_distribution.
        """

        tolerance = 1e-12

        marginal = np.asarray(
            player.rates.minute_distribution,
            dtype=float,
        )

        if marginal.shape != (91,):
            raise ValueError(
                "minute_distribution must have "
                "exactly 91 entries"
            )

        if (
            np.any(~np.isfinite(marginal))
            or np.any(
                marginal < -tolerance
            )
        ):
            raise ValueError(
                "invalid minute_distribution"
            )

        marginal = np.clip(
            marginal,
            0.0,
            None,
        )

        total = float(
            marginal.sum()
        )

        if total <= 0.0:
            raise ValueError(
                "minute_distribution has no mass"
            )

        marginal = (
            marginal / total
        )

        p_app = (
            1.0
            - float(marginal[0])
        )

        q = float(
            reconciled_p_start
        )

        if (
            not math.isfinite(q)
            or q < -tolerance
            or q > p_app + tolerance
        ):
            raise ValueError(
                "reconciled p_start incompatible "
                "with minute marginal: "
                f"q={q}, p_appearance={p_app}"
            )

        q = min(
            p_app,
            max(0.0, q),
        )

        # Branch never sampled, but return a valid
        # probability distribution.
        if q <= tolerance:
            starter = np.zeros(
                91,
                dtype=float,
            )
            starter[1] = 1.0

            return (
                tuple(starter),
                tuple(marginal),
            )

        if (
            1.0 - q
            <= tolerance
        ):
            nonstarter = np.zeros(
                91,
                dtype=float,
            )
            nonstarter[0] = 1.0

            return (
                tuple(marginal),
                tuple(nonstarter),
            )

        positive_mass = float(
            marginal[1:].sum()
        )

        if q > positive_mass + tolerance:
            raise ValueError(
                "starter probability exceeds "
                "positive-minute probability"
            )

        # If start == appearance, every positive-minute
        # outcome is a starter outcome.
        if (
            abs(q - positive_mass)
            <= tolerance
        ):
            joint_start = np.zeros(
                91,
                dtype=float,
            )
            joint_start[1:] = (
                marginal[1:]
            )
        else:
            starter_shape = np.asarray(
                player.rates
                .starter_minutes_distribution,
                dtype=float,
            )

            bench_shape = np.asarray(
                player.rates
                .bench_minutes_distribution,
                dtype=float,
            )

            if (
                starter_shape.shape != (91,)
                or bench_shape.shape != (91,)
            ):
                raise ValueError(
                    "conditional minute distributions "
                    "must have 91 entries"
                )

            starter_shape = np.clip(
                starter_shape,
                0.0,
                None,
            )

            bench_shape = np.clip(
                bench_shape,
                0.0,
                None,
            )

            eps = 1e-12

            # Existing starter/bench models define
            # relative role likelihood by minute.
            log_odds_shape = np.log(
                (
                    starter_shape[1:]
                    + eps
                )
                /
                (
                    bench_shape[1:]
                    + eps
                )
            )

            weights = marginal[1:]

            def posterior(
                offset: float,
            ) -> np.ndarray:
                values = np.clip(
                    log_odds_shape + offset,
                    -60.0,
                    60.0,
                )

                return (
                    1.0
                    / (
                        1.0
                        + np.exp(-values)
                    )
                )

            low = -120.0
            high = 120.0

            for _ in range(120):
                middle = (
                    low + high
                ) / 2.0

                mass = float(
                    np.sum(
                        weights
                        * posterior(middle)
                    )
                )

                if mass < q:
                    low = middle
                else:
                    high = middle

            start_posterior = posterior(
                (low + high) / 2.0
            )

            joint_start = np.zeros(
                91,
                dtype=float,
            )

            joint_start[1:] = (
                weights
                * start_posterior
            )

            drift = (
                q
                - float(
                    joint_start.sum()
                )
            )

            if abs(drift) > 1e-12:
                if drift > 0.0:
                    room = (
                        marginal
                        - joint_start
                    )
                    room[0] = 0.0
                else:
                    room = (
                        joint_start.copy()
                    )

                for index in np.argsort(
                    -room
                ):
                    available = float(
                        room[index]
                    )

                    if available <= 0.0:
                        continue

                    change = min(
                        abs(drift),
                        available,
                    )

                    if drift > 0.0:
                        joint_start[index] += change
                        drift -= change
                    else:
                        joint_start[index] -= change
                        drift += change

                    if abs(drift) <= 1e-12:
                        break

            if abs(
                float(
                    joint_start.sum()
                )
                - q
            ) > 1e-9:
                raise RuntimeError(
                    "unable to match reconciled "
                    "starter marginal"
                )

        joint_nonstart = (
            marginal
            - joint_start
        )

        if np.any(
            joint_nonstart
            < -1e-10
        ):
            raise RuntimeError(
                "negative non-start minute mass"
            )

        joint_nonstart = np.clip(
            joint_nonstart,
            0.0,
            None,
        )

        starter = (
            joint_start / q
        )

        nonstarter = (
            joint_nonstart
            / (1.0 - q)
        )

        if abs(
            float(starter.sum())
            - 1.0
        ) > 1e-8:
            raise RuntimeError(
                "starter conditional distribution "
                "does not sum to one"
            )

        if abs(
            float(nonstarter.sum())
            - 1.0
        ) > 1e-8:
            raise RuntimeError(
                "non-starter conditional distribution "
                "does not sum to one"
            )

        if starter[0] > 1e-10:
            raise RuntimeError(
                "starter has zero-minute mass"
            )

        return (
            tuple(starter),
            tuple(nonstarter),
        )

    def _build_team_plan(
        self,
        team: TeamEventProjection,
    ) -> TeamLineupPlan:
        goalkeepers = tuple(
            player
            for player in team.players
            if player.rates.position == "GK"
        )

        outfield = tuple(
            player
            for player in team.players
            if player.rates.position != "GK"
        )

        goalkeeper_plan = (
            self._build_group_plan(
                goalkeepers,
                1,
                f"{team.team_id}:GK",
            )
        )

        outfield_plan = (
            self._build_group_plan(
                outfield,
                10,
                f"{team.team_id}:OUT",
            )
        )

        real_start = {
            player.rates.player_id: 0.0
            for player in team.players
        }

        real_start.update(
            goalkeeper_plan
            .real_start_probabilities
        )

        real_start.update(
            outfield_plan
            .real_start_probabilities
        )

        conditional = {
            player.rates.player_id:
                self._conditional_minute_distributions(
                    player,
                    real_start[
                        player.rates.player_id
                    ],
                )
            for player in team.players
        }

        return TeamLineupPlan(
            goalkeeper=goalkeeper_plan,
            outfield=outfield_plan,
            real_start_probabilities=real_start,
            conditional_minutes=conditional,
        )

    def _sample_team_minutes(
        self,
        team: TeamEventProjection,
        rng: np.random.Generator,
    ) -> dict[str, PitchState]:
        if self._v21_lineup_plans is None:
            raise RuntimeError(
                "V2.1 lineup plan missing"
            )

        plan = self._v21_lineup_plans[
            team.team_id
        ]

        goalkeeper_selection = (
            self._sample_fixed_size(
                plan.goalkeeper
                .selection_probabilities,
                tuple(
                    plan.goalkeeper
                    .selection_probabilities
                    .keys()
                ),
                rng,
            )
        )

        outfield_selection = (
            self._sample_fixed_size(
                plan.outfield
                .selection_probabilities,
                tuple(
                    plan.outfield
                    .selection_probabilities
                    .keys()
                ),
                rng,
            )
        )

        selected = (
            goalkeeper_selection
            | outfield_selection
        )

        if len(
            goalkeeper_selection
        ) != 1:
            raise RuntimeError(
                "V2.1 goalkeeper lineup "
                "does not contain one slot"
            )

        if len(
            outfield_selection
        ) != 10:
            raise RuntimeError(
                "V2.1 outfield lineup "
                "does not contain ten slots"
            )

        real_ids = set(
            plan.real_start_probabilities
        )

        starters = (
            selected & real_ids
        )

        result: dict[
            str,
            PitchState,
        ] = {}

        for player in team.players:
            pid = player.rates.player_id
            started = pid in starters

            (
                starter_distribution,
                nonstarter_distribution,
            ) = plan.conditional_minutes[
                pid
            ]

            distribution = (
                starter_distribution
                if started
                else nonstarter_distribution
            )

            minutes = self._sample_distribution(
                distribution,
                rng,
            )

            entry, exit_minute = (
                on_pitch_interval(
                    minutes,
                    started,
                )
            )

            result[pid] = PitchState(
                started,
                entry,
                exit_minute,
                minutes,
            )

        return result
