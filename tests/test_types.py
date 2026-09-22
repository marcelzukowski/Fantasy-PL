"""Deterministic validation tests for CORE-005 metadata contracts."""

from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import ValidationError

from fpl_engine.types import (
    DatasetVersion,
    FeatureVersion,
    ModelVersion,
    PredictionContext,
    SourceProvenance,
)


UTC_TIME = datetime(2026, 9, 7, 12, 0, 0, 123456, tzinfo=timezone.utc)
OFFSET_TIME = datetime(
    2026, 9, 7, 14, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2))
)
NAIVE_TIME = datetime(2026, 9, 7, 12, 0, 0, 123456)
UTC_JSON = "2026-09-07T12:00:00.123456Z"

MODEL_CASES = [
    (PredictionContext, {"prediction_timestamp": UTC_TIME, "target_gameweek": 5}),
    (DatasetVersion, {"version": "dataset-001", "created_at": UTC_TIME}),
    (FeatureVersion, {"version": "v1", "created_at": UTC_TIME}),
    (ModelVersion, {"model_name": "team_strength", "version": "BT_TEAM_003", "created_at": UTC_TIME}),
    (SourceProvenance, {"source": "official_fpl_api", "retrieved_at": UTC_TIME}),
]
DATETIME_CASES = [
    (model, data, field)
    for model, data in MODEL_CASES
    for field in data
    if isinstance(data[field], datetime)
] + [
    (ModelVersion, MODEL_CASES[3][1], "training_cutoff"),
    (SourceProvenance, MODEL_CASES[4][1], "effective_at"),
    (SourceProvenance, MODEL_CASES[4][1], "known_at"),
]


@pytest.mark.parametrize("model, data", MODEL_CASES)
def test_valid_minimal_metadata(model, data):
    instance = model(**data)
    for field, value in data.items():
        assert getattr(instance, field) == value
    for field, definition in model.model_fields.items():
        if not definition.is_required():
            assert getattr(instance, field) is None


@pytest.mark.parametrize("model, data", MODEL_CASES)
def test_required_fields_have_no_implicit_defaults(model, data):
    for field, definition in model.model_fields.items():
        if definition.is_required():
            incomplete = {key: value for key, value in data.items() if key != field}
            with pytest.raises(ValidationError) as error:
                model(**incomplete)
            assert any(item["loc"] == (field,) and item["type"] == "missing" for item in error.value.errors())


@pytest.mark.parametrize("model, data, field", DATETIME_CASES)
def test_equivalent_instants_normalize_and_serialize_consistently(model, data, field):
    utc = model(**{**data, field: UTC_TIME})
    offset = model(**{**data, field: OFFSET_TIME})

    assert getattr(offset, field).tzinfo is timezone.utc
    assert getattr(offset, field) == UTC_TIME
    assert utc == offset
    assert utc.model_dump() == offset.model_dump()
    assert utc.model_dump_json() == offset.model_dump_json()
    assert json.loads(offset.model_dump_json())[field] == UTC_JSON
    assert model.model_validate_json(offset.model_dump_json()) == utc
    assert model.model_validate(offset.model_dump()) == utc


@pytest.mark.parametrize("model, data, field", DATETIME_CASES)
@pytest.mark.parametrize("invalid", [NAIVE_TIME, UTC_JSON, 1788782400])
def test_all_datetime_fields_reject_naive_values_and_python_coercion(model, data, field, invalid):
    with pytest.raises(ValidationError) as error:
        model(**{**data, field: invalid})
    assert any(item["loc"] == (field,) for item in error.value.errors())


@pytest.mark.parametrize("gameweek", [1, 38])
def test_prediction_gameweek_bounds_are_inclusive(gameweek):
    context = PredictionContext(prediction_timestamp=UTC_TIME, target_gameweek=gameweek)
    assert context.target_gameweek == gameweek


@pytest.mark.parametrize("gameweek", [0, -1, 39, "5", 5.0, True, None])
def test_prediction_gameweek_invalid_values_fail(gameweek):
    with pytest.raises(ValidationError) as error:
        PredictionContext(prediction_timestamp=UTC_TIME, target_gameweek=gameweek)
    assert error.value.errors()[0]["loc"] == ("target_gameweek",)


def test_prediction_optional_season_and_exact_serialization():
    context = PredictionContext(
        prediction_timestamp=OFFSET_TIME, target_gameweek=5, target_season="2026/27"
    )
    assert context.model_dump() == {
        "prediction_timestamp": UTC_TIME, "target_gameweek": 5, "target_season": "2026/27"
    }
    assert context.model_dump_json() == (
        '{"prediction_timestamp":"2026-09-07T12:00:00.123456Z",'
        '"target_gameweek":5,"target_season":"2026/27"}'
    )


@pytest.mark.parametrize("model", [DatasetVersion, FeatureVersion, ModelVersion])
@pytest.mark.parametrize("version", ["v1", "2026-09-07", "dataset-001", "BT_TEAM_003"])
def test_version_identifiers_do_not_require_semver(model, version):
    data = {"version": version, "created_at": UTC_TIME}
    if model is ModelVersion:
        data["model_name"] = "team_strength"
    assert model(**data).version == version


