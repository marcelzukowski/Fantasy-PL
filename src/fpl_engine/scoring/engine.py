"""SCORE-001 season-configured FPL scoring and fixture bonus allocation."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from fpl_engine.config.loader import ScoringRulesConfig,load_scoring_rules_config,load_yaml_config
@dataclass(frozen=True)
class SimulatedPlayerEvents:
    player_id:str;fixture_id:str;position:str;minutes:int;goals:int=0;penalty_goals:int=0;assists:int=0;goals_conceded_while_on_pitch:int=0;saves:int=0;saves_inside_box:int=0;saves_big_chance:int=0;penalty_saves:int=0;penalty_misses:int=0;yellow_cards:int=0;red_cards:int=0;own_goals:int=0;defensive_contributions:int=0;clearances_blocks_interceptions:int=0;recoveries:int=0;successful_tackles:int=0;successful_open_play_crosses:int=0;chances_created:int=0;big_chances_created:int=0;successful_dribbles:int=0;shots_on_target:int=0;winning_goals:int=0;fouls_won:int=0;passes_attempted:int=0;passes_completed:int=0;goal_line_clearances:int=0;penalties_conceded:int=0;big_chances_missed:int=0;errors_leading_to_goal:int=0;errors_leading_to_attempt:int=0;fouls_conceded:int=0;offsides:int=0;shots_off_target:int=0;unavailable_bps_components:tuple[str,...]=()
    def __post_init__(self):
        if self.position.upper() not in {"GK","DEF","MID","FWD"}:raise ValueError("position must be GK, DEF, MID or FWD")
        if not 0<=self.minutes<=90:raise ValueError("minutes must be in [0, 90]")
        for name,value in self.__dict__.items():
            if name not in {"player_id","fixture_id","position","unavailable_bps_components"} and value<0:raise ValueError(f"{name} cannot be negative")
        if any(not isinstance(component,str) or not component for component in self.unavailable_bps_components):raise ValueError("unavailable_bps_components must contain non-empty names")
        if self.penalty_goals>self.goals:raise ValueError("penalty_goals cannot exceed goals")
@dataclass(frozen=True)
class FPLScoreBreakdown:
    appearance_points:int;goal_points:int;assist_points:int;clean_sheet_points:int;save_points:int;penalty_save_points:int;defensive_contribution_points:int;penalty_miss_points:int;goals_conceded_points:int;yellow_card_points:int;red_card_points:int;own_goal_points:int;bonus_points:int;total_points:int;multiplied_points:int;captain_multiplier:int;scoring_version:int;season:str
@dataclass(frozen=True)
class BpsAssessment:
    known_bps:int; event_completeness:float; unavailable_components:tuple[str,...]
class FPLScoringEngine:
    def __init__(self,rules:ScoringRulesConfig):self.rules=rules.model_dump();self.version=rules.version;self.season=rules.season
    @classmethod
    def from_project(cls,project_root:Path|None=None,*,season:str|None=None):return cls(load_scoring_rules_config(project_root,season=season))
    @classmethod
    def from_file(cls,path:Path):return cls(load_yaml_config(path,model=ScoringRulesConfig))
    def score(self,e:SimulatedPlayerEvents,*,bonus_points:int=0,captain_multiplier:int=1)->FPLScoreBreakdown:
        maximum_bonus=int(self.rules["bonus_points"]["allocation"]["standard"]["first"])
        if not isinstance(bonus_points,int) or not 0<=bonus_points<=maximum_bonus or captain_multiplier not in {1,2,3}:raise ValueError("invalid bonus or captain multiplier")
        p=self._position_name(e.position);appearance=self._appearance(e.minutes);goals=e.goals*int(self.rules["goals"][p]["points_per_goal"]);assists=e.assists*int(self.rules["assists"]["points_per_assist"])
        cs=self.rules["clean_sheets"];clean=int(cs["points"][p]) if e.minutes>=int(cs["minimum_minutes"]) and e.goals_conceded_while_on_pitch==0 else 0
        sr=self.rules["goalkeeper_saves"];saves=(e.saves//int(sr["saves_per_point"]))*int(sr["points_per_group"]) if e.position.upper()=="GK" else 0
        ps=e.penalty_saves*int(self.rules["penalty_saves"]["points_per_penalty_save"]) if e.position.upper()=="GK" else 0
        defensive=self._defensive_points(p,e.defensive_contributions);miss=e.penalty_misses*int(self.rules["penalty_misses"]["points_per_miss"]);conceded=0
        if p in self.rules["goals_conceded"]["applicable_positions"]:conceded=(e.goals_conceded_while_on_pitch//int(self.rules["goals_conceded"]["goals_per_deduction"]))*int(self.rules["goals_conceded"]["points_per_deduction"])
        yellow=e.yellow_cards*int(self.rules["cards"]["yellow"]["points"]);red=e.red_cards*int(self.rules["cards"]["red"]["points"]);own=e.own_goals*int(self.rules["own_goals"]["points_per_own_goal"])
        total=appearance+goals+assists+clean+saves+ps+defensive+miss+conceded+yellow+red+own+bonus_points
        return FPLScoreBreakdown(appearance,goals,assists,clean,saves,ps,defensive,miss,conceded,yellow,red,own,bonus_points,total,total*captain_multiplier,captain_multiplier,self.version,self.season)
    def calculate_bps(self,e:SimulatedPlayerEvents)->int:
        r=self.rules["bps"];p=self._position_name(e.position);value=0 if e.minutes==0 else int(r["appearance"]["minutes_1_to_60"]["bps"]) if e.minutes<=60 else int(r["appearance"]["over_60_minutes"]["bps"])
        value+=e.penalty_goals*int(r["goals"]["penalty_goal"]["bps"])+(e.goals-e.penalty_goals)*int(r["goals"]["non_penalty_goal"][p]["bps"])+e.assists*int(r["assists"]["bps_per_assist"])
        if e.minutes>=int(self.rules["clean_sheets"]["minimum_minutes"]) and e.goals_conceded_while_on_pitch==0:value+=int(r["clean_sheet"][p]["bps"])
        if e.position.upper()=="GK":value+=e.saves*int(r["goalkeeper"]["save"]["bps_per_action"])+e.saves_inside_box*int(r["goalkeeper"]["save_from_inside_box"]["additional_bps_per_action"])+e.saves_big_chance*int(r["goalkeeper"]["save_from_big_chance"]["additional_bps_per_action"])+e.penalty_saves*int(r["goalkeeper"]["penalty_save"]["additional_bps_per_action"])
        a=r["attacking_actions"];value+=e.successful_open_play_crosses*int(a["successful_open_play_cross"]["bps_per_action"])+e.chances_created*int(a["chance_created"]["bps_per_action"])+e.big_chances_created*int(a["big_chance_created"]["bps_per_action"])+e.successful_dribbles*int(a["successful_dribble"]["bps_per_action"])+e.shots_on_target*int(a["shot_on_target"]["bps_per_action"])+e.winning_goals*int(a["winning_goal"]["bps_per_action"])+e.fouls_won*int(a["foul_won"]["bps_per_action"])
        d=r["defensive_actions"];cbi=d["clearances_blocks_interceptions"];rec=d["recoveries"];value+=e.clearances_blocks_interceptions//int(cbi["group_size"])*int(cbi["bps_per_complete_group"])+e.recoveries//int(rec["group_size"])*int(rec["bps_per_complete_group"])+e.successful_tackles*int(d["successful_tackle"]["bps_per_action"])+e.goal_line_clearances*int(d["goal_line_clearance"]["bps_per_action"])
        passing=r["passing"]
        if e.passes_attempted>=int(passing["minimum_passes_attempted_for_completion_bonus"]):
            pct=100*e.passes_completed/e.passes_attempted;key="completion_90_plus_percent" if pct>=90 else "completion_80_to_89_percent" if pct>=80 else "completion_70_to_79_percent" if pct>=70 else None;value+=int(passing[key]["bps"]) if key else 0
        n=r["negative_actions"]
        if p in {"goalkeeper","defender"}:value+=e.goals_conceded_while_on_pitch*int(n["goalkeeper_or_defender_concedes_goal"]["bps_per_goal"])
        for key,count in (("penalty_conceded",e.penalties_conceded),("penalty_missed",e.penalty_misses),("yellow_card",e.yellow_cards),("red_card",e.red_cards),("own_goal",e.own_goals),("big_chance_missed",e.big_chances_missed),("error_leading_to_goal",e.errors_leading_to_goal),("error_leading_to_attempt",e.errors_leading_to_attempt),("foul_conceded",e.fouls_conceded),("offside",e.offsides),("shot_off_target",e.shots_off_target)):value+=count*int(n[key]["bps_per_action"])
        return value
    def assess_bps(self,e:SimulatedPlayerEvents)->BpsAssessment:
        unavailable=tuple(sorted(set(e.unavailable_bps_components)))
        # This is a known-component subtotal, not an assertion that unsupported
        # detailed events occurred zero times.
        return BpsAssessment(self.calculate_bps(e),max(0.0,1.0-len(unavailable)/20),unavailable)
    def allocate_bonus(self,bps:Mapping[str,int])->dict[str,int]:
        if not bps:return {}
        standard=self.rules["bonus_points"]["allocation"]["standard"]
        rank_points=(int(standard["first"]),int(standard["second"]),int(standard["third"]))
        groups=[sorted(player for player,value in bps.items() if value==score) for score in sorted(set(bps.values()),reverse=True)]
        result={player:0 for player in bps};rank=0
        for group in groups:
            if rank>=len(rank_points):break
            for player in group:result[player]=rank_points[rank]
            rank+=len(group)
        return result
    def _appearance(self,minutes):
        r=self.rules["appearance"]
        return int(r["did_not_play"]["points"]) if minutes==0 else int(r["played_under_60"]["points"]) if minutes<60 else int(r["played_60_or_more"]["points"])
    def _defensive_points(self,position,contributions):
        section=self.rules["defensive_contributions"];rule=section[position]
        return 0 if not section["enabled"] or not rule["eligible"] or contributions<int(rule["threshold"]) else min(int(rule["points"]),int(section["maximum_points_per_player_per_fixture"]))
    def _position_name(self,code):
        for name,value in self.rules["positions"].items():
            if value["code"]==code.upper():return name
        raise ValueError(f"unknown position {code}")
