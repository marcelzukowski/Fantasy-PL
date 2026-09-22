"""Frozen canonical metadata contracts, independent of configuration and logging."""

from datetime import datetime, timezone
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


__all__ = [
    "PredictionContext",
    "DatasetVersion",
    "FeatureVersion",
    "ModelVersion",
    "SourceProvenance",
]


def _to_utc(value: datetime) -> datetime:
    """Normalize an already validated aware datetime without changing its instant."""
    return value.astimezone(timezone.utc)


_UTCDateTime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
_Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _FrozenMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class PredictionContext(_FrozenMetadata):
    """Explicit prediction time and target GW, optionally scoped by a season label."""

    prediction_timestamp: _UTCDateTime
    target_gameweek: int = Field(ge=1, le=38)
    target_season: _Identifier | None = None


class _VersionMetadata(_FrozenMetadata):
    version: _Identifier
    created_at: _UTCDateTime


class DatasetVersion(_VersionMetadata):
    """Caller-supplied dataset identity; no hash calculation or registry behavior."""

    description: str | None = None
    source_hash: _Identifier | None = None


class FeatureVersion(_VersionMetadata):
    """Identity of a feature-generation contract."""

    description: str | None = None


class ModelVersion(_VersionMetadata):
    """Identity of an implementation/artifact and its optional training cutoff."""

    model_name: _Identifier
    training_cutoff: _UTCDateTime | None = None

    @model_validator(mode="after")
    def _check_training_cutoff(self) -> Self:
        if self.training_cutoff is not None and self.training_cutoff > self.created_at:
            raise ValueError("training_cutoff must not be after created_at")
        return self


class SourceProvenance(_FrozenMetadata):
    """Independent provenance times; absent availability information stays missing.

    effective_at: when the underlying fact/event became effective.
    known_at: when the information became available/knowable to the system.
    retrieved_at: when the system retrieved/stored the source.

    This contract does not infer times or enforce prediction-time leakage rules.
    """

    source: _Identifier
    retrieved_at: _UTCDateTime
    effective_at: _UTCDateTime | None = None
    known_at: _UTCDateTime | None = None
    source_record_id: _Identifier | None = None
    source_url: _Identifier | None = None
