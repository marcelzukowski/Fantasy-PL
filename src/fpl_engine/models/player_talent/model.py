"""TAL-003..006 empirical-Bayes Player Talent model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation, eligible_talent_history
from fpl_engine.features.tactical_context import TacticalContext
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.validation.leakage import LeakageError


CORE_PRIORS = {
    "GK": {"npxg": 0.00, "xa": 0.01, "shots": 0.05},
    "DEF": {"npxg": 0.08, "xa": 0.08, "shots": 0.80},
    "MID": {"npxg": 0.22, "xa": 0.18, "shots": 1.80},
    "FWD": {"npxg": 0.35, "xa": 0.12, "shots": 2.50},
}
ROLE_PRIOR_MULTIPLIERS = {
    TacticalRole.CENTRE_FORWARD: {"npxg": 1.25, "xa": 0.8, "shots": 1.2},
    TacticalRole.INSIDE_FORWARD: {"npxg": 1.15, "xa": 0.95, "shots": 1.15},
    TacticalRole.WINGER: {"npxg": 0.9, "xa": 1.15, "shots": 1.0},
    TacticalRole.ATTACKING_MIDFIELDER: {"npxg": 0.8, "xa": 1.25, "shots": 0.9},
    TacticalRole.CENTRE_BACK: {"npxg": 0.65, "xa": 0.4, "shots": 0.65},
}


@dataclass(frozen=True)
class PlayerTalentConfig:
    half_life_days: float = 150.0
    team_share_half_life_days: float = 90.0
    prior_minutes: float = 600.0
    finishing_prior_minutes: float = 1800.0
    pre_transfer_weight: float = 0.75
    pre_role_change_weight: float = 0.70
    unsupported_league_weight: float = 0.25
    translation_coefficients: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    model_version: str = "player_talent_empirical_bayes_v1"
    dataset_version: str = "player_talent_dataset_v1"
    feature_version: str = "player_talent_features_v1"

    def __post_init__(self) -> None:
        if self.half_life_days <= 0 or self.team_share_half_life_days <= 0 or self.prior_minutes <= 0:
            raise ValueError("Talent decay and priors must be positive")
        for name in ("pre_transfer_weight", "pre_role_change_weight", "unsupported_league_weight"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if any(value <= 0 for value in self.translation_coefficients.values()):
            raise ValueError("cross-league coefficients must be positive")


@dataclass(frozen=True)
class PlayerTalentPrediction:
    player_id: str
    team_id: str | None
    prediction_timestamp: datetime
    tactical_role: TacticalRole
    talent_npxg_per90: float
    talent_xa_per90: float
    talent_shots_per90: float
    talent_shots_in_box_per90: float | None
    talent_shots_on_target_per90: float | None
    talent_big_chances_created_per90: float | None
    talent_key_passes_per90: float | None
    talent_box_touches_per90: float | None
    team_npxg_share: float | None
    team_xa_share: float | None
    team_shot_share: float | None
    team_box_touch_share: float | None
    finishing_component: float | None
    creation_component: float
    set_piece_attacking_component: float | None
    defensive_contribution_rate: float | None
    sample_size: int
    effective_sample_size: float
    observed_minutes: int
    player_talent_uncertainty: float
    sample_reliability: float
    confidence: float
    cross_league_status: str
    data_quality: Mapping[str, bool]
    model_version: str
    dataset_version: str
    feature_version: str


class PlayerTalentModel:
    def __init__(self, config: PlayerTalentConfig = PlayerTalentConfig()):
        self.config = config

    def predict(
        self,
        observations: Iterable[PlayerPerformanceObservation],
        *,
        player_id: str,
        target_fixture_id: str,
        prediction_timestamp: datetime,
        current_team_id: str | None = None,
        current_competition_id: str = "Premier League",
        fpl_position: str = "MID",
        tactical_context: TacticalContext | None = None,
    ) -> PlayerTalentPrediction:
        if prediction_timestamp.tzinfo is None or prediction_timestamp.utcoffset() is None:
            raise LeakageError("prediction_timestamp must be aware")
        at = prediction_timestamp.astimezone(timezone.utc)
        if tactical_context is not None:
            if tactical_context.player_id != player_id or tactical_context.prediction_timestamp > at:
                raise LeakageError("tactical context is for another player or a future timestamp")
            current_team_id = tactical_context.team_id
            role = tactical_context.current_tactical_role
            transfer_change = tactical_context.club_change_flag
            role_change = tactical_context.role_change_flag
            context_multiplier = tactical_context.historical_weight_multiplier
        else:
            role = TacticalRole.UNKNOWN
            transfer_change = role_change = False
            context_multiplier = 1.0
        rows = eligible_talent_history(
            observations, player_id=player_id, target_fixture_id=target_fixture_id, prediction_timestamp=at
        )
        transfer_change = transfer_change or bool(current_team_id and any(row.team_id != current_team_id for row in rows))
        role_change = role_change or bool(role != TacticalRole.UNKNOWN and any(row.tactical_role != role for row in rows))
        weights, translations, cross_league_status = self._weights(
            rows, at, current_team_id, current_competition_id, role, transfer_change, role_change
        )
        weights = [weight * context_multiplier for weight in weights]
        effective_minutes = sum(row.minutes * weight for row, weight in zip(rows, weights))
        effective_sample = sum(weights)
        base_priors = CORE_PRIORS.get(fpl_position.upper(), CORE_PRIORS["MID"])
        multipliers = ROLE_PRIOR_MULTIPLIERS.get(role, {})
        priors = {name: value * multipliers.get(name, 1.0) for name, value in base_priors.items()}

        npxg = self._shrunk_rate(rows, weights, translations, "npxg", priors["npxg"], required=True)
        xa = self._shrunk_rate(rows, weights, translations, "xa", priors["xa"], required=True)
        shots = self._shrunk_rate(rows, weights, translations, "shots", priors["shots"], required=True)
        shots_box = self._shrunk_rate(rows, weights, translations, "shots_in_box", None)
        shots_target = self._shrunk_rate(rows, weights, translations, "shots_on_target", None)
        big_created = self._shrunk_rate(rows, weights, translations, "big_chances_created", None)
        key_passes = self._shrunk_rate(rows, weights, translations, "key_passes", None)
        box_touches = self._shrunk_rate(rows, weights, translations, "box_touches", None)
        set_piece = self._combined_rate(rows, weights, translations, ("set_piece_npxg", "set_piece_xa"))
        defensive = self._combined_rate(rows, weights, translations, ("tackles", "interceptions", "clearances", "blocks", "recoveries"))
        goals = self._shrunk_rate(rows, weights, translations, "goals", None, prior_minutes=self.config.finishing_prior_minutes)
        finishing = goals - npxg if goals is not None and any(row.npxg is not None for row in rows) else None
        share_weights = [weight * 0.5 ** ((at-row.kickoff.astimezone(timezone.utc)).total_seconds()/86400*(1/self.config.team_share_half_life_days-1/self.config.half_life_days)) for row,weight in zip(rows,weights)]
        shares = {
            "npxg": self._share(rows, share_weights, "npxg", "team_npxg"),
            "xa": self._share(rows, share_weights, "xa", "team_xa"),
            "shots": self._share(rows, share_weights, "shots", "team_shots"),
            "box": self._share(rows, share_weights, "box_touches", "team_box_touches"),
        }
        reliability = effective_minutes / (effective_minutes + self.config.prior_minutes)
        missing_ratio = sum(value is None for value in (shots_box, shots_target, key_passes, box_touches, defensive)) / 5
        regime_penalty = 0.10 * transfer_change + 0.10 * role_change
        league_penalty = 0.10 if cross_league_status == "unsupported_fallback" else 0.0
        uncertainty = 1.0 if not rows else min(1.0, max(0.0, 0.75 * (1 - reliability) + 0.10 * missing_ratio + regime_penalty + league_penalty))
        quality = MappingProxyType({
            "has_xg_data": any(row.npxg is not None for row in rows),
            "has_xa_data": any(row.xa is not None for row in rows),
            "has_shot_data": any(row.shots is not None for row in rows),
            "has_role_data": role != TacticalRole.UNKNOWN,
            "has_team_share_data": any(value is not None for value in shares.values()),
        })
        return PlayerTalentPrediction(
            player_id, current_team_id, at, role, npxg, xa, shots, shots_box, shots_target,
            big_created, key_passes, box_touches, shares["npxg"], shares["xa"], shares["shots"], shares["box"],
            finishing, xa, set_piece, defensive, len(rows), effective_sample, sum(row.minutes for row in rows),
            uncertainty, reliability, 1 - uncertainty, cross_league_status, quality,
            self.config.model_version, self.config.dataset_version, self.config.feature_version,
        )

    def _weights(self, rows, at, current_team, current_competition, current_role, transfer_change, role_change):
        result = [];translations=[]
        status = "same_league"
        for row in rows:
            weight = 0.5 ** ((at - row.kickoff.astimezone(timezone.utc)).total_seconds() / 86400 / self.config.half_life_days)
            if current_team and row.team_id != current_team:
                weight *= self.config.pre_transfer_weight
            if current_role != TacticalRole.UNKNOWN and row.tactical_role != current_role:
                weight *= self.config.pre_role_change_weight
            if row.competition_id != current_competition:
                key = f"{row.competition_id}->{current_competition}"
                coefficient = self.config.translation_coefficients.get(key)
                if coefficient is None:
                    weight *= self.config.unsupported_league_weight
                    translations.append(1.0)
                    status = "unsupported_fallback"
                else:
                    translations.append(coefficient)
                    if status != "unsupported_fallback":
                        status = "configured_translation"
            else:translations.append(1.0)
            result.append(weight)
        return result, translations, status

    def _shrunk_rate(self, rows, weights, translations, field, prior, *, required=False, prior_minutes=None):
        selected = [(row, weight, translation) for row, weight, translation in zip(rows, weights, translations) if getattr(row, field) is not None and row.minutes > 0]
        if not selected and prior is None:
            return None
        prior = 0.0 if prior is None else prior
        exposure = sum(row.minutes * weight for row, weight, _ in selected)
        adjusted = sum(
            getattr(row, field) * weight * translation * (row.opponent_strength or 1.0)
            for row, weight, translation in selected
        )
        prior_exposure = self.config.prior_minutes if prior_minutes is None else prior_minutes
        return (adjusted * 90 + prior * prior_exposure) / (exposure + prior_exposure)

    def _combined_rate(self, rows, weights, translations, fields):
        selected = [(row, weight, translation) for row, weight, translation in zip(rows, weights, translations) if any(getattr(row, field) is not None for field in fields) and row.minutes > 0]
        exposure = sum(row.minutes * weight for row, weight, _ in selected)
        return sum(sum((getattr(row, field) or 0.0) for field in fields) * weight * translation for row, weight, translation in selected) * 90 / exposure if exposure else None

    @staticmethod
    def _share(rows, weights, numerator, denominator):
        selected = [(row, weight) for row, weight in zip(rows, weights) if getattr(row, numerator) is not None and getattr(row, denominator) is not None and getattr(row, denominator) > 0]
        total = sum(getattr(row, denominator) * weight for row, weight in selected)
        return sum(getattr(row, numerator) * weight for row, weight in selected) / total if total else None
