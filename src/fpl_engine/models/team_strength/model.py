"""MODEL-002/003 interpretable opponent-adjusted Poisson/Dixon-Coles model."""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import math
from types import MappingProxyType
from typing import Mapping
from scipy.stats import poisson
from fpl_engine.validation.leakage import assert_information_known,FutureInformationError,TargetFixtureLeakageError

HALF_LIFE_CANDIDATES=(30,45,60,90,120)
@dataclass(frozen=True)
class MatchObservation:
    fixture_id:str;kickoff:datetime;known_at:datetime;home_team_id:str;away_team_id:str;home_goals:float;away_goals:float;home_xg:float|None=None;away_xg:float|None=None;season:str|None=None
@dataclass(frozen=True)
class TeamStrengthConfig:
    half_life_days:int=60;prior_matches:float=5.0;promoted_prior_matches:float=10.0;dixon_coles_rho:float=-0.08;max_goals:int=10;signal:str="xg";pre_regime_weight:float=.7;max_congestion_adjustment:float=.05
    def __post_init__(self):
        if self.half_life_days not in HALF_LIFE_CANDIDATES:raise ValueError("half_life_days must be one of 30,45,60,90,120")
        if self.prior_matches<0 or self.promoted_prior_matches<0 or not -.2<=self.dixon_coles_rho<=.2 or self.max_goals<5 or self.signal not in {"goals","xg"} or not 0<self.pre_regime_weight<=1 or not 0<=self.max_congestion_adjustment<=.25:raise ValueError("invalid Team Strength configuration")
@dataclass(frozen=True)
class TeamRegimeContext:
    manager_id:str;effective_from:datetime;known_at:datetime;fixture_congestion:float|None=None;confidence:float=1.0
    def __post_init__(self):
        if self.effective_from.tzinfo is None or self.known_at.tzinfo is None:raise ValueError("regime timestamps must be aware")
        if self.fixture_congestion is not None and not 0<=self.fixture_congestion<=1:raise ValueError("fixture_congestion must be in [0,1]")
        if not 0<=self.confidence<=1:raise ValueError("confidence must be in [0,1]")
@dataclass(frozen=True)
class TeamEstimate:
    attack_strength:float;defence_strength:float;sample_size:int;effective_sample_size:float;reliability:float
@dataclass(frozen=True)
class TeamStrengthResult:
    home_team_id:str;away_team_id:str;expected_home_goals:float;expected_away_goals:float;home:TeamEstimate;away:TeamEstimate;score_distribution:tuple[tuple[float,...],...];home_clean_sheet_probability:float;away_clean_sheet_probability:float;prediction_timestamp:datetime;model_id:str
