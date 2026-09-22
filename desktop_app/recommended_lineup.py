"""Validation-only adapter for an existing Decision Engine lineup preview."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import Mapping
from .state import POSITION_COUNTS, DesktopSquadState

class RecommendedLineupError(ValueError): pass

@dataclass(frozen=True)
class RecommendedLineup:
    squad_ids: tuple[str,...]; starting_xi_ids: tuple[str,...]; bench_ids: tuple[str,...]
    captain_id: str; vice_captain_id: str; transfers_out: tuple[str,...]; transfers_in: tuple[str,...]

def build_recommended_lineup(state: DesktopSquadState, players: Mapping[str, object], recommendation: Mapping[str, object]) -> RecommendedLineup:
    owned=[str(x) for x in state.player_ids]; outgoing=tuple(str(x) for x in recommendation.get("transfers_out",())); incoming=tuple(str(x) for x in recommendation.get("transfers_in",()))
    if len(outgoing)!=len(incoming) or len(set(outgoing))!=len(outgoing) or len(set(incoming))!=len(incoming): raise RecommendedLineupError("Recommendation transfers are incomplete or conflicting.")
    if any(x not in owned for x in outgoing): raise RecommendedLineupError("Recommendation removes a player who is not owned.")
    squad=[x for x in owned if x not in outgoing]+list(incoming)
    if len(squad)!=15 or len(set(squad))!=15: raise RecommendedLineupError("Recommended squad must contain 15 distinct players.")
    if any(x not in players for x in squad): raise RecommendedLineupError("Recommended players are unavailable in the production bundle.")
    if Counter(str(players[x].position) for x in squad)!=Counter(POSITION_COUNTS): raise RecommendedLineupError("Recommended squad does not have the required 2/5/5/3 structure.")
    if any(v>3 for v in Counter(str(players[x].team_id) for x in squad).values()): raise RecommendedLineupError("Recommended squad exceeds the three-player club limit.")
    starters=tuple(str(x) for x in recommendation.get("starting_xi",())); bench=tuple(str(x) for x in recommendation.get("bench_order",())); captain=str(recommendation.get("captain", "")); vice=str(recommendation.get("vice_captain", ""))
    if len(starters)!=11 or len(set(starters))!=11 or not set(starters)<=set(squad): raise RecommendedLineupError("Recommendation must provide 11 distinct starters from the recommended squad.")
    if len(bench)!=4 or len(set(bench))!=4 or set(bench)!=set(squad)-set(starters): raise RecommendedLineupError("Recommendation bench must be the four remaining players in engine order.")
    formation=Counter(str(players[x].position) for x in starters)
    if formation["GK"]!=1 or not(3<=formation["DEF"]<=5 and 2<=formation["MID"]<=5 and 1<=formation["FWD"]<=3): raise RecommendedLineupError("Recommendation starting XI has an invalid FPL formation.")
    if captain not in starters or vice not in starters or captain==vice: raise RecommendedLineupError("Captain and vice-captain must be distinct starters.")
    return RecommendedLineup(tuple(squad),starters,bench,captain,vice,outgoing,incoming)
