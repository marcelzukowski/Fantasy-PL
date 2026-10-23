"""Assertions for the historical demonstration; no provider or model execution."""
from hashlib import sha256
import json
from pathlib import Path

root = Path.cwd()
here = Path(__file__).resolve().parent
report = json.loads((here / 'verified/report.json').read_text(encoding='utf-8'))
previous = json.loads((here.parent / 'v22-predictive-validation-2026-10/results.json').read_text())
assert report['selected_gameweeks'] == [6, 7]
assert len(report['rows']) == len({(r['gameweek'], r['player_id']) for r in report['rows']}) == 1334
assert len({r['player_id'] for r in report['rows']}) == 667
for key in ('mae', 'rmse', 'bias'):
    assert abs(report['scorecard']['all_players'][key] - previous['points'][key]) < 1e-12
    assert abs(report['scorecard']['minutes'][key] - previous['minutes'][key]) < 1e-12
locks = [json.loads(line) for line in (here / 'primary.jsonl').read_text().splitlines()]
assert len(locks) == len({(r['season'], r['gameweek']) for r in locks}) == 2
assert len(report['primary_archives']) == 2
for name, digest in report['input_sha256'].items():
    path = Path(name) if Path(name).is_absolute() else root / name
    assert sha256(path.read_bytes()).hexdigest() == digest, name
pairs = report['scorecard']['saved_v3_vs_hold_paired']['by_gameweek']
assert pairs['6']['v3_minus_hold_points'] == 10
assert pairs['7']['v3_minus_hold_points'] == -2
result = {'historical_metrics_reproduced': 'PASS', 'unique_gw_and_rows': 'PASS',
          'input_hashes_unchanged': 'PASS', 'input_files_checked': len(report['input_sha256']),
          'same_primary_ledger_after_two_reports': 'PASS', 'saved_v3_hold_scores': 'PASS'}
(here / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