class TeamStrengthModel:
    def __init__(self,config:TeamStrengthConfig=TeamStrengthConfig()):self.config=config
    def predict(self,matches:list[MatchObservation],home_team_id:str,away_team_id:str,prediction_timestamp:datetime,*,target_fixture_id:str|None=None,previous_season:Mapping[str,tuple[float,float]]|None=None,promoted_teams=frozenset(),regime_context:Mapping[str,TeamRegimeContext]|None=None)->TeamStrengthResult:
        if prediction_timestamp.tzinfo is None:raise ValueError("prediction_timestamp must be aware")
        t=prediction_timestamp.astimezone(timezone.utc); history=[]
        for m in matches:
            assert_information_known(known_at=m.known_at,prediction_timestamp=t,entity=m.fixture_id,source="team_match")
            if target_fixture_id is not None and m.fixture_id==target_fixture_id:raise TargetFixtureLeakageError(f"target fixture {target_fixture_id} entered Team Strength training")
            if m.kickoff<t:history.append(m)
        teams={home_team_id,away_team_id}|{x for m in history for x in (m.home_team_id,m.away_team_id)}
        for team,context in (regime_context or {}).items():
            assert_information_known(known_at=context.known_at,prediction_timestamp=t,entity=team,source="manager_regime")
            if context.effective_from.astimezone(timezone.utc)>t:raise FutureInformationError("manager regime cannot start after prediction_timestamp")
        weights=[]
        for m in history:
            weight=.5**((t-m.kickoff.astimezone(timezone.utc)).total_seconds()/86400/self.config.half_life_days)
            multipliers=[]
            for team in (m.home_team_id,m.away_team_id):
                context=(regime_context or {}).get(team)
                if context and m.kickoff.astimezone(timezone.utc)<context.effective_from.astimezone(timezone.utc):
                    multipliers.append(1-(1-self.config.pre_regime_weight)*context.confidence)
            weights.append(weight*(min(multipliers) if multipliers else 1.0))
        hs=[self._signal(m,True) for m in history];aw=[self._signal(m,False) for m in history]
        total_weight=sum(weights); league_prior=self.config.prior_matches
        lh=(1.5*league_prior+sum(w*x for w,x in zip(weights,hs)))/(league_prior+total_weight) if league_prior+total_weight else 1.5
        la=(1.2*league_prior+sum(w*x for w,x in zip(weights,aw)))/(league_prior+total_weight) if league_prior+total_weight else 1.2
        attack={};defence={};counts={}
        for team in teams:
            scored=[];conceded=[]
            for m,w,h,a in zip(history,weights,hs,aw):
                if m.home_team_id==team:scored.append((h,w,lh));conceded.append((a,w,la))
                elif m.away_team_id==team:scored.append((a,w,la));conceded.append((h,w,lh))
            counts[team]=len(scored); prior=self.config.promoted_prior_matches if team in promoted_teams else self.config.prior_matches
            pa,pd=(previous_season or {}).get(team,(1.,1.)); sw=sum(w for _,w,_ in scored)
            attack[team]=(prior*pa+sum(w*x/max(base,1e-6) for x,w,base in scored))/(prior+sw) if prior+sw else 1.
            conceded_ratio=(prior/max(pd,1e-9)+sum(w*x/max(base,1e-6) for x,w,base in conceded))/(prior+sw) if prior+sw else 1.
            defence[team]=1/max(conceded_ratio,1e-6)
        # Two deterministic iterations remove first-order opponent bias.
        for _ in range(2):
            for team in sorted(teams):
                rows=[]
                for m,w,h,a in zip(history,weights,hs,aw):
                    if m.home_team_id==team:rows.append((h/max(lh,1e-6)*defence[m.away_team_id],w))
                    elif m.away_team_id==team:rows.append((a/max(la,1e-6)*defence[m.home_team_id],w))
                prior=self.config.promoted_prior_matches if team in promoted_teams else self.config.prior_matches;pa=(previous_season or {}).get(team,(1.,1.))[0];attack[team]=(prior*pa+sum(v*w for v,w in rows))/(prior+sum(w for _,w in rows)) if rows or prior else 1.
        lam=max(0.,lh*attack[home_team_id]/defence[away_team_id]);mu=max(0.,la*attack[away_team_id]/defence[home_team_id])
        for team,is_home in ((home_team_id,True),(away_team_id,False)):
            context=(regime_context or {}).get(team)
            if context and context.fixture_congestion is not None:
                factor=1-self.config.max_congestion_adjustment*context.fixture_congestion*context.confidence
                if is_home:lam*=factor
                else:mu*=factor
        dist=self._distribution(lam,mu)
        est=lambda x:TeamEstimate(attack[x],defence[x],counts[x],sum(w for m,w in zip(history,weights) if x in (m.home_team_id,m.away_team_id)),min(1.,counts[x]/10))
        model_id=("dixon_coles_regime_v1" if regime_context else "dixon_coles_v1")+f"_hl{self.config.half_life_days}_{self.config.signal}"
        return TeamStrengthResult(home_team_id,away_team_id,lam,mu,est(home_team_id),est(away_team_id),dist,sum(dist[0]),sum(row[0] for row in dist),t,model_id)
    def _signal(self,m,home):
        x=m.home_xg if home else m.away_xg
        return float(x if self.config.signal=="xg" and x is not None else (m.home_goals if home else m.away_goals))
    def _distribution(self,lam,mu):
        n=self.config.max_goals;matrix=[];rho=self.config.dixon_coles_rho
        for i in range(n+1):
            row=[]
            for j in range(n+1):
                tau=1-lam*mu*rho if (i,j)==(0,0) else 1+lam*rho if (i,j)==(0,1) else 1+mu*rho if (i,j)==(1,0) else 1-rho if (i,j)==(1,1) else 1
                row.append(max(0.,poisson.pmf(i,lam)*poisson.pmf(j,mu)*tau))
            matrix.append(row)
        total=sum(map(sum,matrix));return tuple(tuple(x/total for x in row) for row in matrix)
