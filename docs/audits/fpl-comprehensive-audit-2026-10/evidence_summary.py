"""Summarize existing telemetry and inspect existing EXEs without launching them."""
from hashlib import sha256
import json
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def numeric_timings(value, prefix=''):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = prefix+'.'+key
            if isinstance(child,(dict,list)):
                result.update(numeric_timings(child,name))
            elif isinstance(child,(float,int)) and any(s in key.lower() for s in ('seconds','duration','elapsed','total','cache_hit')):
                result[name] = child
    elif isinstance(value,list):
        for index,child in enumerate(value):
            result.update(numeric_timings(child,prefix+f'[{index}]'))
    return result
chips = []
for path in sorted((ROOT/'data/processed/desktop_chips').rglob('*.json'))[-5:]:
    report = read(path)
    chips.append(dict(path=str(path.relative_to(ROOT)), status=report.get('status'),
                      created_at=report.get('created_at'), completed_at=report.get('completed_at'),
                      context_id=report.get('context_id'), projection_run_id=report.get('projection_run_id'),
                      timing=numeric_timings(report)))
replays = {}
for name in ('integrated_replay.json','integrated_replay_r2.json'):
    path = ROOT/'scratch/decision/captain068g'/name
    report = read(path)
    replays[name] = {k:v for k,v in report.items() if not isinstance(v,(list,dict))}
    replays[name]['cases'] = report.get('cases')
packages = []
for path in (ROOT/'FPLControlCenter_PL.exe', ROOT/'dist/FPLControlCenter_PL.exe'):
    archive = CArchiveReader(str(path))
    pyz_name = next(name for name in archive.toc if name.endswith('.pyz'))
    pyz = archive.open_embedded_archive(pyz_name)
    names = list(pyz.toc)
    scientific = [n for n in names if n.split('.')[0] in {'numpy','scipy','pandas','sklearn','matplotlib','pyarrow'}]
    diagnostics = [n for n in names if any(t in n.lower() for t in ('cpsat','guarded_portfolio','challenger','ortools'))]
    packages.append(dict(path=str(path.relative_to(ROOT)),bytes=path.stat().st_size,
                         sha256=sha256(path.read_bytes()).hexdigest(),
                         scientific_modules=scientific,diagnostic_modules=diagnostics,
                         player_risk_module='fpl_engine.planning.player_availability_risk' in names,
                         minutes_history_module='fpl_engine.planning.player_minutes_history' in names))
result = dict(chips=chips,replays=replays,packages=packages)
(HERE/'evidence-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
