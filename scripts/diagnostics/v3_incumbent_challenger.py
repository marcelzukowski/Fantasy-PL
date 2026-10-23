"""Opt-in candidate-coverage experiment. No production module imports this file."""
from collections import Counter, defaultdict
from dataclasses import replace
from itertools import combinations
from time import perf_counter

from fpl_engine.optimizer import next_free_transfers, selling_price, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction, StrategicPlannerV3, StrategicPlannerV3Config,
)


def compare_paths(incumbent, challenger):
    """Keep the complete incumbent unless a separate complete search improves it."""
    if challenger.total_path_value > incumbent.total_path_value + 1e-9:
        return challenger
    # Prefer HOLD on a non-decreasing numerical tie; never lower the incumbent.
    if (challenger.total_path_value >= incumbent.total_path_value
            and challenger.steps[0].action.is_hold and not incumbent.steps[0].action.is_hold):
        return challenger
    return incumbent


def _allocate(budget, max_k):
    # Two-transfer diversity has a protected share; large packages cannot consume it.
    weights = {1: 6, 2: 10, 3: 5, 4: 5, 5: 4}
    quota = {k: 0 for k in range(1, max_k + 1)}
    for index in range(max(0, budget - 1)):
        k = min(quota, key=lambda k: ((quota[k] + 1) / weights[k], k))
        quota[k] += 1
    return quota


