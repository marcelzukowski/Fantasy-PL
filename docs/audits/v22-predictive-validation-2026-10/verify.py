"""Independent cohort assertions and preservation check; never modifies inputs."""
from collections import defaultdict
from hashlib import sha256
import json
import re
from pathlib import Path
from inventory import ROOT,HERE
from evaluate import load, utc, selfcheck

selfcheck()
report_path=HERE.parent/'v22-predictive-validation-2026-10.md'
report=report_path.read_text(encoding='utf-8')
assert re.findall(r'^## (\d+)\.',report,re.MULTILINE)==[str(n) for n in range(1,15)]
for reference in re.findall(r'\]\(([^)]+)\)',report):
    assert (report_path.parent/reference.split('#')[0]).exists(),reference
r=load(HERE/'results.json')
s=load(HERE/'supplement.json')
d=load(HERE/'decision-metrics.json')
assert r['raw_hash_failures']==[] and r['row_exclusions']==[]
assert len(r['selected'])==2 and len(r['rows'])==1334
assert len({(p['gw'],p['player_id']) for p in r['rows']})==1334
assert all(v['status']=='PRE_DEADLINE_COMPLETE' for v in s['archive_validation'])
assert all(p['fixtures']==1 for p in r['rows'])
assert all(0<=v<=1 for p in r['rows'] for k,v in p.items() if k.startswith('p_'))
assert all(abs(p['p_blank']+p['p_return']-1)<1e-9 for p in r['rows'])
assert all(p['p_5_plus']>=p['p_8_plus']>=p['p_10_plus']>=p['p_15_plus'] for p in r['rows'])
assert [p['captain_points'] for p in d['decisions']]==[2,13]
assert all(v['baseline']['n']==v['v22_matched']['n'] for v in r['baselines'].values())
by_provider={(p['gw'],p['provider_id']):p for p in r['rows']}
latest={}
hashes=json.loads((HERE/'input-hashes.json').read_text())
for name in hashes:
    if '/element_summary/' not in name or not name.endswith('snapshot.metadata.json'):continue
    path=ROOT/name
    meta=load(path)
    provider=meta['source_record_id']
    if provider not in latest or utc(meta['retrieved_at'])>utc(latest[provider][0]['retrieved_at']):
        latest[provider]=(meta,path.parent/'payload.bin')
crosschecks=[]
for provider,(meta,path) in latest.items():
    body=load(path)
    by_gw=defaultdict(list)
    for h in body['history']:by_gw[h['round']].append(h)
    for gw in (6,7):
        point=by_provider.get((gw,str(provider)))
        if not point or gw not in by_gw:continue
        observed=by_gw[gw]
        assert all(str(h['element'])==str(provider) for h in observed)
        equal=all(sum(h[field] for h in observed)==point[target]
                  for field,target in (('total_points','points'),('minutes','minutes'),('goals_scored','goals'),('assists','assists')))
        crosschecks.append({'gw':gw,'provider_id':provider,'equal':equal})
assert all(c['equal'] for c in crosschecks), 'event-live and player history disagree'
future_sources=[]
source_time_counts={}
def inspect(obj,stamp,run):
    if isinstance(obj,dict):
        for key,value in obj.items():
            if key in ('known_at','retrieved_at','source_snapshot_timestamp') and isinstance(value,str):
                source_time_counts[run]=source_time_counts.get(run,0)+1
                if utc(value)>stamp:future_sources.append((run,key,value))
            inspect(value,stamp,run)
    elif isinstance(obj,list):
        for value in obj:inspect(value,stamp,run)
for snap in r['selected']:
    run=(ROOT/snap['path']).parent
    for name in ('source_freshness.json','source_provenance.json'):
        inspect(load(run/name),utc(snap['generated']),run.name)
assert not future_sources
protected=json.loads((HERE/'protected-before.json').read_text())['files']
protected.update(hashes)
changes=[]
for name,digest in protected.items():
    path=ROOT/name
    if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=digest:changes.append(name)
before=(HERE/'git-status-before.txt').read_text(encoding='utf-8').splitlines()
after=(HERE/'git-status-after.txt').read_text(encoding='utf-16').splitlines()
def outside(lines):
    return {line for line in lines if 'docs/audits/v22-predictive-validation-2026-10' not in line}
status_changes=sorted(outside(before)^outside(after))
release={name:{'bytes':(ROOT/name).stat().st_size,'sha256':sha256((ROOT/name).read_bytes()).hexdigest()}
         for name in ('FPLControlCenter_PL.exe','dist/FPLControlCenter_PL.exe')}
result={'selfcheck':'PASS','cohort_checks':'PASS','report_sections_and_links':'PASS','archives_pass':len(s['archive_validation']),
        'element_summary_crosscheck_rows':len(crosschecks),'element_summary_mismatches':0,
        'source_time_fields_checked':source_time_counts,'future_source_times':future_sources,
        'protected_files_checked':len(protected),'changed_protected_files':changes,
        'git_status_changes_outside_audit':status_changes,'release':release}
(HERE/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
assert not changes and not status_changes
