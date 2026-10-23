"""Non-production pruning experiments; native actions, lineup and objective."""
from collections import Counter, defaultdict, deque
from dataclasses import asdict, replace
import hashlib
import json
from time import perf_counter

from fpl_engine.optimizer import next_free_transfers
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction, StrategicPlannerV3, StrategicPlannerV3Config, StrategicPath, _Node,
)
from scripts.diagnostics.v3_incumbent_challenger import generate_actions


def state_key(state):
    """Prove future equivalence using every state field, including personal prices."""
    value = asdict(state) if not isinstance(state, dict) else dict(state)
    value['players'] = sorted(value['players'], key=lambda row: row['player_id'])
    return json.dumps(value, sort_keys=True, default=str, separators=(',', ':'))


def deduplicate_nodes(nodes):
    """Discard only lower/equal accumulated value for exactly equivalent futures."""
    best = {}
    dominated = equal = 0
    for node in sorted(nodes, key=lambda n: (-n.points, StrategicPlannerV3._path_key(n.steps))):
        key = state_key(node.state)
        if key not in best:
            best[key] = node
        elif best[key].points > node.points:
            dominated += 1
        else:
            equal += 1
    return list(best.values()), dominated, equal


class BeamAuditPlanner(StrategicPlannerV3):
    """A=dominance; B=A+diversity; C=A+feasible HOLD-completion heuristic."""
    ACTION_BUDGET = 12000
    HEURISTIC_BUDGET = 20000

    def __init__(self, rules, config=None, *, strategy='raw', candidate_mode='native', stats=None, trace_target=None):
        super().__init__(rules, config or StrategicPlannerV3Config())
        if strategy not in {'raw', 'dominance', 'diversity', 'horizon'}:
            raise ValueError('Unknown pruning strategy')
        if candidate_mode not in {'native', 'k2', 'k5'}:
            raise ValueError('Unknown diagnostic candidate mode')
        if self.config.planning_horizon != 3:
            raise ValueError('This audit uses the existing three-GW horizon')
        self.strategy, self.candidate_mode = strategy, candidate_mode
        self.stats = stats if stats is not None else {}
        self.trace_target = trace_target

    def plan(self, state, pool, projections, **kwargs):
        self.root_gw = state.current_gameweek
        self.generation_cache = {}
        self.completion_cache = {}
        self.stats.clear()
        self.stats.update({'dominated': 0, 'equal_duplicates': 0, 'expanded_by_k': Counter(),
                           'available_dominated': 0, 'available_equal_duplicates': 0,
                           'lineup_computations': 0, 'lineup_cache_hits': 0,
                           'heuristic_lineup_computations': 0, 'heuristic_cache_hits': 0,
                           'heuristic_probes': 0, 'generation_cache_hits': 0,
                           'layer_stats': [], 'trace': []})
        return super().plan(state, pool, projections, **kwargs)

    def _actions_for_state(self, state, pool_by_id, projections, *, target_gameweek):
        if self.candidate_mode == 'native':
            return super()._actions_for_state(state, pool_by_id, projections, target_gameweek=target_gameweek)
        key = state_key(state)
        if key in self.generation_cache:
            self.stats['generation_cache_hits'] += 1
            return self.generation_cache[key]
        actions = generate_actions(state, pool_by_id, projections, self.rules, strategy='package_beam',
            max_transfers=2 if self.candidate_mode == 'k2' else 5,
            max_actions=81 if target_gameweek == self.root_gw else 31,
            candidates_per_position=self.config.candidates_per_position)
        self.generation_cache[key] = actions
        return actions

    def _evaluate_action(self, state, action, pool_by_id, projections, **kwargs):
        if sum(self.stats['expanded_by_k'].values()) >= self.ACTION_BUDGET:
            raise RuntimeError('Diagnostic action budget exhausted')
        self.stats['expanded_by_k'][action.transfers_used] += 1
        key = (kwargs['target_gameweek'], action.resulting_squad)
        self.stats['lineup_cache_hits' if key in self._lineup_cache else 'lineup_computations'] += 1
        return super()._evaluate_action(state, action, pool_by_id, projections, **kwargs)

    def _hold_completion(self, state, pool, projections):
        """Attainable lower bound, NOT an admissible optimistic upper bound."""
        key = state_key(state)
        if key in self.completion_cache:
            return self.completion_cache[key]
        current, points = state, 0.0
        while current.current_gameweek < self.root_gw + self.config.planning_horizon:
            if self.stats['heuristic_probes'] >= self.HEURISTIC_BUDGET:
                raise RuntimeError('Diagnostic completion budget exhausted')
            self.stats['heuristic_probes'] += 1
            hold = StrategicAction('HOLD',(),(),0,0,current.bank,current.free_transfers,
                next_free_transfers(current.free_transfers,0,self.rules),tuple(sorted(p.player_id for p in current.players)))
            lineup_key = (current.current_gameweek, hold.resulting_squad)
            self.stats['heuristic_cache_hits' if lineup_key in self._lineup_cache else 'heuristic_lineup_computations'] += 1
            current, step = StrategicPlannerV3._evaluate_action(self, current, hold, pool, projections,
                target_gameweek=current.current_gameweek, signals=None, offset=current.current_gameweek-self.root_gw)
            points += step.points_after_hit
        result = points + self._terminal_ft_value(current)
        self.completion_cache[key] = result
        return result

    def _score(self, node, offset, pool, projections):
        if offset == self.config.planning_horizon-1:
            return node.points + self._terminal_ft_value(node.state)
        if self.strategy == 'horizon':
            return node.points + self._hold_completion(node.state, pool, projections)
        return node.points

    def _diverse(self, ranked):
        buckets = defaultdict(lambda: defaultdict(list))
        for node in ranked:
            first = node.steps[0].action
            buckets[(first.transfers_used, node.state.free_transfers)][(first.action, first.transfers_out, first.transfers_in)].append(node)
        streams = []
        # One family per round within each (initial K, FT) bucket.
        for families in buckets.values():
            queue = deque(deque(rows) for rows in families.values())
            stream = deque()
            while queue:
                family = queue.popleft()
                stream.append(family.popleft())
                if family:
                    queue.append(family)
            streams.append(stream)
        chosen = []
        while streams and len(chosen) < self.config.beam_width:
            remaining = []
            for stream in streams:
                if len(chosen) == self.config.beam_width:
                    break
                chosen.append(stream.popleft())
                if stream:
                    remaining.append(stream)
            streams = remaining
        return chosen

    def _trace(self, expanded, candidates, beam, offset, pool, projections):
        if not self.trace_target:
            return
        known = self.trace_target[offset]
        prefix = self._path_key(known.steps)
        matching = [n for n in expanded if self._path_key(n.steps) == prefix]
        ordered = sorted(expanded, key=lambda n: (-self._score(n, offset, pool, projections), self._path_key(n.steps)))
        ghost_score = self._score(known, offset, pool, projections)
        rank = next((i+1 for i,n in enumerate(ordered) if self._path_key(n.steps)==prefix), None)
        counterfactual_rank = 1 + sum((-self._score(n,offset,pool,projections),self._path_key(n.steps)) < (-ghost_score,prefix) for n in expanded if self._path_key(n.steps)!=prefix)
        remaining = self.config.planning_horizon-offset-1
        maximum_ft = int(self.rules.value('free_transfer_state','maximum'))
        potential = self._terminal_ft_value(replace(known.state, free_transfers=min(maximum_ft,known.state.free_transfers+remaining)))
        self.stats['trace'].append({
            'gw': self.root_gw+offset, 'state_sha256': hashlib.sha256(state_key(known.state).encode()).hexdigest(),
            'state': json.loads(state_key(known.state)), 'accumulated_points': known.points,
            'hits': sum(step.action.hit_cost_points for step in known.steps),
            'ft': known.state.free_transfers, 'bank': known.state.bank,
            'terminal_ft_if_hold': potential, 'ranking_score': ghost_score,
            'rank_before_pruning': rank, 'counterfactual_rank': counterfactual_rank,
            'score_at_beam_tail': self._score(beam[-1],offset,pool,projections),
            'expanded': bool(matching),
            'retained_exact_path': any(self._path_key(n.steps)==prefix for n in beam),
            'retained_equivalent_state': any(state_key(n.state)==state_key(known.state) and n.points>=known.points for n in beam),
            'rank_after_dominance': next((i+1 for i,n in enumerate(candidates) if self._path_key(n.steps)==prefix),None)})

    def _search(self, state, pool_by_id, projections, *, signals, force_hold_now):
        beam = [_Node(state, (), 0.0)]
        for offset in range(self.config.planning_horizon):
            expanded = []
            for node in beam:
                self._states_expanded += 1
                started = perf_counter()
                actions = self._actions_for_state(node.state,pool_by_id,projections,target_gameweek=node.state.current_gameweek)
                self._timing['candidate_generation_seconds'] += perf_counter()-started
                if offset == 0 and force_hold_now:
                    actions = [a for a in actions if a.is_hold]
                started = perf_counter()
                for action in actions:
                    self._actions_evaluated += 1
                    next_state,step = self._evaluate_action(node.state,action,pool_by_id,projections,
                        target_gameweek=node.state.current_gameweek,signals=signals,offset=offset)
                    expanded.append(_Node(next_state,node.steps+(step,),node.points+step.points_after_hit))
                self._timing['beam_expansion_seconds'] += perf_counter()-started
            if not expanded:
                raise RuntimeError('No legal diagnostic path')
            unique, available_dominated, available_equal = deduplicate_nodes(expanded)
            self.stats['available_dominated'] += available_dominated
            self.stats['available_equal_duplicates'] += available_equal
            candidates, dominated, equal = expanded, 0, 0
            if self.strategy != 'raw':
                candidates, dominated, equal = unique, available_dominated, available_equal
                self.stats['dominated'] += dominated
                self.stats['equal_duplicates'] += equal
            ranked = sorted(candidates, key=lambda n: (-self._score(n,offset,pool_by_id,projections),self._path_key(n.steps)))
            beam = self._diverse(ranked) if self.strategy=='diversity' and offset<self.config.planning_horizon-1 else ranked[:self.config.beam_width]
            self.stats['layer_stats'].append({'force_hold':force_hold_now,'gw':self.root_gw+offset,
                'expanded':len(expanded),'unique':len(candidates),'dominated':dominated,'equal_duplicates':equal,
                'equivalent_unique':len(unique),'available_dominated':available_dominated,'available_equal_duplicates':available_equal,
                'retained':len(beam),'retained_ft':dict(Counter(n.state.free_transfers for n in beam)),
                'retained_unique_states':len({state_key(n.state) for n in beam}),
                'retained_first_k':dict(Counter(n.steps[0].action.transfers_used for n in beam)),
                'retained_initial_families':len({self._path_key(n.steps[:1]) for n in beam})})
            if not force_hold_now:
                self._trace(expanded,ranked,beam,offset,pool_by_id,projections)
        best = min(beam,key=lambda n: (-(n.points+self._terminal_ft_value(n.state)),self._path_key(n.steps)))
        terminal = self._terminal_ft_value(best.state)
        return StrategicPath(best.steps,best.points,terminal,best.points+terminal)
