"""EVT-001..009 coherent V1 player-fixture event models."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from typing import Iterable

from scipy.stats import poisson

from fpl_engine.features.tactical_context import TacticalContext
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.models.minutes import MinutesPrediction
from fpl_engine.models.player_talent import PlayerTalentPrediction
from fpl_engine.models.team_strength import TeamStrengthResult
from fpl_engine.validation.leakage import (
    LeakageError, TargetFixtureLeakageError, assert_allowed_source_feature, assert_feature_record,
)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _optional_non_negative(value: float | None, name: str) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class EventFeatureSignal:
    name: str
    value: object
    known_at: datetime
    effective_at: datetime
    source: str
    fixture_id: str | None = None


@dataclass(frozen=True)
class PlayerFixtureInput:
    player_id: str
    team_id: str
    fixture_id: str
    prediction_timestamp: datetime
    position: str
    minutes: MinutesPrediction
    talent: PlayerTalentPrediction
    tactical_context: TacticalContext | None = None
    opponent_defence_strength: float = 1.0
    opponent_shots_on_target: float | None = None
    goalkeeper_save_rate: float | None = None
    penalty_save_rate: float | None = None
    yellow_cards_per90: float | None = None
    red_cards_per90: float | None = None
    historical_bps_per90: float | None = None
    signals: tuple[EventFeatureSignal, ...] = ()

    def __post_init__(self) -> None:
        _utc(self.prediction_timestamp, "prediction_timestamp")
        if not self.player_id or not self.team_id or not self.fixture_id:
            raise ValueError("canonical player, team and fixture IDs are required")
        if self.position.upper() not in {"GK", "DEF", "MID", "FWD"}:
            raise ValueError("position must be GK, DEF, MID or FWD")
        if not math.isfinite(self.opponent_defence_strength) or self.opponent_defence_strength <= 0:
            raise ValueError("opponent_defence_strength must be positive")
        for name in ("opponent_shots_on_target", "yellow_cards_per90", "red_cards_per90", "historical_bps_per90"):
            _optional_non_negative(getattr(self, name), name)
        for name in ("goalkeeper_save_rate", "penalty_save_rate"):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class PlayerFixtureRate:
    player_id: str
    team_id: str
    fixture_id: str
    prediction_timestamp: datetime
    position: str
    p_appearance: float
    p_start: float
    expected_minutes: float
    minute_distribution: tuple[float, ...]
    starter_minutes_distribution: tuple[float, ...]
    bench_minutes_distribution: tuple[float, ...]
    fixture_npxg_per90: float
    fixture_penalty_xg_per90: float
    fixture_xa_per90: float
    fixture_shots_per90: float
    fixture_shots_on_target_per90: float | None
    fixture_defcon_per90: float | None
    raw_expected_npxg: float
    raw_expected_xa: float
    uncertainty: float
    confidence: float


@dataclass(frozen=True)
class PenaltyProcess:
    penalty_award_probability: float
    taker_selection_probability: float
    conversion_probability: float
    miss_probability: float
    expected_penalty_goals: float


@dataclass(frozen=True)
class GoalEvents:
    expected_goals: float
    expected_open_play_goals: float
    expected_penalty_goals: float
    p_goal: float
    goal_distribution: tuple[float, ...]


@dataclass(frozen=True)
class AssistEvents:
    expected_assists: float
    p_assist: float
    assist_distribution: tuple[float, ...]
    approximation: str = "xA opportunity allocated within assisted team-goal envelope"


@dataclass(frozen=True)
class CleanSheetEvents:
    team_clean_sheet_probability: float
    player_clean_sheet_probability: float
    p_60_plus: float
    expected_goals_conceded: float


@dataclass(frozen=True)
class GoalkeeperEvents:
    expected_saves: float | None
    save_distribution: tuple[float, ...] | None
    p_3_plus_saves: float | None
    p_6_plus_saves: float | None
    p_9_plus_saves: float | None
    p_penalty_faced: float | None
    p_penalty_saved_given_faced: float | None
    expected_penalty_saves: float | None
    used_shots_fallback: bool


@dataclass(frozen=True)
class DefensiveContributionEvents:
    expected_defensive_contributions: float | None
    defcon_distribution: tuple[float, ...] | None


@dataclass(frozen=True)
class CardEvents:
    p_yellow: float
    p_red: float
    yellow_rate_source: str
    red_rate_source: str


@dataclass(frozen=True)
class BaseBpsParameters:
    expected_goals: float
    expected_assists: float
    clean_sheet_input: float
    expected_saves: float | None
    expected_defensive_contributions: float | None
    p_yellow: float
    p_red: float
    expected_minutes: float
    historical_bps_per90: float | None
    raw_bps_expectation: float
    fixture_relative_score: float
    fixture_rank: int


@dataclass(frozen=True)
class PlayerFixtureEvents:
    rates: PlayerFixtureRate
    penalty: PenaltyProcess
    goals: GoalEvents
    assists: AssistEvents
    clean_sheet: CleanSheetEvents
    goalkeeper: GoalkeeperEvents
    defensive_contributions: DefensiveContributionEvents
    cards: CardEvents
    bps: BaseBpsParameters
    uncertainty: float
    confidence: float
    model_version: str
    dataset_version: str
    feature_version: str


@dataclass(frozen=True)
class TeamEventProjection:
    fixture_id: str
    team_id: str
    prediction_timestamp: datetime
    expected_team_goals: float
    allocated_player_goals: float
    unassigned_expected_goals: float
    own_goal_expected_goals: float
    expected_team_assists: float
    unassigned_expected_assists: float
    squad_coverage: float
    players: tuple[PlayerFixtureEvents, ...]
    model_version: str = "event_models_v1"


@dataclass(frozen=True)
class FixtureEventProjection:
    fixture_id: str
    prediction_timestamp: datetime
    home: TeamEventProjection
    away: TeamEventProjection
    model_version: str = "event_models_v1"


@dataclass(frozen=True)
class EventModelConfig:
    default_squad_coverage: float = 0.85
    own_goal_share: float = 0.02
    assisted_goal_fraction: float = 0.72
    penalty_award_probability: float = 0.12
    penalty_conversion_probability: float = 0.78
    penalty_faced_probability: float = 0.12
    penalty_save_prior: float = 0.16
    shots_on_target_per_xg: float = 3.2
    save_rate_prior: float = 0.70
    max_count: int = 12
    bps_goal_weight: float = 12.0
    bps_assist_weight: float = 9.0
    bps_clean_sheet_weight: float = 4.0
    bps_save_weight: float = 0.5
    bps_defcon_weight: float = 0.2
    bps_yellow_weight: float = -3.0
    bps_red_weight: float = -9.0

    def __post_init__(self) -> None:
        for name in ("default_squad_coverage", "own_goal_share", "assisted_goal_fraction", "penalty_award_probability", "penalty_conversion_probability", "penalty_faced_probability", "penalty_save_prior", "save_rate_prior"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.shots_on_target_per_xg <= 0 or self.max_count < 3:
            raise ValueError("invalid event count configuration")
        if any(not math.isfinite(getattr(self, name)) for name in (
            "bps_goal_weight", "bps_assist_weight", "bps_clean_sheet_weight", "bps_save_weight",
            "bps_defcon_weight", "bps_yellow_weight", "bps_red_weight",
        )):
            raise ValueError("BPS baseline weights must be finite")


class EventModels:
    def __init__(self, config: EventModelConfig = EventModelConfig()):
        self.config = config

    def predict_team(
        self,
        players: Iterable[PlayerFixtureInput],
        *,
        fixture_id: str,
        team_id: str,
        prediction_timestamp: datetime,
        expected_team_goals: float,
        expected_opponent_goals: float,
        squad_coverage: float | None = None,
        team_clean_sheet_probability: float | None = None,
    ) -> TeamEventProjection:
        at = _utc(prediction_timestamp, "prediction_timestamp")
        _optional_non_negative(expected_team_goals, "expected_team_goals")
        _optional_non_negative(expected_opponent_goals, "expected_opponent_goals")
        coverage = self.config.default_squad_coverage if squad_coverage is None else squad_coverage
        if not 0 <= coverage <= 1:
            raise ValueError("squad_coverage must be in [0, 1]")
        if team_clean_sheet_probability is not None and not 0 <= team_clean_sheet_probability <= 1:
            raise ValueError("team_clean_sheet_probability must be in [0, 1]")
        inputs = tuple(players)
        if len({item.player_id for item in inputs}) != len(inputs):
            raise ValueError("duplicate player in team event projection")
        for item in inputs:
            self._validate_input(item, fixture_id, team_id, at)
        rates = [self._rate(item) for item in inputs]

        own_goals = expected_team_goals * self.config.own_goal_share
        player_envelope = expected_team_goals * coverage * (1 - self.config.own_goal_share)
        penalty_taker_weights = [self._penalty_weight(item) for item in inputs]
        penalty_weight_total = sum(penalty_taker_weights)
        team_penalty_xg = min(player_envelope, self.config.penalty_award_probability * self.config.penalty_conversion_probability)
        penalty_goals = [team_penalty_xg * weight / penalty_weight_total if penalty_weight_total else 0.0 for weight in penalty_taker_weights]
        open_envelope = max(0.0, player_envelope - sum(penalty_goals))
        goal_weights = [rate.raw_expected_npxg for rate in rates]
        goal_weight_total = sum(goal_weights)
        open_goals = [open_envelope * weight / goal_weight_total if goal_weight_total else 0.0 for weight in goal_weights]
        player_goals = [open_goal + penalty_goal for open_goal, penalty_goal in zip(open_goals, penalty_goals)]
        allocated_goals = sum(player_goals)
        unassigned_goals = max(0.0, expected_team_goals - own_goals - allocated_goals)

        assist_envelope = allocated_goals * self.config.assisted_goal_fraction
        assist_weights = [rate.raw_expected_xa for rate in rates]
        assist_weight_total = sum(assist_weights)
        player_assists = [assist_envelope * weight / assist_weight_total if assist_weight_total else 0.0 for weight in assist_weights]
        unassigned_assists = max(0.0, assist_envelope - sum(player_assists))
        team_cs = math.exp(-expected_opponent_goals) if team_clean_sheet_probability is None else team_clean_sheet_probability

        partial = []
        for item, rate, expected_goal, open_goal, penalty_goal, expected_assist, taker_weight in zip(inputs, rates, player_goals, open_goals, penalty_goals, player_assists, penalty_taker_weights):
            rate = replace(rate, fixture_penalty_xg_per90=(penalty_goal*90/item.minutes.expected_minutes if item.minutes.expected_minutes>0 else 0.0))
            taker_probability = taker_weight / penalty_weight_total if penalty_weight_total else 0.0
            penalty = PenaltyProcess(
                self.config.penalty_award_probability, taker_probability,
                self.config.penalty_conversion_probability,
                taker_probability * self.config.penalty_award_probability * (1-self.config.penalty_conversion_probability),
                penalty_goal,
            )
            goals = GoalEvents(expected_goal, open_goal, penalty_goal, 1-math.exp(-expected_goal), self._count_distribution(expected_goal, 5))
            assists = AssistEvents(expected_assist, 1-math.exp(-expected_assist), self._count_distribution(expected_assist, 4))
            clean = CleanSheetEvents(team_cs, team_cs * item.minutes.p60, item.minutes.p60, expected_opponent_goals)
            goalkeeper = self._goalkeeper(item, expected_opponent_goals)
            defensive = self._defensive(item, rate)
            cards = self._cards(item)
            uncertainty = min(1.0, max(item.minutes.minutes_uncertainty, item.talent.player_talent_uncertainty) + (0.1 if squad_coverage is None else 0))
            raw_bps = self._raw_bps(item, goals, assists, clean, goalkeeper, defensive, cards)
            partial.append((item, rate, penalty, goals, assists, clean, goalkeeper, defensive, cards, uncertainty, raw_bps))
        ranking = {player_id: rank+1 for rank, (player_id, _) in enumerate(sorted(((item.player_id, raw_bps) for item, *_, raw_bps in partial), key=lambda pair: (-pair[1], pair[0])))}
        maximum_bps = max((row[-1] for row in partial), default=0.0)
        results = []
        for item, rate, penalty, goals, assists, clean, goalkeeper, defensive, cards, uncertainty, raw_bps in partial:
            bps = BaseBpsParameters(goals.expected_goals, assists.expected_assists, clean.player_clean_sheet_probability,
                goalkeeper.expected_saves, defensive.expected_defensive_contributions, cards.p_yellow, cards.p_red,
                item.minutes.expected_minutes, item.historical_bps_per90, raw_bps, raw_bps / maximum_bps if maximum_bps > 0 else 0.0,
                ranking[item.player_id])
            results.append(PlayerFixtureEvents(rate, penalty, goals, assists, clean, goalkeeper, defensive, cards, bps,
                uncertainty, 1-uncertainty, "event_models_v1", "event_dataset_v1", "event_features_v1"))
        return TeamEventProjection(fixture_id, team_id, at, expected_team_goals, allocated_goals, unassigned_goals,
            own_goals, sum(player_assists), unassigned_assists, coverage, tuple(results))

    def predict_fixture(
        self, home_players: Iterable[PlayerFixtureInput], away_players: Iterable[PlayerFixtureInput],
        *, fixture_id: str, prediction_timestamp: datetime, team_strength: TeamStrengthResult,
        home_squad_coverage: float | None = None, away_squad_coverage: float | None = None,
    ) -> FixtureEventProjection:
        at = _utc(prediction_timestamp, "prediction_timestamp")
        if team_strength.prediction_timestamp != at:
            raise ValueError("Team Strength result does not match prediction_timestamp")
        home = self.predict_team(home_players, fixture_id=fixture_id, team_id=team_strength.home_team_id,
            prediction_timestamp=at, expected_team_goals=team_strength.expected_home_goals,
            expected_opponent_goals=team_strength.expected_away_goals, squad_coverage=home_squad_coverage,
            team_clean_sheet_probability=team_strength.home_clean_sheet_probability)
        away = self.predict_team(away_players, fixture_id=fixture_id, team_id=team_strength.away_team_id,
            prediction_timestamp=at, expected_team_goals=team_strength.expected_away_goals,
            expected_opponent_goals=team_strength.expected_home_goals, squad_coverage=away_squad_coverage,
            team_clean_sheet_probability=team_strength.away_clean_sheet_probability)
        combined = [("home", index, player) for index, player in enumerate(home.players)] + [("away", index, player) for index, player in enumerate(away.players)]
        ordered = sorted(combined, key=lambda row: (-row[2].bps.raw_bps_expectation, row[2].rates.player_id))
        ranks = {(side, index): rank+1 for rank, (side, index, _) in enumerate(ordered)}
        maximum = max((player.bps.raw_bps_expectation for _, _, player in combined), default=0.0)
        def rerank(side, team):
            players=[]
            for index, player in enumerate(team.players):
                score=player.bps.raw_bps_expectation/maximum if maximum>0 else 0.0
                players.append(replace(player,bps=replace(player.bps,fixture_relative_score=score,fixture_rank=ranks[(side,index)])))
            return replace(team,players=tuple(players))
        return FixtureEventProjection(fixture_id,at,rerank("home",home),rerank("away",away))

    def _validate_input(self, item, fixture_id, team_id, at):
        if item.fixture_id != fixture_id or item.team_id != team_id or item.prediction_timestamp.astimezone(timezone.utc) != at:
            raise ValueError("player event input does not match team fixture context")
        if item.minutes.player_id != item.player_id or item.minutes.fixture_id != fixture_id or item.minutes.prediction_timestamp != at:
            raise ValueError("Minutes contract does not match player fixture")
        if item.talent.player_id != item.player_id or item.talent.prediction_timestamp > at:
            raise LeakageError("Player Talent contract is for another player or future timestamp")
        if item.tactical_context is not None and (item.tactical_context.player_id != item.player_id or item.tactical_context.prediction_timestamp > at):
            raise LeakageError("Tactical Context contract is for another player or future timestamp")
        for signal in item.signals:
            if signal.fixture_id == fixture_id:
                raise TargetFixtureLeakageError(f"target fixture {fixture_id} event data entered pre-match model")
            assert_feature_record(known_at=signal.known_at, effective_at=signal.effective_at,
                prediction_timestamp=at, target_fixture_id=fixture_id, record_fixture_id=signal.fixture_id,
                source=signal.source, feature_name=signal.name)
            assert_allowed_source_feature(source=signal.source, field=signal.name,
                known_at=signal.known_at, prediction_timestamp=at)

    @staticmethod
    def _rate(item):
        defence_factor = 1 / item.opponent_defence_strength
        role = item.tactical_context
        goal_multiplier = role.current_role_multiplier_goal if role else 1.0
        assist_multiplier = role.current_role_multiplier_assist if role else 1.0
        defcon_multiplier = role.current_role_multiplier_defcon if role else 1.0
        exposure = item.minutes.expected_minutes / 90
        npxg = max(0.0, item.talent.talent_npxg_per90 * defence_factor * goal_multiplier)
        xa = max(0.0, item.talent.talent_xa_per90 * defence_factor * assist_multiplier)
        penalty_rate = (item.talent.set_piece_attacking_component or 0.0) if role and role.penalty_role else 0.0
        defcon = item.talent.defensive_contribution_rate
        uncertainty = min(1.0, max(item.minutes.minutes_uncertainty, item.talent.player_talent_uncertainty, role.tactical_context_uncertainty if role else 0.0))
        return PlayerFixtureRate(
            player_id=item.player_id,
            team_id=item.team_id,
            fixture_id=item.fixture_id,
            prediction_timestamp=item.prediction_timestamp,
            position=item.position.upper(),
            p_appearance=item.minutes.p_appearance,
            p_start=item.minutes.p_start,
            expected_minutes=item.minutes.expected_minutes,
            minute_distribution=item.minutes.minute_distribution,
            starter_minutes_distribution=item.minutes.starter_minutes_distribution,
            bench_minutes_distribution=item.minutes.bench_minutes_distribution,
            fixture_npxg_per90=npxg,
            fixture_penalty_xg_per90=penalty_rate,
            fixture_xa_per90=xa,
            fixture_shots_per90=item.talent.talent_shots_per90 * defence_factor,
            fixture_shots_on_target_per90=item.talent.talent_shots_on_target_per90,
            fixture_defcon_per90=defcon * defcon_multiplier if defcon is not None else None,
            raw_expected_npxg=npxg * exposure,
            raw_expected_xa=xa * exposure,
            uncertainty=uncertainty,
            confidence=1 - uncertainty,
        )

    @staticmethod
    def _penalty_weight(item):
        role = item.tactical_context.penalty_role if item.tactical_context else None
        return item.minutes.p_appearance * role.confidence / role.rank if role else 0.0

    def _goalkeeper(self, item, opponent_xg):
        if item.position.upper() != "GK":
            return GoalkeeperEvents(None, None, None, None, None, None, None, None, False)
        fallback = item.opponent_shots_on_target is None
        shots = item.opponent_shots_on_target if item.opponent_shots_on_target is not None else opponent_xg * self.config.shots_on_target_per_xg
        save_rate = item.goalkeeper_save_rate if item.goalkeeper_save_rate is not None else self.config.save_rate_prior
        full_match_saves = min(shots * save_rate, max(0.0, shots-opponent_xg))
        expected = max(0.0, full_match_saves * item.minutes.expected_minutes / 90)
        distribution = self._count_distribution(expected, self.config.max_count)
        tail = lambda threshold: sum(distribution[threshold:]) if threshold < len(distribution) else 0.0
        penalty_save_rate = item.penalty_save_rate if item.penalty_save_rate is not None else self.config.penalty_save_prior
        p_faced = self.config.penalty_faced_probability * item.minutes.p_appearance
        return GoalkeeperEvents(expected, distribution, tail(3), tail(6), tail(9), p_faced,
            penalty_save_rate, p_faced * penalty_save_rate, fallback)

    def _defensive(self, item, rate):
        if rate.fixture_defcon_per90 is None:
            return DefensiveContributionEvents(None, None)
        expected = max(0.0, rate.fixture_defcon_per90 * item.minutes.expected_minutes / 90)
        return DefensiveContributionEvents(expected, self._count_distribution(expected, max(20, self.config.max_count)))

    @staticmethod
    def _cards(item):
        priors = {"GK": (0.05, .002), "DEF": (.16, .008), "MID": (.13, .006), "FWD": (.10, .005)}
        yellow_prior, red_prior = priors[item.position.upper()]
        yellow_rate = item.yellow_cards_per90 if item.yellow_cards_per90 is not None else yellow_prior
        red_rate = item.red_cards_per90 if item.red_cards_per90 is not None else red_prior
        exposure = item.minutes.expected_minutes / 90
        return CardEvents(1-math.exp(-yellow_rate*exposure), 1-math.exp(-red_rate*exposure),
            "historical" if item.yellow_cards_per90 is not None else "position_prior",
            "historical" if item.red_cards_per90 is not None else "position_prior")

    def _raw_bps(self, item, goals, assists, clean, goalkeeper, defensive, cards):
        historical = (item.historical_bps_per90 or 0.0) * item.minutes.expected_minutes / 90
        return max(0.0, historical + self.config.bps_goal_weight*goals.expected_goals
            + self.config.bps_assist_weight*assists.expected_assists
            + self.config.bps_clean_sheet_weight*clean.player_clean_sheet_probability
            + self.config.bps_save_weight*(goalkeeper.expected_saves or 0)
            + self.config.bps_defcon_weight*(defensive.expected_defensive_contributions or 0)
            + self.config.bps_yellow_weight*cards.p_yellow + self.config.bps_red_weight*cards.p_red)

    @staticmethod
    def _count_distribution(expected, maximum):
        values = [float(poisson.pmf(count, expected)) for count in range(maximum)]
        values.append(max(0.0, 1-sum(values)))
        total = sum(values)
        return tuple(value/total for value in values)
