"""Read-only frozen-context inventory and explicitly synthetic unit contexts."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from desktop_app.decision_orchestration import planning_context_for_state
from desktop_app.decision_runner import shadow_input
from fpl_engine.planning import DecisionInput, PlanningContext, verify_projection_artifacts
from fpl_engine.planning.context import PLANNING_CONTEXT_SCHEMA
from fpl_engine.shadow import load_squad_state

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'scratch/v3_portfolio_20261022'


def synthetic_input(name,state,pool,projections,rules):
    digest=sha256(json.dumps({pid:asdict(row) for pid,row in sorted(projections.items())},sort_keys=True,default=str).encode()).hexdigest()
    context=PlanningContext(schema_version=PLANNING_CONTEXT_SCHEMA,season=state.season,gameweek=state.current_gameweek,
        deadline=None,player_ids=tuple(sorted(p.player_id for p in state.players)),
        selling_prices_tenths=tuple(sorted((p.player_id,p.selling_price) for p in state.players)),
        bank_tenths=state.bank,free_transfers=state.free_transfers,
        chips_used=tuple(sorted((k,not v) for k,v in asdict(state.chips).items() if isinstance(v,bool))),
        projection_run_id='synthetic-'+name,prediction_timestamp=state.prediction_timestamp.isoformat(),
        simulator_version='SYNTHETIC_CONTROLLED_EXPECTATIONS',model_versions=(),simulation_count=0,
        optimizer_rule_version=rules.version,scoring_rule_version=rules.version,
        manifest_sha256=sha256(('synthetic:'+name+digest).encode()).hexdigest(),
        artifact_hashes=(('synthetic_projection_values',digest),),fpl_sync_timestamp=None,
        source_state_timestamp=None,data_freshness=())
    return DecisionInput.create(planning_context=context,state=state,player_pool=tuple(pool.values()),
        projections=projections,pipeline={'synthetic':True},warnings=(),rules=rules,freshness=None,
        bundle_identity=context.projection_run_id)


def load_frozen(analysis_path):
    analysis=json.loads(Path(analysis_path).read_text(encoding='utf-8'))
    desktop=analysis['display_state']
    bundle_path=ROOT/'data/processed/predictions/2026-27'/analysis['projection_run_id']/'shadow_projection_bundle.json'
    bundle=json.loads(bundle_path.read_text(encoding='utf-8'))
    manifest=json.loads((bundle_path.parent/'run_manifest.json').read_text(encoding='utf-8'))
    verify_projection_artifacts(bundle_path,manifest,require_hashes=True)
    context=planning_context_for_state(ROOT,desktop,bundle_path,require_canonical_path=False)
    if context.context_id!=analysis['context_id']:
        raise ValueError('Saved PlanningContext is not reproducible')
    directory=OUT/'inputs'
    directory.mkdir(parents=True,exist_ok=True)
    request=directory/(context.context_id+'.json')
    request.write_text(json.dumps(shadow_input(desktop,bundle)),encoding='utf-8')
    state,pool,projections,pipeline,warnings,rules,freshness=load_squad_state(request,project_root=ROOT,prediction_bundle_path=bundle_path)
    return DecisionInput.create(planning_context=context,state=state,player_pool=pool,projections=projections,
        pipeline=pipeline,warnings=warnings,rules=rules,freshness=freshness,bundle_identity=context.projection_run_id)


def inventory():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    loaded={}
    for path in sorted((ROOT/'data/processed/desktop_analyses/2026-27').glob('*.json')):
        value=json.loads(path.read_text(encoding='utf-8'))
        context_id=value.get('context_id')
        if context_id is None:
            rows.append({'analysis':path.name,'status':'EXCLUDED_LEGACY_NO_CONTEXT'})
            continue
        if context_id in loaded:
            rows.append({'analysis':path.name,'context_id':context_id,'status':'DUPLICATE_CONTEXT'})
            continue
        try:
            shared=load_frozen(path)
            loaded[context_id]=(path,shared)
            rows.append({'analysis':path.name,'context_id':context_id,'status':'VERIFIED',
                'gw':shared.state.current_gameweek,'ft':shared.state.free_transfers,'bank':shared.state.bank,
                'run':shared.bundle_identity})
        except Exception as exc:
            rows.append({'analysis':path.name,'context_id':context_id,'status':'EXCLUDED',
                         'reason':type(exc).__name__+': '+str(exc)})
    (OUT/'frozen_inventory.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return loaded
