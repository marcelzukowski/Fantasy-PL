"""Offline GW8 experiment. Writes diagnostic results only; never builds an EXE."""
import argparse
from collections import Counter
from dataclasses import asdict
import ctypes
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
OUT = ROOT/'scratch/v3_challenger_20261022'
from desktop_app.decision_runner import shadow_input
from desktop_app.decision_orchestration import planning_context_for_state
from fpl_engine.planning import verify_projection_artifacts
from fpl_engine.shadow import load_squad_state
from fpl_engine.strategy import StrategicPlannerV3
from scripts.diagnostics.v3_incumbent_challenger import ChallengerPlanner, compare_paths, generate_actions


def load_inputs():
    desktop = json.loads((ROOT/'data/processed/desktop_analyses/2026-27/desktop-analysis-20261022T081445787253Z.json').read_text(encoding='utf-8'))['display_state']
    bundle_path = ROOT/'data/processed/predictions/2026-27/20261022T071806Z/shadow_projection_bundle.json'
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    verify_projection_artifacts(bundle_path, json.loads((bundle_path.parent/'run_manifest.json').read_text()), require_hashes=True)
    context = planning_context_for_state(ROOT, desktop, bundle_path, require_canonical_path=False)
    assert context.context_id == '9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208'
    request = OUT/'frozen-input.json'
    request.write_text(json.dumps(shadow_input(desktop, bundle)), encoding='utf-8')
    state, rows, projections, _, _, rules, _ = load_squad_state(request, project_root=ROOT, prediction_bundle_path=bundle_path)
    pool = {p.player_id: p for p in rows if p.player_id in projections}
    names = {p['player_id']: p.get('display_name', p['player_id']) for p in json.loads((bundle_path.parent/'current_players.json').read_text(encoding='utf-8'))}
    return state, pool, projections, rules, names