IDENTIFIER_CASES = [
    (DatasetVersion, MODEL_CASES[1][1], "version"),
    (FeatureVersion, MODEL_CASES[2][1], "version"),
    (ModelVersion, MODEL_CASES[3][1], "version"),
    (ModelVersion, MODEL_CASES[3][1], "model_name"),
    (SourceProvenance, MODEL_CASES[4][1], "source"),
    (PredictionContext, MODEL_CASES[0][1], "target_season"),
    (DatasetVersion, MODEL_CASES[1][1], "source_hash"),
    (SourceProvenance, MODEL_CASES[4][1], "source_record_id"),
    (SourceProvenance, MODEL_CASES[4][1], "source_url"),
]


@pytest.mark.parametrize("model, data, field", IDENTIFIER_CASES)
@pytest.mark.parametrize("invalid", ["", " \t\n ", 123])
def test_identifiers_reject_empty_or_non_string_values(model, data, field, invalid):
    with pytest.raises(ValidationError) as error:
        model(**{**data, field: invalid})
    assert error.value.errors()[0]["loc"] == (field,)


def test_identifier_whitespace_is_trimmed():
    version = DatasetVersion(version="  dataset-001  ", created_at=UTC_TIME)
    provenance = SourceProvenance(source="  new_provider  ", retrieved_at=UTC_TIME)
    assert version.version == "dataset-001"
    assert provenance.source == "new_provider"


def test_version_optional_descriptions_and_source_hash():
    dataset = DatasetVersion(
        version="dataset-001", created_at=UTC_TIME,
        description="Historical snapshot", source_hash="caller-supplied-hash",
    )
    features = FeatureVersion(version="v1", created_at=UTC_TIME, description="Feature contract")
    assert dataset.description == "Historical snapshot"
    assert dataset.source_hash == "caller-supplied-hash"
    assert features.description == "Feature contract"


@pytest.mark.parametrize("model", [DatasetVersion, FeatureVersion])
def test_description_is_not_coerced(model):
    with pytest.raises(ValidationError):
        model(version="v1", created_at=UTC_TIME, description=123)


@pytest.mark.parametrize("cutoff", [UTC_TIME - timedelta(days=1), OFFSET_TIME])
def test_training_cutoff_can_precede_or_equal_creation(cutoff):
    model = ModelVersion(
        model_name="team_strength", version="v1", created_at=UTC_TIME,
        training_cutoff=cutoff,
    )
    assert model.training_cutoff <= model.created_at


def test_training_cutoff_after_creation_fails():
    with pytest.raises(ValidationError, match="training_cutoff must not be after created_at"):
        ModelVersion(
            model_name="team_strength", version="v1", created_at=OFFSET_TIME,
            training_cutoff=UTC_TIME + timedelta(microseconds=1),
        )


def test_full_provenance_keeps_distinct_temporal_meanings():
    effective = UTC_TIME - timedelta(days=2)
    known = UTC_TIME - timedelta(days=1)
    provenance = SourceProvenance(
        source="manual_context", retrieved_at=OFFSET_TIME, effective_at=effective,
        known_at=known, source_record_id="record-001", source_url="https://example.com/record/001",
    )
    assert provenance.model_dump() == {
        "source": "manual_context", "retrieved_at": UTC_TIME, "effective_at": effective,
        "known_at": known, "source_record_id": "record-001", "source_url": "https://example.com/record/001",
    }
    payload = json.loads(provenance.model_dump_json())
    assert payload["retrieved_at"] == UTC_JSON
    assert payload["effective_at"] == "2026-09-05T12:00:00.123456Z"
    assert payload["known_at"] == "2026-09-06T12:00:00.123456Z"
    assert SourceProvenance.model_validate_json(provenance.model_dump_json()) == provenance


def test_missing_known_at_is_not_inferred_from_other_times():
    provenance = SourceProvenance(source="fplcache", retrieved_at=UTC_TIME, effective_at=UTC_TIME)
    assert provenance.known_at is None
    assert json.loads(provenance.model_dump_json())["known_at"] is None


def test_provenance_does_not_enforce_global_leakage_or_temporal_ordering():
    future = UTC_TIME + timedelta(days=1)
    provenance = SourceProvenance(
        source="future_provider", retrieved_at=UTC_TIME, effective_at=future, known_at=future
    )
    assert provenance.effective_at == provenance.known_at == future


@pytest.mark.parametrize("model, data", MODEL_CASES)
def test_metadata_is_frozen(model, data):
    instance = model(**data)
    before = instance.model_dump_json()
    field = next(iter(data))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(instance, field, data[field])
    with pytest.raises(ValidationError, match="frozen"):
        delattr(instance, field)
    assert instance.model_dump_json() == before


@pytest.mark.parametrize("model, data", MODEL_CASES)
def test_unknown_fields_are_rejected(model, data):
    with pytest.raises(ValidationError) as error:
        model(**data, unrecognized_field="typo")
    assert error.value.errors()[0]["type"] == "extra_forbidden"
