"""Bounded local evidence inventory. Never follows junctions or writes inputs."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
SKIP = {'.git', '.venv', '.venv-solver', '__pycache__', 'node_modules', 'pytest-tmp', '.hypothesis'}

def files(base):
    for parent, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = [n for n in dirs if n not in SKIP and not (Path(parent)/n).is_junction() and not (Path(parent)/n).is_symlink()]
        for name in names:
            path=Path(parent)/name
            if not path.is_symlink():
                yield path

def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        return None

if __name__ == '__main__':
    (HERE/'git-status-before.txt').write_bytes(subprocess.check_output(['git.exe','status','--porcelain=v1','-uall']))
    previous=json.loads((ROOT/'scratch/reliability_fixes_20261023/before.json').read_text())['files']
    protected={n:sha256((ROOT/n).read_bytes()).hexdigest() for n in previous if (ROOT/n).is_file()}
    for base in ('src','desktop_app','scripts','tests','config','docs/agents','openspec'):
        for path in files(ROOT/base):
            if path.suffix in {'.py','.yaml','.toml','.json','.md'}:
                protected[str(path.relative_to(ROOT))]=sha256(path.read_bytes()).hexdigest()
    (HERE/'protected-before.json').write_text(json.dumps(dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(),files=protected),indent=2))
    manifests=[]; bundles=[]; archives=[]; outcome_paths=[]; other=[]
    for base in ('data','scratch'):
        for path in files(ROOT/base):
            relative=str(path.relative_to(ROOT)).replace('\\','/')
            name=path.name.lower()
            if name=='run_manifest.json':
                record=read(path)
                if not isinstance(record,dict):
                    manifests.append(dict(path=relative,error='unreadable'))
                    continue
                simulation=record.get('simulation',{})
                manifests.append(dict(path=relative,season=record.get('season'),gw=record.get('target_gameweek'),
                    prediction_timestamp=record.get('prediction_timestamp'),simulator=simulation.get('simulator_version'),
                    simulation_mode=simulation.get('simulation_mode'),simulations=simulation.get('simulations_per_fixture'),
                    sha256=sha256(path.read_bytes()).hexdigest(),bundle_exists=(path.parent/'shadow_projection_bundle.json').is_file()))
            elif name=='shadow_projection_bundle.json':
                bundles.append(dict(path=relative,bytes=path.stat().st_size,manifest_exists=(path.parent/'run_manifest.json').is_file()))
            elif name=='archive_case.json':
                record=read(path)
                archives.append(dict(path=relative,keys=sorted(record) if isinstance(record,dict) else [],
                    companion_outcomes=[str(p.relative_to(ROOT)).replace('\\','/') for p in (path.parent/'outcomes').glob('*.json')]))
            if any(t in relative.lower() for t in ('event_live','event-live','element_summary','element-summary','merged_gw','outcome','actuals','gw_history')):
                if path.suffix in {'.json','.csv','.parquet','.jsonl'}:
                    outcome_paths.append(dict(path=relative,bytes=path.stat().st_size))
            if path.suffix in {'.csv','.parquet','.duckdb'} and not any(t in relative.lower() for t in ('packaged-root','pytest','manual_','reliability_fixes')):
                other.append(dict(path=relative,bytes=path.stat().st_size))
    result=dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(),manifests=manifests,bundles=bundles,
                archives=archives,outcome_candidates=outcome_paths,other_tables=other)
    (HERE/'inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(manifests=len(manifests),bundles=len(bundles),archive_cases=len(archives),
          outcome_candidates=len(outcome_paths),tables=len(other),simulators=dict(Counter(m.get('simulator') for m in manifests))),indent=2))
    for row in manifests:
        if row.get('simulator')=='fixture_simulator_v22_lineup_coherent_logit':
            print(json.dumps(row))
    print('Canonical directories', [p.name for p in (ROOT/'data/processed').iterdir() if p.is_dir()])
