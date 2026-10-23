"""Emit the audit backlog and verify preservation; never changes product files."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
REPORT = HERE.parent/'fpl-comprehensive-audit-2026-10.md'
text = REPORT.read_text(encoding='utf-8')
rows = [
    ('A02','Validate saved Comparator results','Comparator persistence','CONFIRMED BUG',[4,5,4,5,2,2],'FIX NOW',
     ['desktop_app/manual_scenario_store.py','desktop_app/manual_comparator.py'],
     ['tests/test_manual_scenario_store.py','tests/test_manual_comparator_ui.py']),
    ('A01','Recover FailedToStart workflows','Desktop process state','CONFIRMED BUG',[3,5,5,5,2,2],'FIX NOW',
     ['desktop_app/main_window.py'],['tests/test_desktop_decision.py','tests/test_strategic_cancellation.py']),
    ('A04','Frozen V22/policy outcome scorecard','Predictive evaluation','CONFIRMED LIMITATION',[5,4,3,5,3,1],'NEXT',
     ['scripts/run_strict_model_backtest.py','src/fpl_engine/validation/replay_archive.py'],
     ['tests/test_planning_context.py']),
    ('A03','Explicit projection approval/status','Projection provenance','CONFIRMED LIMITATION / EVIDENCE-BASED RISK',[4,4,3,5,2,3],'NEXT',
     ['src/fpl_engine/current.py','desktop_app/decision_orchestration.py','desktop_app/run_center.py'],
     ['tests/test_planning_context.py','tests/test_desktop_decision.py']),
    ('A06','Resolve timed Market Shadow sidecars','Advisory availability UI','CONFIRMED BUG',[1,3,4,5,1,1],'NEXT',
     ['desktop_app/run_center.py','desktop_app/main_window.py','src/fpl_engine/current_market_shadow.py'],
     ['tests/test_analysis_trust.py']),
    ('A05','Quantify native objective/search limits','V3 objective and recall','CONFIRMED LIMITATION',[4,2,3,5,3,3],'NEXT: measurement only',
     ['src/fpl_engine/strategy/strategic_planner_v3.py','src/fpl_engine/optimizer/core.py'],
     ['tests/test_strategic_planner_v3.py','tests/test_v3_guarded_portfolio.py']),
    ('A07','Persist Chip timing/cache attribution','Chip observability','CONFIRMED LIMITATION',[2,3,4,4,2,2],'NEXT: instrumentation only',
     ['desktop_app/chip_runner.py','desktop_app/main_window.py'],
     ['tests/test_strategic_cache_contract.py','tests/test_strategic_cancellation.py']),
    ('A08','Record reproducible desktop environment','Packaging and dependencies','CONFIRMED LIMITATION',[1,4,3,5,2,2],'NEXT',
     ['pyproject.toml','FPLControlCenter_PL.spec','desktop_app/orchestration.py'],
     ['tests/test_packaging_spec.py']),
    ('A09','Keep primary comparison metrics visible','Comparator density','CONFIRMED LIMITATION',[2,1,4,5,2,2],'LATER',
     ['desktop_app/manual_player_table.py','desktop_app/manual_comparator.py'],
     ['tests/test_manual_comparator_ui.py']),
    ('A10','Define fresh-hash versus immutable-cache boundary','Artifact integrity cache','CONFIRMED LIMITATION',[1,2,1,5,2,3],'LATER',
     ['src/fpl_engine/planning/context.py'],['tests/test_planning_context.py']),
]
items=[]
for rank,(key,title,component,classification,scores,recommendation,code,tests) in enumerate(rows,1):
    marker=f'**{key} — '
    detail=text.split(marker,1)[1].split('\n\n',1)[0]
    d,r,u,e,f,g=scores
    items.append(dict(rank=rank,id=key,title=title,component=component,classification=classification,
                      scores=dict(zip(['decision_quality','reliability','user_experience','evidence','effort','regression_risk'],scores)),
                      priority_index=2*d+2*r+u+e-f-g,recommendation=recommendation,
                      code_paths=code,related_existing_tests=tests,
                      problem_solution_benefit_complexity_risk_verification=detail))
assert len(items)==10 and len({i['id'] for i in items})==10
assert all(0<=score<=5 for item in items for score in item['scores'].values())
assert [i['priority_index'] for i in items]==sorted([i['priority_index'] for i in items],reverse=True)
backlog=dict(schema_version=1,audit_date='2026-10-23',production_changes_implemented=False,
             scoring='2D + 2R + U + E - F - G; see report E for common 0..5 rubric and explicit rank 2/3 operational tie exception',
             recommended_next_tasks=['A02','A01','A04'],items=items)
(HERE/'prioritized-backlog.json').write_text(json.dumps(backlog,indent=2),encoding='utf-8')

before=json.loads((HERE/'protected-before.json').read_text(encoding='utf-8'))['files']
changed=[]
missing=[]
for name,digest in before.items():
    path=ROOT/name
    if not path.is_file():
        missing.append(name)
    elif sha256(path.read_bytes()).hexdigest()!=digest:
        changed.append(name)
git=subprocess.run(['git.exe','status','--porcelain=v1','-uall'],cwd=ROOT,capture_output=True,check=True)
status=git.stdout.decode('utf-8')
(HERE/'git-status-after.txt').write_text(status,encoding='utf-8')
original=(HERE/'git-status-before.txt').read_text(encoding='utf-8-sig').splitlines()
allowed_prefix='docs/audits/fpl-comprehensive-audit-2026-10'
def outside(lines):
    return sorted(line for line in lines if line and not line[3:].strip('"').replace('\\','/').startswith(allowed_prefix))
unexpected_added=sorted(set(outside(status.splitlines()))-set(outside(original)))
unexpected_removed=sorted(set(outside(original))-set(outside(status.splitlines())))
result=dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(),protected_file_count=len(before),
            changed_protected_files=changed,missing_protected_files=missing,
            git_status_added_outside_audit=unexpected_added,git_status_removed_outside_audit=unexpected_removed,
            pass_preservation=not any((changed,missing,unexpected_added,unexpected_removed)))
(HERE/'preservation-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
assert result['pass_preservation'], 'Preservation differs: report the concrete changes; do not revert user work.'
links=re.findall(r'\]\(([^)]+)\)',text)
missing_links=[target for target in links if '://' not in target and not (REPORT.parent/target.split('#')[0]).exists()]
assert not missing_links, missing_links
print(json.dumps(dict(report_words=len(text.split()),local_links_checked=len(links),missing_links=missing_links)))
