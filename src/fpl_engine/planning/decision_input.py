"""Run-scoped immutable engine input shared by desktop decision policies."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from time import perf_counter
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from fpl_engine.optimizer import OptimizerError, OptimizerRules, PlayerProjection, SquadPlayer, SquadState, optimize_lineup
from .context import PlanningContext, PlanningContextError

class DecisionInputError(ValueError): pass

@dataclass
class DecisionInputDiagnostics:
    construction_seconds: float = 0.0
    projection_lookup_seconds: float = 0.0
    candidate_universe_seconds: float = 0.0
    lineup_evaluations: int = 0
    lineup_cache_hits: int = 0
    lineup_cache_misses: int = 0
    policy_seconds: dict[str, float] = field(default_factory=dict)
    def snapshot(self) -> dict[str, object]:
        return {"construction_seconds":self.construction_seconds,"projection_lookup_seconds":self.projection_lookup_seconds,"candidate_universe_seconds":self.candidate_universe_seconds,"lineup_evaluations":self.lineup_evaluations,"lineup_cache_hits":self.lineup_cache_hits,"lineup_cache_misses":self.lineup_cache_misses,"policy_seconds":dict(sorted(self.policy_seconds.items()))}

class DecisionInputCache:
    """Mutable cache owned by one immutable DecisionInput, never global or cross-process."""
    def __init__(self, context_id:str, diagnostics:DecisionInputDiagnostics) -> None:
        self.context_id=context_id; self._diagnostics=diagnostics; self._lineups:dict[tuple[object,...],object]={}
    def lineup(self, state:SquadState, projections:Mapping[str,PlayerProjection], rules:OptimizerRules, *, target_gameweek:int, triple_captain:bool=False, bench_boost:bool=False):
        key=(self.context_id,target_gameweek,tuple(sorted(row.player_id for row in state.players)),rules.version,triple_captain,bench_boost)
        cached=self._lineups.get(key)
        if cached is not None:
            self._diagnostics.lineup_cache_hits+=1; return cached
        self._diagnostics.lineup_cache_misses+=1
        value=optimize_lineup(state,projections,rules,triple_captain=triple_captain,bench_boost=bench_boost)
        self._lineups[key]=value; self._diagnostics.lineup_evaluations+=1
        return value

@dataclass(frozen=True)
class DecisionInput:
    """Canonical validated data for one PlanningContext and one analysis execution."""
    planning_context:PlanningContext
    context_id:str
    state:SquadState
    player_pool:tuple[SquadPlayer,...]
    projections:Mapping[str,PlayerProjection]
    projection_lookup:Mapping[tuple[str,int],PlayerProjection]
    player_by_id:Mapping[str,SquadPlayer]
    players_by_position:Mapping[str,tuple[str,...]]
    pipeline:Mapping[str,Any]
    freshness:object
    warnings:tuple[str,...]
    rules:OptimizerRules
    bundle_identity:str
    artifact_identities:tuple[tuple[str,str],...]
    diagnostics:DecisionInputDiagnostics
    cache:DecisionInputCache
    advisory:Mapping[str,object]=field(default_factory=lambda:MappingProxyType({}))

    @classmethod
    def create(cls, *, planning_context:PlanningContext, state:SquadState, player_pool:Sequence[SquadPlayer], projections:Mapping[str,PlayerProjection], pipeline:Mapping[str,Any], warnings:Sequence[str], rules:OptimizerRules, freshness:object, bundle_identity:str) -> "DecisionInput":
        started=perf_counter()
        if planning_context.projection_run_id != bundle_identity:
            raise DecisionInputError("PlanningContext does not match the selected projection bundle.")
        if state.season!=planning_context.season or state.current_gameweek!=planning_context.gameweek or state.bank!=planning_context.bank_tenths or state.free_transfers!=planning_context.free_transfers or tuple(sorted(row.player_id for row in state.players))!=planning_context.player_ids:
            raise DecisionInputError("Validated SquadState does not match the PlanningContext.")
        if state.rule_version!=planning_context.optimizer_rule_version:
            raise DecisionInputError("Optimizer rule version does not match the PlanningContext.")
        if state.prediction_timestamp.isoformat()!=planning_context.prediction_timestamp:
            raise DecisionInputError("Prediction timestamp does not match the PlanningContext.")
        selling=tuple(sorted((row.player_id,row.selling_price) for row in state.players))
        if selling!=planning_context.selling_prices_tenths:
            raise DecisionInputError("Owned selling prices do not match the PlanningContext.")
        diagnostics=DecisionInputDiagnostics(); lookup_started=perf_counter()
        ordered_projection=tuple(sorted(projections.items()))
        if set(row.player_id for row in player_pool)-set(projections):raise DecisionInputError("Player pool has no matching canonical projection.")
        projection_lookup={(player_id,gw.target_gameweek):projection for player_id,projection in ordered_projection for gw in projection.gameweeks}
        diagnostics.projection_lookup_seconds=perf_counter()-lookup_started
        universe_started=perf_counter(); by_id={row.player_id:row for row in player_pool}
        for row in state.players:by_id.setdefault(row.player_id,row)
        positions={position:tuple(sorted(row.player_id for row in by_id.values() if row.position==position)) for position in ("GK","DEF","MID","FWD")}
        diagnostics.candidate_universe_seconds=perf_counter()-universe_started
        diagnostics.construction_seconds=perf_counter()-started
        cache=DecisionInputCache(planning_context.context_id,diagnostics)
        return cls(planning_context,planning_context.context_id,state,tuple(player_pool),MappingProxyType(dict(ordered_projection)),MappingProxyType(projection_lookup),MappingProxyType(by_id),MappingProxyType(positions),MappingProxyType(dict(pipeline)),freshness,tuple(warnings),rules,bundle_identity,planning_context.artifact_hashes,diagnostics,cache)

    def with_advisory(self, name: str, value: object) -> "DecisionInput":
        """Attach a context-scoped advisory artifact without exposing it to policies."""
        if not isinstance(name, str) or not name:
            raise DecisionInputError("advisory name must be non-empty.")
        context_id = getattr(value, "context_id", self.context_id)
        if context_id != self.context_id:
            raise DecisionInputError("advisory artifact context does not match DecisionInput.")
        return replace(self, advisory=MappingProxyType({**dict(self.advisory), name: value}))
    def lineage(self)->dict[str,object]:
        return {"context_id":self.context_id,"bundle_identity":self.bundle_identity,"projection_ids":tuple(self.projections),"artifact_identities":self.artifact_identities}
    def policy_timer(self,name:str):
        class _Timer:
            def __enter__(inner):inner.started=perf_counter();return inner
            def __exit__(inner,*_):self.diagnostics.policy_seconds[name]=self.diagnostics.policy_seconds.get(name,0.0)+perf_counter()-inner.started
        return _Timer()
    def lineup_for(self,state:SquadState,*,target_gameweek:int|None=None,triple_captain:bool=False,bench_boost:bool=False):
        if state.season!=self.state.season or state.rule_version!=self.rules.version:raise DecisionInputError("Lineup state is incompatible with DecisionInput.")
        return self.cache.lineup(state,self.projections,self.rules,target_gameweek=target_gameweek or state.current_gameweek,triple_captain=triple_captain,bench_boost=bench_boost)
