"""ADV-002 Player Talent V2 challenger with reliability-aware shrinkage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.player_talent_dataset import (
    PlayerPerformanceObservation, eligible_talent_history,
)
from fpl_engine.features.tactical_context import TacticalContext
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.validation.leakage import LeakageError

from .model import CORE_PRIORS, ROLE_PRIOR_MULTIPLIERS, PlayerTalentPrediction


@dataclass(frozen=True)
class LeagueTranslationEvidence:
    coefficient: float
    cohort_size: int
    estimated_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.coefficient) or self.coefficient <= 0:
            raise ValueError("translation coefficient must be positive")
        if self.cohort_size < 1:
            raise ValueError("translation cohort_size must be positive")
        if self.estimated_at.tzinfo is None or self.estimated_at.utcoffset() is None:
            raise LeakageError("translation estimated_at must be aware")


@dataclass(frozen=True)
class PlayerTalentV2Config:
    half_life_days: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({
        "npxg": 120.0, "xa": 120.0, "shots": 90.0,
        "shots_in_box": 90.0, "shots_on_target": 90.0,
        "key_passes": 120.0, "big_chances_created": 120.0,
        "box_touches": 90.0, "goals": 180.0,
    }))
    prior_minutes: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({
        "npxg": 360.0, "xa": 180.0, "shots": 270.0,
        "shots_in_box": 270.0, "shots_on_target": 270.0,
        "key_passes": 270.0, "big_chances_created": 360.0,
        "box_touches": 270.0, "goals": 1800.0,
    }))
    pre_transfer_weight: float = 0.60
    pre_role_change_weight: float = 0.65
    unsupported_league_weight: float = 0.20
    minimum_translation_cohort: int = 30
    translation_evidence: Mapping[str, LeagueTranslationEvidence] = field(
        default_factory=lambda: MappingProxyType({})
    )
    model_version: str = "player_talent_reliability_v2"
    dataset_version: str = "player_talent_dataset_v2"
    feature_version: str = "player_talent_features_v2"

    def __post_init__(self) -> None:
        if any(value <= 0 for value in (*self.half_life_days.values(), *self.prior_minutes.values())):
            raise ValueError("half-lives and prior exposures must be positive")
        if not all(0 < value <= 1 for value in (
            self.pre_transfer_weight, self.pre_role_change_weight,
            self.unsupported_league_weight,
        )):
            raise ValueError("history weights must be in (0, 1]")
        if self.minimum_translation_cohort < 2:
            raise ValueError("minimum_translation_cohort must be at least two")


class PlayerTalentV2:
    """Interpretable challenger; missing source fields never enter as zero."""

    def __init__(self, config: PlayerTalentV2Config = PlayerTalentV2Config()):
        self.config = config

    def predict(
        self, observations: Iterable[PlayerPerformanceObservation], *,
        player_id: str, target_fixture_id: str, prediction_timestamp: datetime,
        current_team_id: str | None = None,
        current_competition_id: str = "Premier League", fpl_position: str = "MID",
        tactical_context: TacticalContext | None = None,
    ) -> PlayerTalentPrediction:
        if prediction_timestamp.tzinfo is None or prediction_timestamp.utcoffset() is None:
            raise LeakageError("prediction_timestamp must be aware")
        at = prediction_timestamp.astimezone(timezone.utc)
        role = TacticalRole.UNKNOWN
        context_weight = 1.0
        role_change = False
        transfer_change = False
        if tactical_context is not None:
            if tactical_context.player_id != player_id or tactical_context.prediction_timestamp > at:
                raise LeakageError("tactical context is for another player or a future timestamp")
            current_team_id = tactical_context.team_id
            role = tactical_context.current_tactical_role
            context_weight = tactical_context.historical_weight_multiplier
            role_change = tactical_context.role_change_flag
            transfer_change = tactical_context.club_change_flag
        rows = eligible_talent_history(
            observations, player_id=player_id, target_fixture_id=target_fixture_id,
            prediction_timestamp=at,
        )
        transfer_change = transfer_change or bool(
            current_team_id and any(row.team_id != current_team_id for row in rows)
        )
        role_change = role_change or bool(
            role != TacticalRole.UNKNOWN and any(row.tactical_role != role for row in rows)
        )
        priors = self._priors(fpl_position, role)
        cross_league_status = "same_league"
        field_rates: dict[str, float | None] = {}
        effective_exposures: dict[str, float] = {}
        translated = False
        unsupported = False
        fields = (
            "npxg", "xa", "shots", "shots_in_box", "shots_on_target",
            "key_passes", "big_chances_created", "box_touches", "goals",
        )
        for field_name in fields:
            rate, exposure, used_translation, used_unsupported = self._rate(
                rows, field_name, at, current_team_id, current_competition_id,
                role, context_weight, priors.get(field_name),
            )
            field_rates[field_name] = rate
            effective_exposures[field_name] = exposure
            translated = translated or used_translation
            unsupported = unsupported or used_unsupported
        if unsupported:
            cross_league_status = "unsupported_fallback"
        elif translated:
            cross_league_status = "evidence_backed_translation"

        npxg = field_rates["npxg"]
        xa = field_rates["xa"]
        shots = field_rates["shots"]
        # Required stable outputs use explicit position/role priors when source
        # evidence is absent. The source data-quality flags remain false.
        assert npxg is not None and xa is not None and shots is not None
        set_piece = self._strict_combined(rows, at, current_team_id, current_competition_id,
                                          role, context_weight, ("set_piece_npxg", "set_piece_xa"))
        defensive = self._strict_combined(
            rows, at, current_team_id, current_competition_id, role, context_weight,
            ("tackles", "interceptions", "clearances", "blocks", "recoveries"),
        )
        shares = {
            "npxg": self._share(rows, "npxg", "team_npxg", at),
            "xa": self._share(rows, "xa", "team_xa", at),
            "shots": self._share(rows, "shots", "team_shots", at),
            "box": self._share(rows, "box_touches", "team_box_touches", at),
        }
        goals = field_rates["goals"]
        finishing = goals - npxg if goals is not None and any(row.npxg is not None for row in rows) else None
        observed_fields = {
            name: any(getattr(row, name) is not None for row in rows) for name in fields
        }
        advanced_names = (
            "npxg", "xa", "shots", "shots_in_box", "shots_on_target",
            "key_passes", "big_chances_created", "box_touches",
        )
        coverage = sum(observed_fields[name] for name in advanced_names) / len(advanced_names)
        core_exposure = max(effective_exposures["npxg"], effective_exposures["xa"])
        reliability = core_exposure / (core_exposure + 360.0)
        regime_penalty = 0.10 * transfer_change + 0.10 * role_change
        league_penalty = 0.15 if unsupported else 0.05 if translated else 0.0
        uncertainty = min(1.0, max(
            0.0, 0.65 * (1 - reliability) + 0.25 * (1 - coverage)
            + regime_penalty + league_penalty,
        ))
        quality = MappingProxyType({
            "has_xg_data": observed_fields["npxg"],
            "has_xa_data": observed_fields["xa"],
            "has_shot_data": observed_fields["shots"],
            "has_role_data": role != TacticalRole.UNKNOWN,
            "has_team_share_data": any(value is not None for value in shares.values()),
            "has_shots_in_box_data": observed_fields["shots_in_box"],
            "has_shots_on_target_data": observed_fields["shots_on_target"],
            "has_key_pass_data": observed_fields["key_passes"],
            "has_big_chance_created_data": observed_fields["big_chances_created"],
            "has_box_touch_data": observed_fields["box_touches"],
            "translation_is_evidence_backed": translated and not unsupported,
        })
        return PlayerTalentPrediction(
            player_id, current_team_id, at, role, npxg, xa, shots,
            field_rates["shots_in_box"], field_rates["shots_on_target"],
            field_rates["big_chances_created"], field_rates["key_passes"],
            field_rates["box_touches"], shares["npxg"], shares["xa"],
            shares["shots"], shares["box"], finishing, xa, set_piece, defensive,
            len(rows), sum(weight for row in rows for weight in [self._base_weight(row, at)]),
            sum(row.minutes for row in rows), uncertainty, reliability, 1 - uncertainty,
            cross_league_status, quality, self.config.model_version,
            self.config.dataset_version, self.config.feature_version,
        )

    @staticmethod
    def _priors(position: str, role: TacticalRole) -> dict[str, float | None]:
        core = dict(CORE_PRIORS.get(position.upper(), CORE_PRIORS["MID"]))
        multipliers = ROLE_PRIOR_MULTIPLIERS.get(role, {})
        result: dict[str, float | None] = {
            "npxg": core["npxg"] * multipliers.get("npxg", 1.0),
            "xa": core["xa"] * multipliers.get("xa", 1.0),
            "shots": core["shots"] * multipliers.get("shots", 1.0),
            "shots_in_box": None, "shots_on_target": None, "key_passes": None,
            "big_chances_created": None, "box_touches": None, "goals": None,
        }
        return result

    def _base_weight(self, row: PlayerPerformanceObservation, at: datetime) -> float:
        return 0.5 ** ((at - row.kickoff.astimezone(timezone.utc)).total_seconds() / 86400 / 120.0)

    def _rate(self, rows, field_name, at, current_team, current_competition, role,
              context_weight, prior):
        selected = [row for row in rows if getattr(row, field_name) is not None and row.minutes > 0]
        if not selected:
            return prior, 0.0, False, False
        half_life = self.config.half_life_days.get(field_name, 120.0)
        weights = []
        translations = []
        used_translation = used_unsupported = False
        for row in selected:
            weight = 0.5 ** ((at - row.kickoff.astimezone(timezone.utc)).total_seconds() / 86400 / half_life)
            if current_team and row.team_id != current_team:
                weight *= self.config.pre_transfer_weight
            if role != TacticalRole.UNKNOWN and row.tactical_role != role:
                weight *= self.config.pre_role_change_weight
            coefficient = 1.0
            if row.competition_id != current_competition:
                key = f"{row.competition_id}->{current_competition}"
                evidence = self.config.translation_evidence.get(key)
                if (evidence is not None and evidence.cohort_size >= self.config.minimum_translation_cohort
                        and evidence.estimated_at.astimezone(timezone.utc) <= at):
                    coefficient = evidence.coefficient
                    used_translation = True
                else:
                    weight *= self.config.unsupported_league_weight
                    used_unsupported = True
            weights.append(weight * context_weight)
            translations.append(coefficient)
        exposure = sum(row.minutes * weight for row, weight in zip(selected, weights))
        numerator = sum(
            getattr(row, field_name) * weight * coefficient * (row.opponent_strength or 1.0)
            for row, weight, coefficient in zip(selected, weights, translations)
        ) * 90
        if prior is None:
            return numerator / exposure if exposure else None, exposure, used_translation, used_unsupported
        prior_exposure = self.config.prior_minutes.get(field_name, 360.0)
        return ((numerator + prior * prior_exposure) / (exposure + prior_exposure),
                exposure, used_translation, used_unsupported)

    def _strict_combined(self, rows, at, current_team, current_competition, role,
                         context_weight, fields):
        # A total is estimable only from rows where every component exists.
        selected = [row for row in rows if row.minutes > 0 and all(
            getattr(row, field_name) is not None for field_name in fields
        )]
        if not selected:
            return None
        weighted = []
        for row in selected:
            weight = self._base_weight(row, at) * context_weight
            if current_team and row.team_id != current_team:
                weight *= self.config.pre_transfer_weight
            if role != TacticalRole.UNKNOWN and row.tactical_role != role:
                weight *= self.config.pre_role_change_weight
            if row.competition_id != current_competition:
                weight *= self.config.unsupported_league_weight
            weighted.append(weight)
        exposure = sum(row.minutes * weight for row, weight in zip(selected, weighted))
        numerator = sum(
            sum(getattr(row, field_name) for field_name in fields) * weight
            for row, weight in zip(selected, weighted)
        )
        return numerator * 90 / exposure if exposure else None

    @staticmethod
    def _share(rows, numerator, denominator, at):
        selected = [row for row in rows if getattr(row, numerator) is not None
                    and getattr(row, denominator) is not None and getattr(row, denominator) > 0]
        weights = [0.5 ** ((at - row.kickoff.astimezone(timezone.utc)).total_seconds() / 86400 / 90.0)
                   for row in selected]
        total = sum(getattr(row, denominator) * weight for row, weight in zip(selected, weights))
        return (sum(getattr(row, numerator) * weight for row, weight in zip(selected, weights)) / total
                if total else None)

