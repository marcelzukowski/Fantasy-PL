"""Read-only provenance/UI discovery probes on existing artifacts."""
import json
from pathlib import Path
from time import perf_counter
from desktop_app.run_center import discover_projection_runs
from desktop_app.decision_orchestration import validate_decision_bundle

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

rows = []
for path in sorted((ROOT/'data/processed/predictions/2026-27').glob('*/run_manifest.json')):
    manifest = read(path)
    try:
        validate_decision_bundle(ROOT, path.parent/'shadow_projection_bundle.json',
                                 season=manifest['season'], gameweek=manifest['target_gameweek'])
        accepted = True
        error = None
    except Exception as exc:
        accepted = False
        error = str(exc)
    simulation = manifest.get('simulation', {})
    rows.append(dict(run_id=path.parent.name, gameweek=manifest['target_gameweek'],
                     mode=simulation.get('simulation_mode'), simulations=simulation.get('simulations_per_fixture'),
                     accepted=accepted, error=error))
timings = []
for _ in range(3):
    start = perf_counter()
    runs = discover_projection_runs(ROOT, season='2026/27', gameweek=8)
    timings.append(perf_counter()-start)
latest = runs[0]
sidecars = sorted((ROOT/'data/processed/market_shadow/2026-27'/latest.run_id).glob('*.json'))
market = read(sidecars[-1]) if sidecars else {}
coverage = market.get('coverage', {})
result = dict(validated_bundles=rows, discovery_seconds=timings, discovered_gw8=len(runs),
              latest_run=latest.run_id, latest_label=latest.label, latest_detail=latest.detail,
              market_ui_status=latest.market_shadow_status,
              market_sidecar_status=market.get('status'),
              market_sidecar_path=str(sidecars[-1].relative_to(ROOT)) if sidecars else None,
              market_sidecar_prediction_timestamp=market.get('prediction_timestamp'),
              market_sidecar_snapshot_timestamp=market.get('market_snapshot_timestamp'),
              projection_timestamp=latest.timestamp.isoformat(),
              market_coverage={k:v for k,v in coverage.items() if not isinstance(v,(dict,list))},
              production_influence=market.get('production_influence'))
(HERE/'lineage-probes.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
