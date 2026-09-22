from datetime import datetime,timedelta,timezone
import pytest
from fpl_engine.validation.leakage import *
N=datetime(2026,1,1,12,tzinfo=timezone.utc)
def test_known_equality_valid_and_future_record_rejected():
 assert_information_known(known_at=N,prediction_timestamp=N,entity='price',source='fpl')
 with pytest.raises(FutureInformationError):assert_information_known(known_at=N+timedelta(seconds=1),prediction_timestamp=N,entity='injury',source='fpl')
def test_snapshots_require_strictly_before_boundary():
 assert_snapshot_before(snapshot_timestamp=N-timedelta(microseconds=1),prediction_timestamp=N)
 with pytest.raises(FutureSnapshotError):assert_snapshot_before(snapshot_timestamp=N,prediction_timestamp=N)
def test_future_context_mapping_target_and_aggregate_are_rejected():
 with pytest.raises(FutureInformationError):assert_mapping_active(effective_from=N+timedelta(days=1),effective_to=None,prediction_timestamp=N)
 with pytest.raises(TargetFixtureLeakageError):assert_feature_record(known_at=N,effective_at=N,prediction_timestamp=N,target_fixture_id='fix',record_fixture_id='fix')
 with pytest.raises(ForbiddenFeatureError):assert_season_to_date(latest_fixture_kickoff=N,prediction_timestamp=N)
def test_xp_unsafe_odds_and_valid_historical_evidence():
 with pytest.raises(ForbiddenFeatureError):assert_allowed_source_feature(source='vaastav',field='xP',known_at=N-timedelta(days=1),prediction_timestamp=N)
 with pytest.raises(ForbiddenFeatureError):assert_allowed_source_feature(source='football_data',field='B365 odds',known_at=None,prediction_timestamp=N)
 assert_allowed_source_feature(source='football_data',field='B365 odds',known_at=N,prediction_timestamp=N)
