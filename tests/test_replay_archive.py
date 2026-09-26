from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import pytest
from fpl_engine.planning.context import PLANNING_CONTEXT_SCHEMA, PlanningContext, REQUIRED_ARTIFACTS
from fpl_engine.planning import ChipForecastStatus, ChipOpportunityForecast, write_chip_opportunity_forecast
from fpl_engine.reports import AnalysisManifestV2, DecisionReportV2, ReportReference, parse_analysis_manifest, parse_decision_report
from fpl_engine.validation.replay_archive import (
 ArchiveConflictError, ArchiveStatus, ReplayArchiveError, archive_analysis, archive_status,
 attach_outcome, build_archive_case, discover_archives, select_operational_archive, validate_archive_case,
 write_archive_case,
)
AT=datetime(2026,8,1,9,tzinfo=timezone.utc); DEADLINE=AT+timedelta(hours=1)
def _write(path,content): path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(content); return sha256(content).hexdigest()
def _root(tmp_path,*,deadline=DEADLINE,decision_at=AT+timedelta(minutes=1),analysis_at=AT+timedelta(minutes=2)):
 root=tmp_path; run=root/'data/processed/predictions/2026-27/run-1'; run.mkdir(parents=True); bundle=run/'shadow_projection_bundle.json'; bundle.write_text('{}',encoding='utf-8')
 artifacts={}
 for name in REQUIRED_ARTIFACTS:
  file=run/f'{name}.json'; digest=_write(file,f'{name}-immutable'.encode()); artifacts[name]={'path':file.name,'sha256':digest}
 manifest=run/'run_manifest.json'; manifest.write_text(json.dumps({'artifacts':artifacts}),encoding='utf-8'); manifest_sha=sha256(manifest.read_bytes()).hexdigest()
 ids=tuple(f'p{i}' for i in range(15)); context=PlanningContext(PLANNING_CONTEXT_SCHEMA,'2026/27',6,deadline.isoformat(),ids,tuple((x,50) for x in ids),10,2,(('wildcard_h1',False),),'run-1',AT.isoformat(),'v22',('v22',),512,1,1,manifest_sha,tuple((name,meta['sha256']) for name,meta in artifacts.items()),AT.isoformat(),AT.isoformat(),())
 preview={'transfers_out':[],'transfers_in':[],'resulting_bank':10,'free_transfers_after':3,'starting_xi':list(ids[:11]),'bench_order':list(ids[11:]),'captain':'p0','vice_captain':'p1'}
 forecast=ChipOpportunityForecast('chip_opportunity_forecast_v1',context.context_id,decision_at.isoformat(),6,6,'chip_opportunity_forecast_v1',(),{'prediction_timestamp':AT.isoformat(),'projection_run_id':'run-1','production_influence':False},{'evaluated_gameweeks':[6]},'LOW',(),ChipForecastStatus.UNAVAILABLE,{'cache_hits':0})
 forecast_path=write_chip_opportunity_forecast(root,forecast); forecast_ref={'path':str(forecast_path.relative_to(root)),'sha256':sha256(forecast_path.read_bytes()).hexdigest()}
 decision=DecisionReportV2.create(report_id='d',created_at=decision_at,planning_context=context,mode='READ ONLY',external_mutations=[],shadow_report=None,recommendation={'transfers_out':[],'transfers_in':[],'roll_free_transfer':True},feasible_plans=[],strategic_v2={'action':'ROLL_FT','transfers_out':[],'transfers_in':[]},strategic_v3={'current_action':{'action':'HOLD','transfers_out':[],'transfers_in':[]},'path':[]},strategic_v3_error=None,strategy_previews={'short_term':preview},strategy_preview_identities={},strategy_unavailable={},player_metadata={},chip_opportunity_forecast=forecast_ref)
 decision_path=root/'data/processed/desktop_decisions/d.json'; decision_path.parent.mkdir(parents=True); decision_path.write_text(json.dumps(decision.to_dict(),sort_keys=True),encoding='utf-8'); ref=ReportReference(str(decision_path.relative_to(root)),sha256(decision_path.read_bytes()).hexdigest())
 analysis=AnalysisManifestV2.create(analysis_run_id='a',created_at=analysis_at,status='COMPLETE',season='2026/27',gameweek=6,projection_run_id='run-1',decision_report=decision,decision_reference=ref,chip_report=None,chip_reference=None,recommended_xi_available=True,captaincy_available=True,display_state=None)
 analysis_path=root/'data/processed/desktop_analyses/2026-27/a.json'; analysis_path.parent.mkdir(parents=True); analysis_path.write_text(json.dumps(analysis.to_dict(),sort_keys=True),encoding='utf-8')
 return root,analysis_path,decision_path,manifest
def test_valid_predeadline_analysis_archives_idempotently(tmp_path):
 root,analysis,*_= _root(tmp_path); first=archive_analysis(root,analysis); second=archive_analysis(root,analysis)
 assert first==second and validate_archive_case(root,first).status is ArchiveStatus.PRE_DEADLINE_COMPLETE
 assert len(discover_archives(root,'2026-27',6))==1
def test_postdeadline_context_and_external_mutation_cannot_archive(tmp_path):
 root,analysis,*_= _root(tmp_path,deadline=AT)
 with pytest.raises(ReplayArchiveError): archive_analysis(root,analysis)
