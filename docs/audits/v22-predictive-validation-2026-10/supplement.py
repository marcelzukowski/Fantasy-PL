"""Read-only archive verification and descriptive breakdowns of the fixed cohort."""
from dataclasses import asdict
from collections import Counter
import json
from statistics import mean
from inventory import ROOT, HERE
from evaluate import load, INPUTS, metrics, spearman
from fpl_engine.validation.replay_archive import validate_archive_case

r=load(HERE/'results.json')
rows=r['rows']
out={'archive_validation':[], 'unique_players':len({p['player_id'] for p in rows}),
     'zero_actual_rows':sum(p['points']==0 and p['minutes']==0 for p in rows),
     'fixture_counts':dict(Counter(p['fixtures'] for p in rows)),
     'minutes_by_gw':{gw:metrics([p for p in rows if p['gw']==int(gw)],'predicted_minutes','minutes') for gw in r['by_gw']},
     'minutes_strata':{},'high_xp':{},'ranking':r['ranking'],'calibration':r['calibration'],
     'points_strata':r['by_xp'], 'error_sources':{},'archive_report_shapes':[]}
for archive in r['archives']:
    validation=validate_archive_case(ROOT,ROOT/archive['path'])
    out['archive_validation'].append(asdict(validation))
    case=load(ROOT/archive['path'])
    for label in ('decision_report','analysis_manifest','projection_manifest'):
        ref=case[label]
        obj=load(ROOT/ref['path'])
        if label=='decision_report':
            out['archive_report_shapes'].append({'gw':archive['gw'],'created':obj.get('created_at'),
                'keys':list(obj), 'v3':obj.get('strategic_plan_v3'), 'captaincy':obj.get('captaincy'),
                'strategic_plan':obj.get('strategic_plan')})
for low,high in ((0,1),(1,30),(30,60),(60,80),(80,1000)):
    group=[p for p in rows if low<=p['predicted_minutes']<high]
    out['minutes_strata'][f'{low}-{high}']={'points':metrics(group),'minutes':metrics(group,'predicted_minutes','minutes'),
        'mean_predicted_minutes':mean(p['predicted_minutes'] for p in group) if group else None,
        'mean_actual_minutes':mean(p['minutes'] for p in group) if group else None}
for threshold in (2,4,6):
    group=[p for p in rows if p['xp']>=threshold]
    out['high_xp'][threshold]={'points':metrics(group),'spearman':spearman(group)}
for label,group in [('played',[p for p in rows if p['minutes']>0]),('did_not_play',[p for p in rows if p['minutes']==0]),
                    ('minutes_error_30plus',[p for p in rows if abs(p['predicted_minutes']-p['minutes'])>=30])]:
    out['error_sources'][label]=metrics(group)
out['largest_errors']=sorted(rows,key=lambda p:abs(p['xp']-p['points']),reverse=True)[:15]
(HERE/'supplement.json').write_text(json.dumps(out,indent=2,default=str),encoding='utf-8')
hashes=json.loads((HERE/'input-hashes.json').read_text())
hashes.update(INPUTS)
# Generated diagnostic results are outputs, not protected historical inputs.
hashes={p:v for p,v in hashes.items() if not p.startswith('docs/audits/v22-predictive-validation-2026-10/')}
(HERE/'input-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k not in ('archive_report_shapes','ranking','largest_errors','calibration')},indent=2,default=str))
print('REPORT SHAPES')
for report in out['archive_report_shapes']:print(json.dumps(report,default=str)[:3500])
