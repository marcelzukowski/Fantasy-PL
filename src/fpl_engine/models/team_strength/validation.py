"""Deterministic expanding-window comparison for Team Strength V1 candidates."""
from dataclasses import dataclass
import math
from scipy.stats import poisson
from .baselines import league_average,rolling_goals,rolling_xg
from .model import MatchObservation,TeamRegimeContext,TeamStrengthConfig,TeamStrengthModel
@dataclass(frozen=True)
class CandidateMetrics:
    model_id:str;fixtures:int;mae_goals:float;poisson_deviance:float;negative_log_likelihood:float;brier_clean_sheet:float
@dataclass(frozen=True)
class WalkForwardReport:
    candidates:tuple[CandidateMetrics,...];champion_model_id:str
@dataclass(frozen=True)
class RegimeWalkForwardReport:
    existing_champion:CandidateMetrics;challenger:CandidateMetrics;champion_model_id:str;promoted:bool
def walk_forward(matches:list[MatchObservation],*,minimum_history:int=4,config:TeamStrengthConfig=TeamStrengthConfig())->WalkForwardReport:
    ordered=sorted(matches,key=lambda m:(m.kickoff,m.fixture_id));scores={name:[] for name in ("league_average_v1","rolling_goals_v1","rolling_xg_v1",f"dixon_coles_v1_hl{config.half_life_days}_{config.signal}")}
    for i,target in enumerate(ordered):
        history=ordered[:i]
        if len(history)<minimum_history:continue
        predictions=[league_average(history,target.kickoff),rolling_goals(history,target.home_team_id,target.away_team_id,target.kickoff),rolling_xg(history,target.home_team_id,target.away_team_id,target.kickoff)]
        dc=TeamStrengthModel(config).predict(history,target.home_team_id,target.away_team_id,target.kickoff,target_fixture_id=target.fixture_id)
        predictions.append(type(predictions[0])(dc.expected_home_goals,dc.expected_away_goals,dc.model_id))
        for p in predictions:scores[p.model_id].append(_metrics(target,p.expected_home_goals,p.expected_away_goals))
    result=[]
    for name,rows in scores.items():
        if not rows:continue
        result.append(CandidateMetrics(name,len(rows),*(sum(row[i] for row in rows)/len(rows) for i in range(4))))
    # NLL is primary. A challenger needs >1% improvement; ties retain simpler ordering.
    best=result[0]
    for candidate in result[1:]:
        if candidate.negative_log_likelihood < best.negative_log_likelihood*.99:best=candidate
    return WalkForwardReport(tuple(result),best.model_id)
def walk_forward_regime(matches:list[MatchObservation],regimes:dict[str,tuple[TeamRegimeContext,...]],*,minimum_history:int=4,config:TeamStrengthConfig=TeamStrengthConfig())->RegimeWalkForwardReport:
    ordered=sorted(matches,key=lambda m:(m.kickoff,m.fixture_id));baseline=[];challenger=[]
    for i,target in enumerate(ordered):
        history=ordered[:i]
        if len(history)<minimum_history:continue
        base=rolling_xg(history,target.home_team_id,target.away_team_id,target.kickoff)
        active={}
        for team in (target.home_team_id,target.away_team_id):
            eligible=[context for context in regimes.get(team,()) if context.known_at<=target.kickoff and context.effective_from<=target.kickoff]
            if eligible:active[team]=max(eligible,key=lambda context:(context.effective_from,context.known_at))
        result=TeamStrengthModel(config).predict(history,target.home_team_id,target.away_team_id,target.kickoff,target_fixture_id=target.fixture_id,regime_context=active or None)
        baseline.append(_metrics(target,base.expected_home_goals,base.expected_away_goals));challenger.append(_metrics(target,result.expected_home_goals,result.expected_away_goals))
    if not baseline:raise ValueError("not enough observations for regime walk-forward validation")
    aggregate=lambda name,rows:CandidateMetrics(name,len(rows),*(sum(row[i] for row in rows)/len(rows) for i in range(4)))
    incumbent=aggregate("rolling_xg_v1",baseline);candidate=aggregate("dixon_coles_regime_v1",challenger)
    promoted=candidate.negative_log_likelihood<incumbent.negative_log_likelihood*.99 and candidate.mae_goals<=incumbent.mae_goals and candidate.brier_clean_sheet<=incumbent.brier_clean_sheet
    return RegimeWalkForwardReport(incumbent,candidate,candidate.model_id if promoted else incumbent.model_id,promoted)
def _metrics(m,lh,la):
    eps=1e-12;mae=(abs(m.home_goals-lh)+abs(m.away_goals-la))/2
    dev=sum(2*(y*math.log(y/max(x,eps))-(y-x)) if y else 2*x for y,x in ((m.home_goals,lh),(m.away_goals,la)))/2
    nll=-(poisson.logpmf(int(m.home_goals),lh)+poisson.logpmf(int(m.away_goals),la));ph=math.exp(-la);pa=math.exp(-lh);brier=((ph-(m.away_goals==0))**2+(pa-(m.home_goals==0))**2)/2
    return mae,dev,nll,brier
