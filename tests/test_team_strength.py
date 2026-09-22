from datetime import datetime,timedelta,timezone
import math,pytest
from fpl_engine.models.team_strength.model import *
from fpl_engine.models.team_strength.baselines import *
from fpl_engine.models.team_strength.validation import walk_forward
from fpl_engine.validation.leakage import FutureInformationError,TargetFixtureLeakageError
N=datetime(2025,1,1,tzinfo=timezone.utc)
def match(i,h,a,hg,ag,days,xg=None):return MatchObservation(str(i),N+timedelta(days=days),N+timedelta(days=days,hours=3),h,a,hg,ag,xg if xg is not None else hg+.1,ag+.1,"2024")
def history():
 return [match(1,"A","B",3,0,0),match(2,"C","A",0,2,7),match(3,"B","C",1,1,14),match(4,"A","C",4,1,21),match(5,"B","A",0,2,28),match(6,"C","B",1,1,35)]
def test_direction_home_away_distribution_and_determinism():
 m=TeamStrengthModel();a=m.predict(history(),"A","B",N+timedelta(days=50));b=m.predict(history(),"A","B",N+timedelta(days=50))
 assert a==b and a.home.attack_strength>b.away.attack_strength and a.expected_home_goals>a.expected_away_goals
 assert a.away.defence_strength<a.home.defence_strength
 assert a.expected_home_goals>=0 and a.expected_away_goals>=0
 assert sum(map(sum,a.score_distribution))==pytest.approx(1);assert 0<=a.home_clean_sheet_probability<=1 and 0<=a.away_clean_sheet_probability<=1
def test_sparse_promoted_prior_and_previous_season_prior_decline():
 cfg=TeamStrengthConfig(signal="goals",prior_matches=2,promoted_prior_matches=20)
 promoted=TeamStrengthModel(cfg).predict([match(1,"P","A",5,0,0)],"P","A",N+timedelta(days=2),promoted_teams={"P"})
 ordinary=TeamStrengthModel(cfg).predict([match(1,"P","A",5,0,0)],"P","A",N+timedelta(days=2))
 assert abs(promoted.home.attack_strength-1)<abs(ordinary.home.attack_strength-1)
 prior=TeamStrengthModel(cfg).predict([match(1,"P","A",1,1,0)],"P","A",N+timedelta(days=2),previous_season={"P":(2,.8)})
 assert prior.home.attack_strength>1
def test_recency_weight_and_point_in_time_guards():
 old=match(1,"A","B",5,0,0);recent=match(2,"A","B",0,2,119);t=N+timedelta(days=120)
 short=TeamStrengthModel(TeamStrengthConfig(half_life_days=30,signal="goals")).predict([old,recent],"A","B",t)
 long=TeamStrengthModel(TeamStrengthConfig(half_life_days=120,signal="goals")).predict([old,recent],"A","B",t)
 assert short.expected_home_goals<long.expected_home_goals
 with pytest.raises(FutureInformationError):TeamStrengthModel().predict(history()+[match(9,"A","B",9,0,60)],"A","B",N+timedelta(days=50))
 with pytest.raises(TargetFixtureLeakageError):TeamStrengthModel().predict(history(),"A","B",N+timedelta(days=50),target_fixture_id="1")
def test_baselines_and_walk_forward_ordering_are_deterministic():
 rows=history()+[match(7,"A","B",2,0,42),match(8,"B","C",1,1,49)]
 assert league_average(rows,N+timedelta(days=40)).model_id=="league_average_v1"
 assert rolling_xg(rows,"A","B",N+timedelta(days=40)).model_id=="rolling_xg_v1"
 report=walk_forward(rows,minimum_history=3);assert report==walk_forward(rows,minimum_history=3)
 assert [x.model_id for x in report.candidates][:3]==["league_average_v1","rolling_goals_v1","rolling_xg_v1"] and report.champion_model_id in {x.model_id for x in report.candidates}
