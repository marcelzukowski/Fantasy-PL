"""MODEL-001 league-average and rolling Team Strength baselines."""
from dataclasses import dataclass
from datetime import datetime
import math
from .model import MatchObservation

@dataclass(frozen=True)
class BaselinePrediction:
    expected_home_goals:float; expected_away_goals:float; model_id:str

def league_average(matches:list[MatchObservation], prediction_timestamp:datetime)->BaselinePrediction:
    history=[m for m in matches if m.known_at<=prediction_timestamp and m.kickoff<prediction_timestamp]
    if not history:return BaselinePrediction(1.5,1.2,"league_average_v1")
    return BaselinePrediction(sum(m.home_goals for m in history)/len(history),sum(m.away_goals for m in history)/len(history),"league_average_v1")

def rolling_goals(matches:list[MatchObservation],home_team_id:str,away_team_id:str,prediction_timestamp:datetime,window:int=5)->BaselinePrediction:
    base=league_average(matches,prediction_timestamp); history=sorted((m for m in matches if m.known_at<=prediction_timestamp and m.kickoff<prediction_timestamp),key=lambda m:m.kickoff)
    def attack(team):
        rows=[(m.home_goals if m.home_team_id==team else m.away_goals) for m in history if team in (m.home_team_id,m.away_team_id)][-window:]
        return sum(rows)/len(rows) if rows else (base.expected_home_goals+base.expected_away_goals)/2
    return BaselinePrediction(max(0,attack(home_team_id)),max(0,attack(away_team_id)),"rolling_goals_v1")

def rolling_xg(matches:list[MatchObservation],home_team_id:str,away_team_id:str,prediction_timestamp:datetime,window:int=5)->BaselinePrediction:
    eligible=[m for m in matches if m.known_at<=prediction_timestamp and m.kickoff<prediction_timestamp and m.home_xg is not None and m.away_xg is not None]
    if not eligible:return rolling_goals(matches,home_team_id,away_team_id,prediction_timestamp,window)
    projected=[MatchObservation(m.fixture_id,m.kickoff,m.known_at,m.home_team_id,m.away_team_id,float(m.home_xg),float(m.away_xg),m.home_xg,m.away_xg,m.season) for m in eligible]
    out=rolling_goals(projected,home_team_id,away_team_id,prediction_timestamp,window)
    return BaselinePrediction(out.expected_home_goals,out.expected_away_goals,"rolling_xg_v1")
