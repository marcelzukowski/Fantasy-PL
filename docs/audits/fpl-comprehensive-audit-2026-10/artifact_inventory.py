"""Read-only local artifact summaries; no credentials/account values exported."""
from pathlib import Path
import json

ROOT=Path.cwd(); OUT=Path(__file__).resolve().parent
def obj(path):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return None

inventory={}
projection=[]
for p in sorted((ROOT/'data/processed/predictions/2026-27').glob('*/run_manifest.json')):
    r=obj(p)
    if not isinstance(r,dict):continue
    projection.append({'path':str(p.relative_to(ROOT)),'timestamp':r.get('prediction_timestamp'),'simulation':r.get('simulation'),'market_shadow':r.get('market_shadow'),'timing':r.get('timing') or r.get('timings')})
inventory['projection_manifests']=projection
archives=[]
for p in (ROOT/'data/processed/historical_replay_cases').rglob('archive_case.json'):
    r=obj(p)
    if not isinstance(r,dict):continue
    archives.append({'path':str(p.relative_to(ROOT)),'schema':r.get('schema_version'),'season':r.get('season'),'gameweek':r.get('gameweek'),'outcome_files':len(list((p.parent/'outcomes').glob('*.json'))),'keys':sorted(r)})
inventory['archives']=archives
for name,base in [('chips','data/processed/desktop_chips'),('backtests','data/processed/backtests')]:
    paths=[p for p in (ROOT/base).rglob('*.json') if p.is_file()]
    inventory[name+'_files']=[str(p.relative_to(ROOT)) for p in sorted(paths)]
markets=[]
for p in (ROOT/'data/processed/market_shadow').rglob('*.json'):
    r=obj(p)
    if not isinstance(r,dict):continue
    markets.append({'path':str(p.relative_to(ROOT)),'status':r.get('status'),'production_influence':r.get('production_influence'),'coverage':r.get('coverage'),'projection_run_id':r.get('projection_run_id'),'prediction_timestamp':r.get('prediction_timestamp'),'market_snapshot_timestamp':r.get('market_snapshot_timestamp'),'pit_status':r.get('pit_status'),'keys':sorted(r)})
inventory['market_sidecars']=markets
evidence=[]
for base in ('scratch','data/processed/backtests','data/processed/advanced'):
    for p in (ROOT/base).rglob('*.json'):
        low=str(p).lower()
        if any(token in low for token in ('replay','calibrat','v22','backtest','chip','benchmark','market')):
            evidence.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size})
inventory['evidence_candidates']=evidence
(OUT/'artifact-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
print(json.dumps({'projection_manifests':len(projection),'archive_cases':len(archives),'archive_outcome_files':sum(a['outcome_files'] for a in archives),'chip_files':len(inventory['chips_files']),'backtest_files':len(inventory['backtests_files']),'market_sidecars':len(markets),'evidence_candidates':len(evidence)},indent=2))
for row in projection[-3:]: print(json.dumps(row))
print('CHIP',inventory['chips_files'][-5:])
print('EVIDENCE',*[r['path'] for r in evidence if any(t in r['path'].lower() for t in ['integrated','strict_backtest','summary','validation','replay_report'])][:35],sep='\n')