def peak_memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(key, ctypes.c_size_t) for key in (
            'peak_working_set', 'working_set', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    result = Counters()
    result.cb = ctypes.sizeof(result)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    assert query(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(result), result.cb)
    return result.peak_working_set / 1024**2


class MeasuredIncumbent(StrategicPlannerV3):
    def __init__(self, rules):
        super().__init__(rules)
        self.stats = {'evaluated_by_k': Counter(), 'lineup_computations': 0, 'lineup_cache_hits': 0}

    def _evaluate_action(self, state, action, pool, projections, **kwargs):
        self.stats['evaluated_by_k'][action.transfers_used] += 1
        key = (kwargs['target_gameweek'], action.resulting_squad)
        self.stats['lineup_cache_hits' if key in self._lineup_cache else 'lineup_computations'] += 1
        return super()._evaluate_action(state, action, pool, projections, **kwargs)


def describe(path, names):
    action = path.steps[0].action
    return {'action': action.action, 'out': [names[x] for x in action.transfers_out],
            'in': [names[x] for x in action.transfers_in], 'objective': path.total_path_value,
            'path_points': path.projected_3gw_path_points, 'terminal_ft_value': path.terminal_ft_value,
            'hits': sum(s.action.hit_cost_points for s in path.steps), 'path': asdict(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('incumbent', 'package_beam', 'atomic', 'root_profile', 'known_package', 'combined'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    state, pool, projections, rules, names = load_inputs()
    input_identity = hashlib.sha256((OUT/'frozen-input.json').read_bytes()).hexdigest()
    known_out = {pid for pid, name in names.items() if name in {'Giles', 'B.Fernandes'}}
    known_in = {pid for pid, name in names.items() if name in {'Gabriel', 'Mbeumo'}}
    assert len(known_out) == len(known_in) == 2
    if args.mode == 'combined':
        measured = {strategy: json.loads((OUT/(strategy+'.json')).read_text()) for strategy in ('package_beam', 'atomic')}
        strategy = max(measured, key=lambda key: measured[key]['selected']['objective'])
        started = perf_counter()
        incumbent = MeasuredIncumbent(rules)
        incumbent_result = incumbent.plan(state, pool.values(), projections)
        challenger = ChallengerPlanner(rules, strategy=strategy, root_actions=81)
        candidate_result = challenger.plan(state, pool.values(), projections)
        selected = compare_paths(incumbent_result.best_path, candidate_result.best_path)
        output = {'strategy': strategy, 'wall_seconds': perf_counter()-started,
                  'peak_working_set_mb': peak_memory(), 'input_identity': input_identity,
                  'incumbent': describe(incumbent_result.best_path, names),
                  'challenger': describe(candidate_result.best_path, names),
                  'selected': describe(selected, names), 'stats': challenger.stats}
        assert selected.total_path_value >= incumbent_result.best_path.total_path_value
        assert selected.total_path_value == measured[strategy]['combined_objective'], 'Nondeterministic combined objective'
        assert json.loads(json.dumps(asdict(candidate_result.best_path))) == measured[strategy]['selected']['path'], 'Nondeterministic challenger path'
        (OUT/'combined.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(json.dumps({'strategy': strategy, 'wall_seconds': output['wall_seconds'], 'memory_mb': output['peak_working_set_mb'],
                          'selected': {k:v for k,v in output['selected'].items() if k != 'path'}}), flush=True)
        return
    if args.mode == 'known_package':
        class KnownRoot(MeasuredIncumbent):
            def _actions_for_state(self, current, players, rows, *, target_gameweek):
                if target_gameweek == state.current_gameweek:
                    current_owned = {p.player_id: p for p in current.players}
                    action = self._make_action(current, tuple(current_owned[x] for x in sorted(known_out)), tuple(players[x] for x in sorted(known_in)))
                    assert action is not None
                    return [action]
                return super()._actions_for_state(current, players, rows, target_gameweek=target_gameweek)
        planner = KnownRoot(rules)
        started = perf_counter()
        path = planner._search(state, pool, projections, signals=None, force_hold_now=False)
        output = {'known_package': describe(path, names), 'runtime_seconds': perf_counter()-started}
        (OUT/'known_package.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in output['known_package'].items() if k != 'path'}), flush=True)
        return
    if args.mode == 'root_profile':
        results = {}
        for strategy in ('package_beam', 'atomic'):
            stats = {}
            actions = generate_actions(state, pool, projections, rules, strategy=strategy, max_actions=81, stats=stats)
            results[strategy] = {**stats, 'known_package_retained': any(set(a.transfers_out)==known_out and set(a.transfers_in)==known_in for a in actions)}
        (OUT/'root_profile.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(results), flush=True)
        return
    planner = MeasuredIncumbent(rules) if args.mode == 'incumbent' else ChallengerPlanner(rules, strategy=args.mode, root_actions=81)
    started, cpu = perf_counter(), process_time()
    result = planner.plan(state, pool.values(), projections)
    elapsed = perf_counter()-started
    output = {'mode': args.mode, 'input_identity': input_identity,
              'context_id': '9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208',
              'evaluation_budget': getattr(planner, 'EVALUATION_BUDGET', None),
              'wall_seconds': elapsed, 'cpu_seconds': process_time()-cpu,
              'peak_working_set_mb': peak_memory(), 'config': asdict(planner.config),
              'diagnostics': result.diagnostics, 'stats': planner.stats,
              'selected': describe(result.best_path, names), 'forced_hold': describe(result.hold_now_path, names),
              'result': result.as_dict()}
    if args.mode != 'incumbent':
        roots = planner.root_actions
        output['root_retained_by_k'] = dict(Counter(a.transfers_used for a in roots))
        output['known_package_retained'] = any(set(a.transfers_out)==known_out and set(a.transfers_in)==known_in for a in roots)
        incumbent = json.loads((OUT/'incumbent.json').read_text())
        assert incumbent['input_identity'] == input_identity, 'Incumbent used different input'
        comparison_started = perf_counter()
        prior = SimpleNamespace(total_path_value=incumbent['selected']['objective'], steps=(
            SimpleNamespace(action=SimpleNamespace(is_hold=incumbent['selected']['action'] == 'HOLD')),))
        selected = compare_paths(prior, result.best_path)
        comparison_seconds = perf_counter()-comparison_started
        output['combined_objective'] = selected.total_path_value
        output['combined_runtime_seconds'] = incumbent['wall_seconds'] + elapsed + comparison_seconds
        output['combined_includes_comparison_only'] = True
        output['combined_source'] = args.mode if selected is result.best_path else 'incumbent'
        assert output['combined_objective'] >= incumbent['selected']['objective']
    (OUT/(args.mode+'.json')).write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in output.items() if key not in {'stats', 'result', 'selected', 'forced_hold'}}), flush=True)
    print(json.dumps({'selected': {key:value for key,value in output['selected'].items() if key != 'path'}}), flush=True)


if __name__ == '__main__':
    main()
