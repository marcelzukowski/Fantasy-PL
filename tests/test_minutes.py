from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.features.minutes_dataset import MinutesObservation, build_minutes_training_rows
from fpl_engine.models.minutes import (
    MINUTE_BUCKETS,
    CalibrationPoint,
    MinutesContext,
    MinutesFeatureSignal,
    MinutesModel,
    MinutesCalibrationPoint,
    fit_minutes_calibration,
    load_minutes_calibration,
    save_minutes_calibration,
    fit_probability_calibrator,
    walk_forward_minutes,
)
from fpl_engine.models.minutes.baselines import (
    empirical_hurdle,
    previous_match_minutes,
    rolling_5_minutes,
    rolling_5_start_rate,
)
from fpl_engine.validation.leakage import (
    FutureInformationError,
    FutureSnapshotError,
    TargetFixtureLeakageError,
)


BASE = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)


def observation(index, minutes, started, *, player="p1", known_delay=2):
    kickoff = BASE + timedelta(days=index * 7)
    return MinutesObservation(
        player, f"f{index}", kickoff, kickoff + timedelta(hours=known_delay), minutes, started
    )


def context(index, **changes):
    values = dict(
        player_id="p1",
        fixture_id=f"f{index}",
        prediction_timestamp=BASE + timedelta(days=index * 7) - timedelta(hours=1),
        availability_probability=1.0,
        availability_known_at=BASE + timedelta(days=index * 7) - timedelta(hours=2),
        availability_confidence=0.9,
    )
    values.update(changes)
    return MinutesContext(**values)


def assert_coherent(prediction):
    assert tuple(prediction.minute_bucket_distribution) == MINUTE_BUCKETS
    assert sum(prediction.minute_bucket_distribution.values()) == pytest.approx(1)
    assert sum(prediction.minute_distribution) == pytest.approx(1)
    assert prediction.expected_minutes == pytest.approx(
        sum(minute * probability for minute, probability in enumerate(prediction.minute_distribution))
    )
    assert 0 <= prediction.p90 <= prediction.p75 <= prediction.p60 <= prediction.p_appearance <= 1
    assert prediction.p_zero + prediction.p_appearance == pytest.approx(1)
    assert prediction.p_start + prediction.p_bench_appearance == pytest.approx(prediction.p_appearance)
    assert 0 <= prediction.prediction_confidence <= 1


def test_nailed_starter_has_high_start_and_minutes_but_not_extreme_confidence():
    history = [observation(i, minute, True) for i, minute in enumerate([90, 88, 90, 82, 90, 86, 90, 84])]
    prediction = MinutesModel().predict(history, context(9, position="DEF"))
    assert prediction.p_start > 0.65
    assert prediction.expected_minutes > 60
    assert prediction.p90 < 1
    assert_coherent(prediction)


def test_regular_bench_player_and_substitute_appearance_are_explicit():
    history = [observation(i, minute, False) for i, minute in enumerate([0, 14, 0, 22, 8, 0, 17])]
    prediction = MinutesModel().predict(history, context(8))
    assert prediction.p_bench_appearance > prediction.p_start
    assert prediction.minute_bucket_distribution["1-29"] > prediction.minute_bucket_distribution["60-69"]
    assert prediction.expected_minutes < 35
    assert_coherent(prediction)


def test_injured_or_suspended_player_is_deterministically_unavailable():
    history = [observation(i, 90, True) for i in range(6)]
    injured = MinutesModel().predict(history, context(7, definitely_unavailable=True))
    suspended = MinutesModel().predict(history, context(7, confirmed_suspension=True))
    for prediction in (injured, suspended):
        assert prediction.p_zero == 1
        assert prediction.p_start == prediction.expected_minutes == prediction.p60 == 0
        assert_coherent(prediction)


def test_uncertain_injury_return_lowers_minutes_and_increases_uncertainty():
    history = [observation(i, 88, True) for i in range(8)]
    ordinary = MinutesModel().predict(history, context(9))
    returning = MinutesModel().predict(
        history,
        context(
            9,
            availability_probability=0.75,
            availability_confidence=0.45,
            returning_from_injury=True,
        ),
    )
    assert returning.expected_minutes < ordinary.expected_minutes
    assert returning.minutes_uncertainty > ordinary.minutes_uncertainty
    assert returning.early_substitution_risk >= 0.55


def test_rotation_and_early_substitution_risks_affect_the_expected_shape():
    history = [observation(i, minute, True) for i, minute in enumerate([72, 68, 75, 70, 74, 69])]
    normal = MinutesModel().predict(history, context(7))
    risky = MinutesModel().predict(
        history, context(7, rotation_risk=0.9, early_substitution_risk=0.9, fixture_congestion=1.0)
    )
    assert risky.p_start < normal.p_start
    assert risky.expected_minutes < normal.expected_minutes
    assert risky.rotation_risk >= 0.9 and risky.early_substitution_risk >= 0.9


def test_sparse_player_uses_priors_and_marks_missing_availability_unknown():
    prediction = MinutesModel().predict([], MinutesContext("new", "future", BASE))
    assert 0 < prediction.p_start < prediction.p_appearance < 1
    assert prediction.availability_confidence == 0
    assert prediction.minutes_uncertainty > 0.5
    assert_coherent(prediction)


def test_predictions_are_deterministic():
    history = [observation(i, minute, minute > 30) for i, minute in enumerate([0, 20, 67, 81, 90])]
    model = MinutesModel()
    assert model.predict(history, context(6)) == model.predict(history, context(6))


