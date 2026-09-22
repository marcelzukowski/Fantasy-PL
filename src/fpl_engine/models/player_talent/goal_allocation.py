"""Goal-allocation proxy challenger.

Historical total xG may contain penalties, therefore this signal is not npxG.
It is intended only as a relative player goal-allocation signal.

alpha=0.55 was selected on 2023-24 -> 2024-25 and frozen before evaluation
on 2024-25 -> 2025-26.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .model import CORE_PRIORS


@dataclass(frozen=True)
class GoalAllocationProxyConfig:
    alpha: float = 0.55
    prior_minutes: float = 600.0
    model_version: str = "goal_allocation_proxy_v1"
    feature_version: str = "goal_allocation_proxy_total_xg_v1"

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.alpha)
            or not 0.0 <= self.alpha <= 1.0
        ):
            raise ValueError(
                "alpha must be finite and in [0, 1]"
            )

        if (
            not math.isfinite(self.prior_minutes)
            or self.prior_minutes <= 0.0
        ):
            raise ValueError(
                "prior_minutes must be finite and positive"
            )


@dataclass(frozen=True)
class GoalAllocationProxyPrediction:
    player_id: str
    position: str
    source_season: str | None
    source_total_xg: float | None
    source_minutes: float
    position_prior_per90: float
    frozen_total_xg_rate_per90: float
    goal_allocation_proxy_per90: float
    alpha: float
    used_historical_total_xg: bool
    source_metric: str
    intended_use: str
    model_version: str
    feature_version: str


def predict_goal_allocation_proxy(
    *,
    player_id: str,
    position: str,
    source_season: str | None,
    source_total_xg: float | None,
    source_minutes: float,
    config: GoalAllocationProxyConfig = GoalAllocationProxyConfig(),
) -> GoalAllocationProxyPrediction:

    if not player_id:
        raise ValueError("player_id is required")

    position = str(position).upper()

    prior = float(
        CORE_PRIORS.get(
            position,
            CORE_PRIORS["MID"],
        )["npxg"]
    )

    if (
        not math.isfinite(source_minutes)
        or source_minutes < 0.0
    ):
        raise ValueError(
            "source_minutes must be finite and non-negative"
        )

    if source_total_xg is not None:
        if (
            not math.isfinite(source_total_xg)
            or source_total_xg < 0.0
        ):
            raise ValueError(
                "source_total_xg must be finite and non-negative or None"
            )

    usable = (
        source_total_xg is not None
        and source_minutes > 0.0
    )

    if usable:
        frozen_rate = (
            float(source_total_xg) * 90.0
            + prior * config.prior_minutes
        ) / (
            source_minutes
            + config.prior_minutes
        )
    else:
        frozen_rate = prior

    proxy = (
        prior
        + config.alpha
        * (
            frozen_rate
            - prior
        )
    )

    return GoalAllocationProxyPrediction(
        player_id=player_id,
        position=position,
        source_season=source_season,
        source_total_xg=(
            float(source_total_xg)
            if source_total_xg is not None
            else None
        ),
        source_minutes=float(source_minutes),
        position_prior_per90=prior,
        frozen_total_xg_rate_per90=frozen_rate,
        goal_allocation_proxy_per90=proxy,
        alpha=config.alpha,
        used_historical_total_xg=usable,
        source_metric="historical_total_xg_including_penalties",
        intended_use="relative_team_goal_allocation_only",
        model_version=config.model_version,
        feature_version=config.feature_version,
    )


def fixture_goal_allocation_weight(
    *,
    goal_allocation_proxy_per90: float | None,
    legacy_raw_expected_npxg: float,
    expected_minutes: float,
    opponent_defence_strength: float = 1.0,
    goal_multiplier: float = 1.0,
) -> float:

    if goal_allocation_proxy_per90 is None:
        return float(
            legacy_raw_expected_npxg
        )

    if (
        not math.isfinite(goal_allocation_proxy_per90)
        or goal_allocation_proxy_per90 < 0.0
    ):
        raise ValueError(
            "goal_allocation_proxy_per90 must be finite and non-negative"
        )

    if (
        not math.isfinite(expected_minutes)
        or expected_minutes < 0.0
    ):
        raise ValueError(
            "expected_minutes must be finite and non-negative"
        )

    if (
        not math.isfinite(opponent_defence_strength)
        or opponent_defence_strength <= 0.0
    ):
        raise ValueError(
            "opponent_defence_strength must be finite and positive"
        )

    if (
        not math.isfinite(goal_multiplier)
        or goal_multiplier < 0.0
    ):
        raise ValueError(
            "goal_multiplier must be finite and non-negative"
        )

    fixture_proxy = (
        goal_allocation_proxy_per90
        / opponent_defence_strength
        * goal_multiplier
    )

    return (
        fixture_proxy
        * expected_minutes
        / 90.0
    )
