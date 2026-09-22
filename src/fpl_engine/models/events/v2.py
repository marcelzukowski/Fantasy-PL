"""Targeted coherent assist and penalty challengers for the advanced block."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.tactical_context import SetPieceRole
from fpl_engine.models.data_quality import DataQualitySignals, assess_data_quality
from fpl_engine.validation.leakage import LeakageError, TargetFixtureLeakageError

from .model import (
    AssistEvents, BaseBpsParameters, EventModelConfig, EventModels,
    PenaltyProcess, PlayerFixtureInput, TeamEventProjection,
)


@dataclass(frozen=True)
class EventModelsV2Config:
    feature_groups: frozenset[str] = frozenset({
        "talent_xa", "key_passes", "big_chances_created", "set_pieces",
    })
    model_version: str = "coherent_assists_v2"
    feature_version: str = "assist_allocation_features_v2"
    dataset_version: str = "event_dataset_v2"

    def __post_init__(self) -> None:
        allowed = {"talent_xa", "key_passes", "big_chances_created", "set_pieces"}
        if not self.feature_groups or not self.feature_groups <= allowed:
            raise ValueError("invalid assist V2 feature groups")


@dataclass(frozen=True)
class AssistOpportunityProcess:
    expected_assist_eligible_goals: float
    probability_at_least_one_assist_eligible_goal: float
    assisted_goal_fraction: float


@dataclass(frozen=True)
class TeamPenaltyEvidence:
    team_id: str
    observed_at: datetime
    known_at: datetime
    matches: int
    penalties_awarded: int
    penalties_scored: int
    fixture_id: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.known_at.tzinfo is None:
            raise LeakageError("penalty evidence timestamps must be aware")
        if min(self.matches, self.penalties_awarded, self.penalties_scored) < 0:
            raise ValueError("penalty evidence counts cannot be negative")
        if self.penalties_scored > self.penalties_awarded or self.penalties_awarded > self.matches * 5:
            raise ValueError("incoherent penalty evidence")


@dataclass(frozen=True)
class TeamPenaltyProjection:
    award_probability: float
    conversion_probability: float
    miss_probability: float
    taker_probabilities: Mapping[str, float]
    unassigned_taker_probability: float
    confidence: float


class PenaltyModelV2:
    """Strongly shrunk team penalty rate and probabilistic taker hierarchy."""

    def __init__(self, *, award_prior: float = 0.12, award_prior_matches: float = 40.0,
                 conversion_prior: float = 0.78, conversion_prior_attempts: float = 25.0):
        self.award_prior = award_prior
        self.award_prior_matches = award_prior_matches
        self.conversion_prior = conversion_prior
        self.conversion_prior_attempts = conversion_prior_attempts

    def predict(self, players: Iterable[PlayerFixtureInput], *, team_id: str,
                fixture_id: str, prediction_timestamp: datetime,
                evidence: Iterable[TeamPenaltyEvidence] = ()) -> TeamPenaltyProjection:
        if prediction_timestamp.tzinfo is None:
            raise LeakageError("prediction_timestamp must be aware")
        at = prediction_timestamp.astimezone(timezone.utc)
        rows = []
        for row in evidence:
            if row.team_id != team_id:
                continue
            if row.fixture_id == fixture_id:
                raise TargetFixtureLeakageError("target penalty outcome entered prediction")
            if row.known_at.astimezone(timezone.utc) > at or row.observed_at.astimezone(timezone.utc) >= at:
                raise LeakageError("future penalty evidence entered prediction")
            rows.append(row)
        matches = sum(row.matches for row in rows)
        awarded = sum(row.penalties_awarded for row in rows)
        scored = sum(row.penalties_scored for row in rows)
        award = (self.award_prior * self.award_prior_matches + awarded) / (
            self.award_prior_matches + matches
        )
        conversion = (self.conversion_prior * self.conversion_prior_attempts + scored) / (
            self.conversion_prior_attempts + awarded
        )
        inputs = tuple(players)
        raw = {}
        for item in inputs:
            role = item.tactical_context.penalty_role if item.tactical_context else None
            if role is not None:
                raw[item.player_id] = item.minutes.p_appearance * role.confidence / role.rank
        if raw:
            total = sum(raw.values())
            certainty = min(1.0, max(
                item.tactical_context.penalty_role.confidence
                for item in inputs if item.tactical_context and item.tactical_context.penalty_role
            ))
            shares = {key: certainty * value / total for key, value in raw.items()}
        else:
            certainty, shares = 0.0, {}
        sample_confidence = matches / (matches + self.award_prior_matches)
        return TeamPenaltyProjection(
            award, conversion, award * (1 - conversion), MappingProxyType(shares),
            1 - certainty, math.sqrt(sample_confidence * certainty),
        )


class EventModelsV2(EventModels):
    """V1 goal process plus a coherent, feature-gated assist challenger."""

    def __init__(self, config: EventModelConfig = EventModelConfig(), *,
                 v2_config: EventModelsV2Config = EventModelsV2Config()):
        super().__init__(config)
        self.v2_config = v2_config

    def predict_team(self, players: Iterable[PlayerFixtureInput], **kwargs) -> TeamEventProjection:
        inputs = tuple(players)
        base = super().predict_team(inputs, **kwargs)
        if not inputs or "talent_xa" not in self.v2_config.feature_groups:
            return replace(base, model_version=self.v2_config.model_version)
        opportunity = self.assist_opportunity(base.allocated_player_goals)
        envelope = opportunity.expected_assist_eligible_goals
        distributions: list[tuple[float, list[float]]] = []
        xa = [player.rates.raw_expected_xa for player in base.players]
        if sum(xa) > 0:
            distributions.append((1.0, [value / sum(xa) for value in xa]))
        self._complete_feature_distribution(inputs, "key_passes", "key_passes", distributions)
        self._complete_feature_distribution(
            inputs, "big_chances_created", "big_chances_created", distributions,
        )
        if "set_pieces" in self.v2_config.feature_groups:
            raw = [self._set_piece_weight(item) for item in inputs]
            total = sum(raw)
            certainty = max((self._set_piece_certainty(item) for item in inputs), default=0.0)
            if total > 0 and certainty > 0:
                distributions.append((certainty, [value / total for value in raw]))
        if not distributions:
            return replace(base, model_version=self.v2_config.model_version)
        total_weight = sum(weight for weight, _ in distributions)
        shares = [
            sum(weight * distribution[index] for weight, distribution in distributions) / total_weight
            for index in range(len(inputs))
        ]
        expected = [envelope * share for share in shares]
        updated = []
        for item, old, value in zip(inputs, base.players, expected):
            assists = AssistEvents(
                value, 1 - math.exp(-value), self._count_distribution(value, 4),
                "assist-eligible team-goal envelope with conditional V2 player allocation",
            )
            bps_delta = self.config.bps_assist_weight * (value - old.assists.expected_assists)
            bps = replace(old.bps, expected_assists=value,
                          raw_bps_expectation=max(0.0, old.bps.raw_bps_expectation + bps_delta))
            coverage = sum((
                item.talent.data_quality.get("has_xa_data", False),
                item.talent.data_quality.get("has_key_pass_data", False),
                item.talent.data_quality.get("has_big_chance_created_data", False),
            )) / 3
            quality = assess_data_quality(DataQualitySignals(
                provider_coverage=coverage,
                event_feature_coverage=coverage,
                minutes_confidence=1 - item.minutes.minutes_uncertainty,
                talent_reliability=item.talent.sample_reliability,
                role_certainty=(item.tactical_context.role_confidence if item.tactical_context else None),
                set_piece_certainty=self._set_piece_certainty(item),
                availability_certainty=(item.tactical_context.availability.availability_confidence
                                        if item.tactical_context else None),
                bps_completeness=0.35,
                cross_league_certainty=(0.35 if item.talent.cross_league_status == "unsupported_fallback" else 1.0),
            ))
            updated.append(replace(
                old, assists=assists, bps=bps, uncertainty=quality.uncertainty,
                confidence=quality.confidence, model_version=self.v2_config.model_version,
                dataset_version=self.v2_config.dataset_version,
                feature_version=self.v2_config.feature_version,
            ))
        ranked = self._rerank(updated)
        return replace(
            base, expected_team_assists=sum(expected),
            unassigned_expected_assists=max(0.0, envelope - sum(expected)),
            players=ranked, model_version=self.v2_config.model_version,
        )

    def assist_opportunity(self, allocated_player_goals: float) -> AssistOpportunityProcess:
        """Team opportunity process, separate from conditional player allocation."""
        if not math.isfinite(allocated_player_goals) or allocated_player_goals < 0:
            raise ValueError("allocated_player_goals must be finite and non-negative")
        expected = allocated_player_goals * self.config.assisted_goal_fraction
        return AssistOpportunityProcess(
            expected, 1 - math.exp(-expected), self.config.assisted_goal_fraction,
        )

    def _complete_feature_distribution(self, inputs, flag, attribute, output):
        if flag not in self.v2_config.feature_groups:
            return
        values = [getattr(item.talent, f"talent_{attribute}_per90") for item in inputs]
        # Partial provider coverage is unknown, so the entire feature group is
        # omitted instead of assigning zero to missing players.
        if any(value is None for value in values):
            return
        exposed = [value * item.minutes.expected_minutes / 90 for value, item in zip(values, inputs)]
        total = sum(exposed)
        if total > 0:
            output.append((1.0, [value / total for value in exposed]))

    @staticmethod
    def _set_piece_weight(item: PlayerFixtureInput) -> float:
        context = item.tactical_context
        if context is None:
            return 0.0
        roles: tuple[SetPieceRole | None, ...] = (
            context.direct_free_kick_role, context.indirect_free_kick_role,
            context.corner_role_left, context.corner_role_right,
        )
        return item.minutes.p_appearance * sum(
            role.confidence / role.rank for role in roles if role is not None
        )

    @staticmethod
    def _set_piece_certainty(item: PlayerFixtureInput) -> float:
        context = item.tactical_context
        if context is None:
            return 0.0
        roles = (
            context.direct_free_kick_role, context.indirect_free_kick_role,
            context.corner_role_left, context.corner_role_right,
        )
        return max((role.confidence for role in roles if role is not None), default=0.0)

    @staticmethod
    def _rerank(players):
        maximum = max((player.bps.raw_bps_expectation for player in players), default=0.0)
        order = sorted(players, key=lambda row: (-row.bps.raw_bps_expectation, row.rates.player_id))
        ranks = {row.rates.player_id: index + 1 for index, row in enumerate(order)}
        return tuple(replace(
            player, bps=replace(
                player.bps,
                fixture_relative_score=(player.bps.raw_bps_expectation / maximum if maximum else 0.0),
                fixture_rank=ranks[player.rates.player_id],
            ),
        ) for player in players)