def test_future_history_and_target_match_outcomes_are_rejected():
    with pytest.raises(FutureInformationError):
        MinutesModel().predict([observation(1, 90, True, known_delay=200)], context(2))
    target = observation(2, 90, True)
    with pytest.raises(TargetFixtureLeakageError):
        MinutesModel().predict([target], context(2))


def test_future_lineup_availability_and_snapshot_boundary_are_rejected():
    target_context = context(3)
    future_lineup = MinutesFeatureSignal(
        "lineup", True, target_context.prediction_timestamp + timedelta(minutes=1),
        target_context.prediction_timestamp, "api_football", "f2"
    )
    with pytest.raises(FutureInformationError):
        MinutesModel().predict([], context(3, signals=(future_lineup,)))
    target_lineup = MinutesFeatureSignal(
        "lineup", True, target_context.prediction_timestamp,
        target_context.prediction_timestamp, "api_football", "f3"
    )
    with pytest.raises(TargetFixtureLeakageError):
        MinutesModel().predict([], context(3, signals=(target_lineup,)))
    equal_snapshot = MinutesFeatureSignal(
        "status", "a", target_context.prediction_timestamp,
        target_context.prediction_timestamp, "fplcache", source_snapshot_timestamp=target_context.prediction_timestamp
    )
    with pytest.raises(FutureSnapshotError):
        MinutesModel().predict([], context(3, signals=(equal_snapshot,)))


def test_training_dataset_is_expanding_and_never_uses_target_match():
    rows = build_minutes_training_rows([observation(0, 10, False), observation(1, 70, True), observation(2, 90, True)])
    assert [row.history_count for row in rows] == [0, 1, 2]
    assert rows[1].previous_match_minutes == 10
    assert rows[2].rolling_5_start_rate == 0.5
    assert all(row.prediction_timestamp < BASE + timedelta(days=index * 7) for index, row in enumerate(rows))


def test_all_baselines_are_bounded_and_use_only_prior_results():
    history = [observation(i, minute, minute >= 60) for i, minute in enumerate([0, 18, 61, 75, 90])]
    functions = (previous_match_minutes, rolling_5_minutes, rolling_5_start_rate, empirical_hurdle)
    predictions = [function(history, "p1", "f6", context(6).prediction_timestamp) for function in functions]
    assert len({prediction.model_id for prediction in predictions}) == 4
    assert all(0 <= prediction.expected_minutes <= 90 for prediction in predictions)
    assert all(0 <= prediction.p_start <= 1 and 0 <= prediction.p_60_plus <= 1 for prediction in predictions)


def test_calibration_is_time_frozen_and_preserves_probability_bounds():
    points = [
        CalibrationPoint(0.2, False, BASE),
        CalibrationPoint(0.4, False, BASE + timedelta(hours=1)),
        CalibrationPoint(0.7, True, BASE + timedelta(hours=2)),
        CalibrationPoint(0.9, True, BASE + timedelta(hours=3)),
    ]
    artifact = fit_probability_calibrator(points, training_cutoff=BASE + timedelta(hours=3), method="platt")
    assert 0 <= artifact.predict(0.6, prediction_timestamp=BASE + timedelta(days=1)) <= 1
    with pytest.raises(FutureInformationError):
        artifact.predict(0.6, prediction_timestamp=BASE + timedelta(hours=2))
    with pytest.raises(FutureInformationError):
        fit_probability_calibrator(points, training_cutoff=BASE + timedelta(hours=2), method="isotonic")


def test_complete_calibration_artifact_keeps_mixture_coherent(tmp_path):
    history = [observation(i, minute, minute >= 60) for i, minute in enumerate([0, 18, 65, 78, 90, 72])]
    raw = MinutesModel().predict(history, context(7))
    calibration_rows = [
        MinutesCalibrationPoint(0.2, 0.1, 0.1, 0.05, 0.02, False, False, 0, BASE),
        MinutesCalibrationPoint(0.5, 0.3, 0.2, 0.1, 0.05, True, False, 18, BASE + timedelta(hours=1)),
        MinutesCalibrationPoint(0.8, 0.7, 0.65, 0.5, 0.2, True, True, 78, BASE + timedelta(hours=2)),
        MinutesCalibrationPoint(0.95, 0.9, 0.9, 0.8, 0.6, True, True, 90, BASE + timedelta(hours=3)),
    ]
    artifact = fit_minutes_calibration(
        calibration_rows, training_cutoff=BASE + timedelta(hours=3), method="isotonic"
    )
    artifact_path = tmp_path / "minutes-calibration.json"
    save_minutes_calibration(artifact, artifact_path)
    restored = load_minutes_calibration(artifact_path)
    assert restored == artifact
    calibrated = MinutesModel().predict(history, context(7), calibration=restored)
    assert calibrated != raw
    assert_coherent(calibrated)


def test_walk_forward_is_chronological_deterministic_and_reports_champion():
    pattern = [90, 86, 0, 72, 18, 90, 78, 0, 65, 88, 15, 90, 74, 0, 82, 90, 20, 76]
    rows = [observation(i, minute, minute >= 60) for i, minute in enumerate(pattern)]
    first = walk_forward_minutes(rows, minimum_history=3, minimum_calibration_points=5)
    second = walk_forward_minutes(rows, minimum_history=3, minimum_calibration_points=5)
    assert first == second
    assert first.prediction_fixture_order == tuple(f"f{i}" for i in range(3, len(rows)))
    assert {item.model_id for item in first.candidates} >= {
        "previous_match_minutes_v1", "rolling_5_minutes_v1", "empirical_hurdle_v1", "minutes_hurdle_v1"
    }
    assert first.champion_model_id in {item.model_id for item in first.candidates}
    assert all(item.fixtures > 0 and item.mae_minutes >= 0 and item.brier_start >= 0 for item in first.candidates)