def generate_actions(state, pool, projections, rules, *, strategy='atomic', max_transfers=5,
                     max_actions=31, partial_width=32, candidates_per_position=8, stats=None):
    """Bounded shortlist search; prefixes may be invalid, final actions never are."""
    if strategy not in {'package_beam', 'atomic'}:
        raise ValueError('Unknown diagnostic strategy')
    if not 0 <= max_transfers <= 5 or min(max_actions, partial_width, candidates_per_position) < 1:
        raise ValueError('Invalid diagnostic search budget')
    validate_squad(state, rules)
    started = perf_counter()
    planner = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    owned = {p.player_id: p for p in state.players}
    pool = {**pool, **owned}
    gw = state.current_gameweek
    points = {pid: planner._points(row, gw) for pid, row in projections.items()}
    proceeds = {pid: p.selling_price if p.selling_price is not None else selling_price(p.purchase_price, p.current_price, rules)
                for pid, p in owned.items()}
    shortlist = {pos: tuple(sorted(
        (p.player_id for p in pool.values() if p.player_id not in owned and p.position == pos
         and p.player_id in projections and planner._gameweek_projection(projections[p.player_id], gw) is not None),
        key=lambda pid: (-points[pid], pool[pid].current_price, pid))[:candidates_per_position])
        for pos in ('GK', 'DEF', 'MID', 'FWD')}
    moves = tuple((out, incoming) for out in sorted(owned) for incoming in shortlist[owned[out].position])
    hit_unit = int(rules.value('transfers', 'normal_gameweek', 'points_cost_per_transfer_above_allowance'))
    attempted, legal = Counter(), Counter()
    packages = {}
    seen = set()

    def score(package):
        outs, ins = package
        return sum(points[pid] for pid in ins) - sum(points[pid] for pid in outs) - max(0, len(outs)-state.free_transfers)*hit_unit

    def margin(package):
        outs, ins = package
        return state.bank + sum(proceeds[pid] for pid in outs) - sum(pool[pid].current_price for pid in ins)

    def rank(package):
        return -score(package), -margin(package), package

    def add(package):
        outs, ins = package
        if package in seen:
            return
        seen.add(package)
        attempted[len(outs)] += 1
        # _make_action performs complete simultaneous finance/club/position validation.
        action = planner._make_action(state, tuple(owned[x] for x in outs), tuple(pool[x] for x in ins))
        if action is not None:
            packages[package] = action
            legal[len(outs)] += 1

    def diversify(rows, width):
        # Round-robin OUT sets protects coverage from many versions of one sale.
        groups = defaultdict(list)
        for row in sorted(rows, key=rank):
            groups[row[0]].append(row)
        chosen = []
        for depth in range(width):
            layer = sorted((values[depth] for values in groups.values() if len(values) > depth), key=rank)
            chosen.extend(layer[:width-len(chosen)])
            if len(chosen) >= width or not layer:
                break
        return chosen

    # K1/K2 are explored independently of the K3+ prefix frontier. All pairs are
    # from the unchanged V3 shortlist, bounded by 15*8 raw moves (not the full pool).
    for out, incoming in moves:
        if max_transfers >= 1:
            add(((out,), (incoming,)))
    if max_transfers >= 2:
        for left, right in combinations(moves, 2):
            if left[0] != right[0] and left[1] != right[1]:
                add((tuple(sorted((left[0], right[0]))), tuple(sorted((left[1], right[1])))))

    if strategy == 'package_beam':
        frontier = [((), ())]
        for k in range(1, max_transfers + 1):
            candidates = set()
            for outs, ins in frontier:
                for out, incoming in moves:
                    if out not in outs and incoming not in ins:
                        candidates.add((tuple(sorted((*outs, out))), tuple(sorted((*ins, incoming)))))
            for package in sorted(candidates):
                add(package)
            # No finance or club check is applied to the retained partial packages.
            frontier = diversify(candidates, partial_width)
    else:
        # Complete OUT sets are selected before constructing IN packages. This
        # allows funding and club rotations whose every proper prefix is invalid.
        for k in range(3, max_transfers + 1):
            outsets = [outs for outs in combinations(sorted(owned), k)
                       if all(shortlist[owned[pid].position] for pid in outs)]
            outsets.sort(key=lambda outs: (sum(points[pid] for pid in outs), -sum(proceeds[pid] for pid in outs), outs))
            selected = outsets[:partial_width]
            # Reserve outgoing coverage across position/club patterns as well.
            patterns = {}
            for outs in outsets:
                pattern = tuple(sorted((owned[pid].position, owned[pid].club_id) for pid in outs))
                patterns.setdefault(pattern, outs)
            funding = sorted(outsets, key=lambda outs: (-sum(proceeds[pid] for pid in outs), sum(points[pid] for pid in outs), outs))
            for outs in [*list(patterns.values())[:partial_width//2], *funding[:partial_width//2]]:
                if outs not in selected:
                    selected.append(outs)
            for outs in selected:
                incoming_frontier = [()]
                for out in outs:
                    candidates = {tuple(sorted((*ins, pid))) for ins in incoming_frontier
                                  for pid in shortlist[owned[out].position] if pid not in ins}
                    ranked = sorted(candidates, key=lambda ins: (
                        -sum(points[pid] for pid in ins), sum(pool[pid].current_price for pid in ins), ins))
                    cheap = sorted(candidates, key=lambda ins: (
                        sum(pool[pid].current_price for pid in ins), -sum(points[pid] for pid in ins), ins))
                    incoming_frontier = ranked[:max(1, partial_width//2)]
                    incoming_frontier.extend(ins for ins in cheap if ins not in incoming_frontier)
                    incoming_frontier = incoming_frontier[:partial_width]
                for ins in incoming_frontier:
                    add((outs, ins))

    hold = StrategicAction('HOLD', (), (), 0, 0, state.bank, state.free_transfers,
                           next_free_transfers(state.free_transfers, 0, rules), tuple(sorted(owned)))
    quota = _allocate(max_actions, max_transfers) if max_transfers else {}
    chosen = [hold]
    for k, count in quota.items():
        rows = [package for package in packages if len(package[0]) == k]
        chosen.extend(packages[key] for key in diversify(rows, count))
    if stats is not None:
        stats.update({'attempted_by_k': dict(attempted), 'legal_by_k': dict(legal),
                      'retained_by_k': dict(Counter(a.transfers_used for a in chosen)),
                      'quota_by_k': quota, 'raw_moves': len(moves),
                      'runtime_seconds': perf_counter()-started})
    return chosen


class ChallengerPlanner(StrategicPlannerV3):
    """Changes only candidate coverage; native beams, objective and HOLD selection."""
    EVALUATION_BUDGET = 6000
    def __init__(self, rules, config=None, *, strategy='atomic', stats=None, root_actions=None):
        super().__init__(rules, config or replace(StrategicPlannerV3Config(), max_actions_per_state=31))
        self.strategy = strategy
        self.stats = stats if stats is not None else {}
        self.root_actions_budget = root_actions

    def plan(self, state, pool, projections, **kwargs):
        self.generation_cache = {}
        self.stats.clear()
        self.stats.update({'evaluated_by_k': Counter(), 'lineup_computations': 0, 'lineup_cache_hits': 0,
                           'generation_cache_hits': 0, 'generation_calls': 0, 'generation': []})
        self.root_gameweek = state.current_gameweek
        return super().plan(state, pool, projections, **kwargs)

    def _actions_for_state(self, state, pool_by_id, projections, *, target_gameweek):
        self.stats['generation_calls'] += 1
        key = (target_gameweek, state.bank, state.free_transfers, tuple(sorted(
            (p.player_id, p.position, p.club_id, p.current_price, p.purchase_price, p.selling_price) for p in state.players)))
        if key in self.generation_cache:
            self.stats['generation_cache_hits'] += 1
            return self.generation_cache[key]
        stats = {}
        budget = self.root_actions_budget if self.root_actions_budget and target_gameweek == self.root_gameweek else self.config.max_actions_per_state
        actions = generate_actions(state, pool_by_id, projections, self.rules, strategy=self.strategy,
            max_actions=budget, candidates_per_position=self.config.candidates_per_position, stats=stats)
        self.generation_cache[key] = actions
        self.stats['generation'].append({'gameweek': target_gameweek, **stats})
        if target_gameweek == self.root_gameweek:
            self.root_actions = actions
        return actions

    def _evaluate_action(self, state, action, pool_by_id, projections, **kwargs):
        if sum(self.stats['evaluated_by_k'].values()) >= self.EVALUATION_BUDGET:
            raise RuntimeError('Diagnostic action-evaluation budget exhausted; keep incumbent')
        self.stats['evaluated_by_k'][action.transfers_used] += 1
        key = (kwargs['target_gameweek'], action.resulting_squad)
        self.stats['lineup_cache_hits' if key in self._lineup_cache else 'lineup_computations'] += 1
        return super()._evaluate_action(state, action, pool_by_id, projections, **kwargs)
