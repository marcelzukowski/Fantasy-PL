from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import unicodedata
from typing import Callable

from fpl_engine.data.providers.the_odds_api import (
    PROVIDER,
    TheOddsApiEventIdentityAudit,
)
from fpl_engine.data.schemas.entities import (
    FixtureProviderMapping,
    MatchMethod,
    ReviewStatus,
)


ODDS_PLAYER_ALIAS_SCHEMA_VERSION = 1


class OddsIdentityError(ValueError):
    """Invalid bookmaker identity data."""


class OddsIdentityConflictError(
    OddsIdentityError
):
    """Provider identity conflicts with an existing mapping."""


def _utc(
    value: datetime,
    name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise OddsIdentityError(
            f"{name} must be timezone-aware"
        )

    return value.astimezone(
        timezone.utc
    )


def _non_empty(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise OddsIdentityError(
            f"{name} must be non-empty"
        )

    return value.strip()


def normalize_odds_player_alias(
    value: str,
) -> str:
    """Conservative textual normalization.

    This is an alias lookup key only. It is never a canonical
    player ID and never performs fuzzy matching.
    """

    text = _non_empty(
        value,
        "provider_player_name",
    )

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    return " ".join(
        text.split()
    ).casefold()


@dataclass(frozen=True)
class FixtureMappingPersistenceReport:
    created: tuple[str, ...]
    reused: tuple[str, ...]


def persist_fixture_identity_matches(
    database,
    audit: TheOddsApiEventIdentityAudit,
    *,
    effective_from: datetime,
    recorded_at: datetime,
    retrieved_at: datetime | None = None,
    source_record_id: str | None = None,
    match_confidence: float = 1.0,
) -> FixtureMappingPersistenceReport:
    """Persist confirmed provider event -> canonical fixture mappings.

    Existing provider IDs are never silently remapped. Any existing
    mapping to another fixture, or an unresolved/non-confirmed mapping,
    fails closed.
    """

    if not isinstance(
        audit,
        TheOddsApiEventIdentityAudit,
    ):
        raise OddsIdentityError(
            "audit must be TheOddsApiEventIdentityAudit"
        )

    effective = _utc(
        effective_from,
        "effective_from",
    )

    now = _utc(
        recorded_at,
        "recorded_at",
    )

    retrieved = (
        None
        if retrieved_at is None
        else _utc(
            retrieved_at,
            "retrieved_at",
        )
    )

    if (
        type(match_confidence)
        not in (int, float)
        or not math.isfinite(
            match_confidence
        )
        or not 0
        <= match_confidence
        <= 1
    ):
        raise OddsIdentityError(
            "match_confidence must be in [0, 1]"
        )

    if source_record_id is not None:
        source_record_id = _non_empty(
            source_record_id,
            "source_record_id",
        )

    if not hasattr(
        database,
        "connection",
    ) or not callable(
        getattr(
            database,
            "persist_fixture_mapping",
            None,
        )
    ):
        raise OddsIdentityError(
            "database must provide connection "
            "and persist_fixture_mapping()"
        )

    created: list[str] = []
    reused: list[str] = []

    seen_provider_ids: set[str] = set()

    for match in audit.matches:
        provider_id = _non_empty(
            match.provider_event_id,
            "provider_event_id",
        )

        fixture_id = _non_empty(
            match.canonical_fixture_id,
            "canonical_fixture_id",
        )

        if provider_id in seen_provider_ids:
            raise OddsIdentityConflictError(
                "duplicate provider event ID "
                "inside identity audit"
            )

        seen_provider_ids.add(
            provider_id
        )

        rows = database.connection.execute(
            """
            SELECT
                fixture_id,
                review_status,
                effective_from,
                effective_to,
                provider_kickoff
            FROM dim_fixture_provider_map
            WHERE provider=?
              AND provider_id=?
            """,
            [
                PROVIDER,
                provider_id,
            ],
        ).fetchall()

        if rows:
            mapped_fixture_ids = {
                str(row[0])
                for row in rows
            }

            if mapped_fixture_ids != {
                fixture_id
            }:
                raise OddsIdentityConflictError(
                    "The Odds API event "
                    f"{provider_id!r} already maps to "
                    "a different canonical fixture"
                )

            confirmed_rows = [
                row
                for row in rows
                if str(row[1])
                == ReviewStatus.confirmed.value
            ]

            if not confirmed_rows:
                raise OddsIdentityConflictError(
                    "existing bookmaker fixture mapping "
                    "is not confirmed and requires review"
                )

            active_confirmed = [
                row
                for row in confirmed_rows
                if (
                    _utc(
                        row[2],
                        "existing effective_from",
                    )
                    <= effective
                    and (
                        row[3] is None
                        or _utc(
                            row[3],
                            "existing effective_to",
                        )
                        >= effective
                    )
                )
            ]

            if len(active_confirmed) != 1:
                raise OddsIdentityConflictError(
                    "existing bookmaker fixture mapping "
                    "is ambiguous or inactive at effective_from"
                )

            reused.append(
                provider_id
            )
            continue

        database.persist_fixture_mapping(
            FixtureProviderMapping(
                provider=PROVIDER,
                provider_id=provider_id,
                provider_name=None,
                effective_from=effective,
                effective_to=None,
                match_method=(
                    MatchMethod.cross_provider_bridge
                ),
                match_confidence=float(
                    match_confidence
                ),
                review_status=(
                    ReviewStatus.confirmed
                ),
                created_at=now,
                updated_at=now,
                source_record_id=(
                    source_record_id
                ),
                retrieved_at=retrieved,
                fixture_id=fixture_id,
                provider_kickoff=(
                    match.provider_commence_time
                ),
            )
        )

        created.append(
            provider_id
        )

    return FixtureMappingPersistenceReport(
        created=tuple(
            sorted(created)
        ),
        reused=tuple(
            sorted(reused)
        ),
    )


@dataclass(frozen=True)
class OddsPlayerAlias:
    provider_player_name: str
    player_id: str | None

    effective_from: datetime
    effective_to: datetime | None

    review_status: ReviewStatus

    created_at: datetime
    updated_at: datetime

    source_record_id: str | None = None
    retrieved_at: datetime | None = None

    def __post_init__(self) -> None:
        name = _non_empty(
            self.provider_player_name,
            "provider_player_name",
        )

        object.__setattr__(
            self,
            "provider_player_name",
            name,
        )

        effective_from = _utc(
            self.effective_from,
            "effective_from",
        )

        object.__setattr__(
            self,
            "effective_from",
            effective_from,
        )

        if self.effective_to is not None:
            effective_to = _utc(
                self.effective_to,
                "effective_to",
            )

            if effective_to < effective_from:
                raise OddsIdentityError(
                    "effective_to cannot be before "
                    "effective_from"
                )

            object.__setattr__(
                self,
                "effective_to",
                effective_to,
            )

        object.__setattr__(
            self,
            "created_at",
            _utc(
                self.created_at,
                "created_at",
            ),
        )

        object.__setattr__(
            self,
            "updated_at",
            _utc(
                self.updated_at,
                "updated_at",
            ),
        )

        if self.retrieved_at is not None:
            object.__setattr__(
                self,
                "retrieved_at",
                _utc(
                    self.retrieved_at,
                    "retrieved_at",
                ),
            )

        try:
            status = ReviewStatus(
                self.review_status
            )
        except ValueError as exc:
            raise OddsIdentityError(
                "invalid review_status"
            ) from exc

        object.__setattr__(
            self,
            "review_status",
            status,
        )

        player_id = self.player_id

        if player_id is not None:
            player_id = _non_empty(
                player_id,
                "player_id",
            )

            object.__setattr__(
                self,
                "player_id",
                player_id,
            )

        if (
            status
            == ReviewStatus.confirmed
            and player_id is None
        ):
            raise OddsIdentityError(
                "confirmed alias requires player_id"
            )

        if (
            self.source_record_id
            is not None
        ):
            object.__setattr__(
                self,
                "source_record_id",
                _non_empty(
                    self.source_record_id,
                    "source_record_id",
                ),
            )

    @property
    def normalized_alias(self) -> str:
        return normalize_odds_player_alias(
            self.provider_player_name
        )

    def is_active_at(
        self,
        at: datetime,
    ) -> bool:
        timestamp = _utc(
            at,
            "at",
        )

        return (
            self.effective_from
            <= timestamp
            and (
                self.effective_to is None
                or self.effective_to
                >= timestamp
            )
        )


def _record_to_json(
    record: OddsPlayerAlias,
) -> dict[str, object]:
    return {
        "provider_player_name": (
            record.provider_player_name
        ),
        "normalized_alias": (
            record.normalized_alias
        ),
        "player_id": record.player_id,
        "effective_from": (
            record.effective_from.isoformat()
        ),
        "effective_to": (
            None
            if record.effective_to is None
            else record.effective_to.isoformat()
        ),
        "review_status": (
            record.review_status.value
        ),
        "created_at": (
            record.created_at.isoformat()
        ),
        "updated_at": (
            record.updated_at.isoformat()
        ),
        "source_record_id": (
            record.source_record_id
        ),
        "retrieved_at": (
            None
            if record.retrieved_at is None
            else record.retrieved_at.isoformat()
        ),
    }


def _parse_json_datetime(
    value: object,
    name: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise OddsIdentityError(
            f"{name} must be an ISO timestamp"
        )

    try:
        parsed = datetime.fromisoformat(
            value
        )
    except ValueError as exc:
        raise OddsIdentityError(
            f"invalid {name}"
        ) from exc

    return _utc(
        parsed,
        name,
    )


def _record_from_json(
    value: object,
) -> OddsPlayerAlias:
    if not isinstance(
        value,
        dict,
    ):
        raise OddsIdentityError(
            "alias record must be an object"
        )

    effective_to_raw = value.get(
        "effective_to"
    )

    retrieved_raw = value.get(
        "retrieved_at"
    )

    return OddsPlayerAlias(
        provider_player_name=str(
            value.get(
                "provider_player_name",
                "",
            )
        ),
        player_id=(
            None
            if value.get("player_id")
            is None
            else str(
                value.get("player_id")
            )
        ),
        effective_from=(
            _parse_json_datetime(
                value.get(
                    "effective_from"
                ),
                "effective_from",
            )
        ),
        effective_to=(
            None
            if effective_to_raw is None
            else _parse_json_datetime(
                effective_to_raw,
                "effective_to",
            )
        ),
        review_status=ReviewStatus(
            value.get(
                "review_status"
            )
        ),
        created_at=(
            _parse_json_datetime(
                value.get(
                    "created_at"
                ),
                "created_at",
            )
        ),
        updated_at=(
            _parse_json_datetime(
                value.get(
                    "updated_at"
                ),
                "updated_at",
            )
        ),
        source_record_id=(
            None
            if value.get(
                "source_record_id"
            )
            is None
            else str(
                value.get(
                    "source_record_id"
                )
            )
        ),
        retrieved_at=(
            None
            if retrieved_raw is None
            else _parse_json_datetime(
                retrieved_raw,
                "retrieved_at",
            )
        ),
    )


def _intervals_overlap(
    left: OddsPlayerAlias,
    right: OddsPlayerAlias,
) -> bool:
    left_end = (
        datetime.max.replace(
            tzinfo=timezone.utc
        )
        if left.effective_to is None
        else left.effective_to
    )

    right_end = (
        datetime.max.replace(
            tzinfo=timezone.utc
        )
        if right.effective_to is None
        else right.effective_to
    )

    return (
        left.effective_from
        <= right_end
        and right.effective_from
        <= left_end
    )


class OddsPlayerAliasRegistry:
    """Persistent exact alias registry for bookmaker player labels.

    Provider names are lookup aliases only. They are never canonical
    IDs and there is deliberately no fuzzy fallback.
    """

    def __init__(
        self,
        path: Path,
    ):
        self.path = Path(
            path
        )

    def records(
        self,
    ) -> tuple[OddsPlayerAlias, ...]:
        return self._load()

    def add(
        self,
        record: OddsPlayerAlias,
    ) -> bool:
        if not isinstance(
            record,
            OddsPlayerAlias,
        ):
            raise OddsIdentityError(
                "record must be OddsPlayerAlias"
            )

        records = list(
            self._load()
        )

        for existing in records:
            if (
                existing.normalized_alias
                != record.normalized_alias
            ):
                continue

            if (
                existing.player_id
                == record.player_id
                and existing.effective_from
                == record.effective_from
                and existing.effective_to
                == record.effective_to
                and existing.review_status
                == record.review_status
            ):
                return False

            if (
                existing.review_status
                == ReviewStatus.confirmed
                and record.review_status
                == ReviewStatus.confirmed
                and _intervals_overlap(
                    existing,
                    record,
                )
                and existing.player_id
                != record.player_id
            ):
                raise OddsIdentityConflictError(
                    "overlapping confirmed bookmaker aliases "
                    "map the same provider name to "
                    "different canonical players"
                )

        records.append(
            record
        )

        records.sort(
            key=lambda item: (
                item.normalized_alias,
                item.effective_from,
                item.player_id or "",
                item.review_status.value,
            )
        )

        self._write(
            tuple(records)
        )

        return True

    def resolve(
        self,
        provider_player_name: str,
        *,
        at: datetime,
    ) -> str | None:
        normalized = (
            normalize_odds_player_alias(
                provider_player_name
            )
        )

        timestamp = _utc(
            at,
            "at",
        )

        active = [
            record
            for record in self._load()
            if (
                record.normalized_alias
                == normalized
                and record.review_status
                == ReviewStatus.confirmed
                and record.is_active_at(
                    timestamp
                )
            )
        ]

        if not active:
            return None

        player_ids = {
            record.player_id
            for record in active
        }

        if (
            None in player_ids
            or len(player_ids) != 1
        ):
            raise OddsIdentityConflictError(
                "bookmaker player alias resolves "
                "to multiple canonical players"
            )

        return next(
            iter(player_ids)
        )

    def resolver(
        self,
        *,
        at: datetime,
    ) -> Callable[
        [str],
        str | None,
    ]:
        timestamp = _utc(
            at,
            "at",
        )

        return lambda name: self.resolve(
            name,
            at=timestamp,
        )

    def _load(
        self,
    ) -> tuple[OddsPlayerAlias, ...]:
        if not self.path.exists():
            return ()

        try:
            payload = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise OddsIdentityError(
                f"cannot read alias registry "
                f"{self.path}"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise OddsIdentityError(
                "alias registry must be an object"
            )

        if (
            payload.get(
                "schema_version"
            )
            != ODDS_PLAYER_ALIAS_SCHEMA_VERSION
        ):
            raise OddsIdentityError(
                "unsupported alias registry schema"
            )

        if (
            payload.get("provider")
            != PROVIDER
        ):
            raise OddsIdentityError(
                "alias registry provider mismatch"
            )

        raw_records = payload.get(
            "records"
        )

        if not isinstance(
            raw_records,
            list,
        ):
            raise OddsIdentityError(
                "alias registry records must be a list"
            )

        return tuple(
            _record_from_json(
                item
            )
            for item in raw_records
        )

    def _write(
        self,
        records: tuple[
            OddsPlayerAlias,
            ...
        ],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "schema_version": (
                ODDS_PLAYER_ALIAS_SCHEMA_VERSION
            ),
            "provider": PROVIDER,
            "records": [
                _record_to_json(
                    record
                )
                for record in records
            ],
        }

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"

        temporary = self.path.with_name(
            self.path.name + ".tmp"
        )

        try:
            temporary.write_text(
                content,
                encoding="utf-8",
            )

            os.replace(
                temporary,
                self.path,
            )
        except OSError as exc:
            try:
                temporary.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

            raise OddsIdentityError(
                f"cannot write alias registry "
                f"{self.path}"
            ) from exc
