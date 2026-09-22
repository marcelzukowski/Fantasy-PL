"""Fail-fast point-in-time assertions for DATA-015."""
from datetime import datetime, timezone
class LeakageError(ValueError): pass
class FutureInformationError(LeakageError): pass
class FutureSnapshotError(LeakageError): pass
class ForbiddenFeatureError(LeakageError): pass
class TargetFixtureLeakageError(LeakageError): pass
def _utc(value,name):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None: raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)
def assert_information_known(*,known_at:datetime,prediction_timestamp:datetime,entity="record",source="unknown"):
    known,prediction=_utc(known_at,"known_at"),_utc(prediction_timestamp,"prediction_timestamp")
    if known>prediction: raise FutureInformationError(f"{entity} from {source} known_at {known.isoformat()} is after prediction_timestamp {prediction.isoformat()}")
def assert_snapshot_before(*,snapshot_timestamp:datetime,prediction_timestamp:datetime,source="snapshot"):
    snapshot,prediction=_utc(snapshot_timestamp,"snapshot_timestamp"),_utc(prediction_timestamp,"prediction_timestamp")
    if snapshot>=prediction: raise FutureSnapshotError(f"{source} snapshot_timestamp {snapshot.isoformat()} must be strictly before prediction_timestamp {prediction.isoformat()}")
def assert_feature_record(*,known_at:datetime,effective_at:datetime,prediction_timestamp:datetime,target_fixture_id=None,record_fixture_id=None,source="unknown",feature_name="feature"):
    assert_information_known(known_at=known_at,prediction_timestamp=prediction_timestamp,entity=feature_name,source=source)
    effective,prediction=_utc(effective_at,"effective_at"),_utc(prediction_timestamp,"prediction_timestamp")
    if effective>prediction: raise FutureInformationError(f"{feature_name} effective_at is after prediction_timestamp")
    if target_fixture_id is not None and target_fixture_id==record_fixture_id: raise TargetFixtureLeakageError(f"{feature_name} includes target fixture {target_fixture_id}")
def assert_mapping_active(*,effective_from:datetime,effective_to:datetime|None,prediction_timestamp:datetime,provider="provider"):
    prediction=_utc(prediction_timestamp,"prediction_timestamp"); start=_utc(effective_from,"effective_from")
    if start>prediction: raise FutureInformationError(f"future {provider} mapping cannot resolve historical data")
    if effective_to is not None and _utc(effective_to,"effective_to")<start: raise LeakageError("mapping effective_to precedes effective_from")
def assert_allowed_source_feature(*,source:str,field:str,known_at:datetime|None,prediction_timestamp:datetime):
    if source=="vaastav" and field=="xP": raise ForbiddenFeatureError("Vaastav historical xP is forbidden by default")
    if source=="football_data" and "odds" in field.lower() and known_at is None: raise ForbiddenFeatureError("football-data odds require evidenced pre-prediction availability")
    if known_at is not None: assert_information_known(known_at=known_at,prediction_timestamp=prediction_timestamp,entity=field,source=source)
def assert_season_to_date(*,latest_fixture_kickoff:datetime,prediction_timestamp:datetime):
    if _utc(latest_fixture_kickoff,"latest_fixture_kickoff")>=_utc(prediction_timestamp,"prediction_timestamp"): raise ForbiddenFeatureError("season aggregate contains target/future fixture")