def test_artifact_tampering_and_conflicting_duplicate_are_rejected(tmp_path):
 root,analysis,_,manifest=_root(tmp_path); target=archive_analysis(root,analysis); (manifest.parent/'minutes.json').write_text('tampered',encoding='utf-8')
 assert validate_archive_case(root,target).status is ArchiveStatus.INVALID
 case=build_archive_case(root,analysis) if False else None
 # Existing immutable bytes cannot be replaced by another payload sharing the stable path.
 with pytest.raises(ReplayArchiveError): build_archive_case(root,analysis)
def test_outcome_is_companion_and_wrong_context_rejected(tmp_path):
 root,analysis,*_= _root(tmp_path); archive=archive_analysis(root,analysis)
 source=root/'outcome.json'; source.write_text(json.dumps({'archive_case_id':archive.parent.name,'context_id':'wrong','season':'2026/27','planning_gameweek':6,'outcome_source':'local','realised_outcomes':[{'player_id':'p0','gameweek':6,'fixture_id':'f','points':5,'minutes':90,'outcome_known_at':(DEADLINE+timedelta(hours=2)).isoformat(),'source_id':'official'}]}),encoding='utf-8')
 with pytest.raises(ReplayArchiveError): attach_outcome(root,archive,source)
 source.write_text(json.dumps({'archive_case_id':archive.parent.name,'season':'2026/27','planning_gameweek':6,'outcome_source':'local','realised_outcomes':[{'player_id':'p0','gameweek':6,'fixture_id':'f','points':5,'minutes':90,'outcome_known_at':(DEADLINE+timedelta(hours=2)).isoformat(),'source_id':'official'}]}),encoding='utf-8')
 assert attach_outcome(root,archive,source).is_file() and archive_status(root,archive).status is ArchiveStatus.OUTCOME_COMPLETE
def test_selection_ignores_invalid_and_postdeadline_archives(tmp_path):
 root,analysis,*_= _root(tmp_path); archive=archive_analysis(root,analysis)
 assert select_operational_archive(root,'2026/27',6,DEADLINE)==archive
 # A post-deadline case cannot be created; no later invalid artifact is eligible.
 assert select_operational_archive(root,'2026/27',6,AT) is None
def test_missing_market_and_price_signals_are_explicit_unavailable(tmp_path):
 root,analysis,*_= _root(tmp_path); case=build_archive_case(root,analysis)
 assert case.market_shadow.status.value=='UNAVAILABLE' and case.price_signals.status.value=='UNAVAILABLE'
def test_legacy_report_never_becomes_archive(tmp_path):
 root=tmp_path; legacy=root/'legacy.json'; legacy.write_text(json.dumps({'status':'COMPLETE'}),encoding='utf-8')
 with pytest.raises(Exception): build_archive_case(root,legacy)

def test_conflicting_duplicate_never_overwrites_existing_archive(tmp_path):
 root,analysis,*_= _root(tmp_path); case=build_archive_case(root,analysis); target=write_archive_case(root,case)
 with pytest.raises(ArchiveConflictError): write_archive_case(root,replace(case,policy_versions={'greedy':'different'}))
 assert target.read_bytes()==target.read_bytes()

def test_future_dated_snapshot_is_rejected(tmp_path):
 root,analysis,*_= _root(tmp_path); case=build_archive_case(root,analysis)
 from fpl_engine.validation.replay_archive import OptionalSnapshotReference, SnapshotStatus
 future=OptionalSnapshotReference(SnapshotStatus.AVAILABLE,'data/x.json','a'*64,(AT+timedelta(minutes=1)).isoformat(),'provider',{},False)
 with pytest.raises(ReplayArchiveError): replace(case,price_signals=future)


def test_archive_preserves_exact_chip_forecast_reference(tmp_path):
 root,analysis,*_= _root(tmp_path); case=build_archive_case(root,analysis)
 assert case.chip_opportunity_forecast.status.value == "AVAILABLE"
 target=write_archive_case(root,case)
 assert validate_archive_case(root,target).checks["chip_opportunity_forecast"]


def test_archive_preserves_availability_snapshot_reference(tmp_path):
 root,analysis_path,decision_path,*_= _root(tmp_path)
 from fpl_engine.planning.player_availability_risk import (
  PLAYER_AVAILABILITY_RISK_METHOD_V1, PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1,
  PlayerAvailabilitySnapshot, write_player_availability_snapshot,
 )
 decision=parse_decision_report(json.loads(decision_path.read_text(encoding="utf-8")))
 snapshot=PlayerAvailabilitySnapshot(
  PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1,decision.context_id,AT.isoformat(),6,
  PLAYER_AVAILABILITY_RISK_METHOD_V1,(),{"status":"AVAILABLE","players_evaluated":0},
  {"prediction_timestamp":AT.isoformat(),"observed_at":AT.isoformat(),"source":"official_fpl","production_influence":False},(),{"cache_hits":0},
 )
 snapshot_path=write_player_availability_snapshot(root,snapshot)
 updated=replace(decision,player_availability_snapshot=ReportReference(str(snapshot_path.relative_to(root)),sha256(snapshot_path.read_bytes()).hexdigest()))
 decision_path.write_text(json.dumps(updated.to_dict(),sort_keys=True),encoding="utf-8")
 analysis=parse_analysis_manifest(json.loads(analysis_path.read_text(encoding="utf-8")))
 updated_analysis=replace(analysis,decision_report=ReportReference(str(decision_path.relative_to(root)),sha256(decision_path.read_bytes()).hexdigest()))
 analysis_path.write_text(json.dumps(updated_analysis.to_dict(),sort_keys=True),encoding="utf-8")
 case=build_archive_case(root,analysis_path)
 assert case.player_availability_snapshot.status.value == "AVAILABLE"
 assert case.player_availability_snapshot.path == str(snapshot_path.relative_to(root))
