"""Descriptive frozen recommendations only; never reruns a policy."""
import json
from statistics import mean
from inventory import ROOT,HERE
from evaluate import load,INPUTS,metrics

r=load(HERE/'results.json')
out={'decisions':[], 'matched_high_xp_baselines':{},'zero_baseline':{},'probabilities':{}}
for gw in sorted({p['gw'] for p in r['rows']}):
    candidates=[a for a in r['archives'] if a['gw']==gw]
    chosen=max(candidates,key=lambda a:a['created'])
    case=load(ROOT/chosen['path'])
    report=load(ROOT/case['decision_report']['path'])
    by_id={p['player_id']:p for p in r['rows'] if p['gw']==gw}
    recommendation=report['recommendation']
    captain=by_id[recommendation['captain']]
    eligible=[by_id[p] for p in recommendation['starting_xi']]
    comparison={}
    for baseline in ('previous_gw','recent_mean'):
        picked=sorted((p for p in eligible if baseline in p),key=lambda p:(-p[baseline],p['player_id']))[0]
        comparison[baseline]={'player':picked['name'],'forecast':picked[baseline],'points':picked['points']}
    transfers=[{'out':by_id[o]['name'],'in':by_id[i]['name'],
                'forecast_difference':by_id[i]['xp']-by_id[o]['xp'],
                'realised_raw_player_difference':by_id[i]['points']-by_id[o]['points']}
               for o,i in zip(recommendation['transfers_out'],recommendation['transfers_in'])]
    out['decisions'].append({'gw':gw,'archive':chosen['path'],'created':report['created_at'],
       'optimizer_version':recommendation['optimizer_version'],'captain':captain['name'],
       'captain_xp':captain['xp'],'captain_points':captain['points'],
       'benchmarked_captains_on_same_recorded_xi':comparison,'transfers':transfers,
       'policy_keys':list(report['policy_results']),
       'strategic_preview_keys':[list(x) for x in report['strategy_previews'] if x['strategy_key']=='strategic'],
       'decision_margin':recommendation.get('decision_margin')})
for threshold in (0,2):
    group=[p for p in r['rows'] if p['xp']>=threshold]
    out['matched_high_xp_baselines'][threshold]={}
    for baseline in ('previous_gw','recent_mean','minutes_aware'):
        matched=[p for p in group if baseline in p]
        out['matched_high_xp_baselines'][threshold][baseline]={'v22':metrics(matched),'baseline':metrics(matched,baseline)}
    out['zero_baseline'][threshold]=metrics([{**p,'zero':0} for p in group],'zero')
for name,test in (('p_blank',lambda p:p['goals']+p['assists']==0),('p_return',lambda p:p['goals']+p['assists']>0)):
    # FixtureSimulator defines a return as a goal or assist, not a points threshold.
    group=[p for p in r['rows'] if name in p]
    out['probabilities'][name]={'n':len(group),'mean_prediction':mean(p[name] for p in group),
        'observed':mean(test(p) for p in group),'brier':mean((p[name]-test(p))**2 for p in group)}
(HERE/'decision-metrics.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
hashes=json.loads((HERE/'input-hashes.json').read_text())
hashes.update({p:v for p,v in INPUTS.items() if not p.startswith('docs/audits/')})
(HERE/'input-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
