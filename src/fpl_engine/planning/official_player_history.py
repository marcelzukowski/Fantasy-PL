"""Explicit Official FPL element-summary acquisition for advisory minutes history.

Nothing imports or calls this module during desktop startup.  It is invoked by
the explicit ``refresh-player-history`` command and uses the established
OfficialFPLAdapter/HttpCache/RawStore boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from fpl_engine.data.providers.fpl_api import FPLApiError, OfficialFPLAdapter
from fpl_engine.data.raw_store import RawStore
from fpl_engine.reports import DecisionReportV2

from .player_minutes_history import appearances_from_official_element_history


OFFICIAL_PLAYER_HISTORY_ACQUISITION_SCHEMA_V1 = "official_fpl_player_history_acquisition_v1"
DEFAULT_HISTORY_CACHE_TTL = timedelta(minutes=5)


class OfficialPlayerHistoryError(ValueError):
    pass


def _utc(value: datetime | str, label: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OfficialPlayerHistoryError(f"{label} must be ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OfficialPlayerHistoryError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OfficialPlayerHistoryError(f"Cannot read {label}.") from exc


def _raw_snapshot_id(raw_store: RawStore, *, entity: str, source_record_id: str, checksum: str) -> str | None:
    """Recover a RawStore receipt for a fresh cache hit without creating data."""
    base = raw_store.root / "official_fpl_api" / entity
    if not base.is_dir():
        return None
    for metadata in base.glob("*/*/snapshot.metadata.json"):
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (str(value.get("source_record_id")) == str(source_record_id)
                and value.get("checksum") == checksum and isinstance(value.get("snapshot_id"), str)):
            return str(value["snapshot_id"])
    return None


def _provider_ids(bundle_directory: Path, *, squad_player_ids: Sequence[str], decision: DecisionReportV2 | None,
                  top_targets: int, extra_player_ids: Sequence[str] = ()) -> tuple[tuple[str, ...], dict[str, str]]:
    rows = _json(bundle_directory / "current_players.json", "current_players")
    if not isinstance(rows, list):
        raise OfficialPlayerHistoryError("current_players must be an array.")
    by_id = {
        str(row.get("player_id")): str(row.get("provider_id"))
        for row in rows if isinstance(row, Mapping) and row.get("player_id") is not None and row.get("provider_id") is not None
    }
    selected = {str(value) for value in squad_player_ids}
    # The desktop worker freezes all policy outputs before this advisory call.
    # It may therefore supply its exact final set (V3 path, previews and
    # captaincy) without constructing a temporary DecisionReport.
    selected.update(str(value) for value in extra_player_ids if value)
    if decision is not None:
        selected.update(str(value) for value in decision.recommendation.get("transfers_in", ()) if value)
        for plan in decision.feasible_plans:
            selected.update(str(value) for value in plan.get("transfers_in", ()) if value)
        for preview in decision.strategy_previews:
            selected.update((preview.captain, preview.vice_captain))
    candidates = _json(bundle_directory / "candidate_pool.json", "candidate_pool")
    if isinstance(candidates, list):
        ranked = sorted(
            (row for row in candidates if isinstance(row, Mapping) and row.get("player_id") in by_id),
            key=lambda row: (-float(row.get("weighted_ev_next_6", 0.0) or 0.0), str(row.get("player_id"))),
        )
        selected.update(str(row["player_id"]) for row in ranked[:max(0, top_targets)])
    missing = tuple(sorted(player_id for player_id in selected if player_id not in by_id))
    mapping = {player_id: by_id[player_id] for player_id in sorted(selected) if player_id in by_id}
    return missing, mapping


@dataclass(frozen=True)
class OfficialPlayerHistoryAcquisition:
    schema_version: str
    season: str
    gameweek: int
    bundle_run_id: str
    context_id: str | None
    requested_at: str
    requested_player_ids: tuple[str, ...]
    provider_player_ids: Mapping[str, str]
    appearances: tuple[Mapping[str, Any], ...]
    raw_source_references: Mapping[str, Mapping[str, Any]]
    failures: Mapping[str, str]
    warnings: tuple[str, ...]
    statistics: Mapping[str, Any]
    production_influence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "season": self.season, "gameweek": self.gameweek,
            "bundle_run_id": self.bundle_run_id, "context_id": self.context_id, "requested_at": self.requested_at,
            "requested_player_ids": list(self.requested_player_ids), "provider_player_ids": dict(self.provider_player_ids),
            "appearances": [dict(row) for row in self.appearances], "raw_source_references": {key: dict(value) for key, value in self.raw_source_references.items()},
            "failures": dict(self.failures), "warnings": list(self.warnings), "statistics": dict(self.statistics),
            "production_influence": False,
        }


def write_official_player_history_acquisition(bundle_directory: Path, acquisition: OfficialPlayerHistoryAcquisition) -> Path:
    payload = json.dumps(acquisition.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    target = Path(bundle_directory) / f"player_minutes_history_records_{sha256(payload).hexdigest()[:24]}.json"
    if target.exists() and target.read_bytes() != payload:
        raise OfficialPlayerHistoryError("immutable player-history acquisition conflicts.")
    target.write_bytes(payload)
    return target


class OfficialPlayerHistoryAcquirer:
    """Small bounded sequential acquisition; Official FPL is per-player here."""

    def __init__(self, *, adapter: OfficialFPLAdapter, raw_store: RawStore, cache_ttl: timedelta = DEFAULT_HISTORY_CACHE_TTL, clock=None):
        if not callable(getattr(adapter, "get_fixtures", None)) or not callable(getattr(adapter, "get_element_summary", None)) or not isinstance(raw_store, RawStore):
            raise OfficialPlayerHistoryError("OfficialFPLAdapter-compatible adapter and RawStore are required.")
        if type(cache_ttl) is not timedelta or cache_ttl < timedelta(0):
            raise OfficialPlayerHistoryError("cache_ttl must be non-negative timedelta.")
        self.adapter, self.raw_store, self.cache_ttl = adapter, raw_store, cache_ttl
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def refresh(self, *, bundle_directory: Path, season: str, gameweek: int, squad_player_ids: Sequence[str], decision: DecisionReportV2 | None = None,
                top_targets: int = 10, extra_player_ids: Sequence[str] = ()) -> OfficialPlayerHistoryAcquisition:
        started = perf_counter(); requested_at = _utc(self.clock(), "clock"); bundle = Path(bundle_directory)
        missing, canonical_to_provider = _provider_ids(
            bundle, squad_player_ids=squad_player_ids, decision=decision,
            top_targets=top_targets, extra_player_ids=extra_player_ids,
        )
        warnings = [f"Provider ID unresolved for {player_id}." for player_id in missing]
        failures: dict[str, str] = {}; raw_refs: dict[str, Mapping[str, Any]] = {}; records: list[Mapping[str, Any]] = []
        cache_hits = network_requests = successes = 0
        try:
            fixtures_result = self.adapter.get_fixtures()
            network_requests += int(not fixtures_result.from_cache); cache_hits += int(fixtures_result.from_cache)
            fixture_raw = fixtures_result.raw_snapshot.snapshot_id if fixtures_result.raw_snapshot else _raw_snapshot_id(self.raw_store, entity="fixtures", source_record_id="None", checksum=fixtures_result.response.checksum)
            if fixture_raw is None:
                raise OfficialPlayerHistoryError("cached fixture response has no recoverable immutable raw receipt.")
            fixtures_by_id = {str(row.get("id")): row for row in fixtures_result.payload if isinstance(row, Mapping) and row.get("id") is not None}
            raw_refs["fixtures"] = {"raw_snapshot_id": fixture_raw, "checksum": fixtures_result.response.checksum, "cache_key": fixtures_result.response.cache_key, "observed_at": fixtures_result.response.stored_at.isoformat(), "from_cache": fixtures_result.from_cache}
        except Exception as exc:
            warnings.append(f"Official fixture completion state unavailable: {type(exc).__name__}.")
            fixtures_by_id = None
        if fixtures_by_id is not None:
            for canonical_id, provider_id in canonical_to_provider.items():
                try:
                    result = self.adapter.get_element_summary(int(provider_id))
                    network_requests += int(not result.from_cache); cache_hits += int(result.from_cache)
                    raw_id = result.raw_snapshot.snapshot_id if result.raw_snapshot else _raw_snapshot_id(self.raw_store, entity="element_summary", source_record_id=provider_id, checksum=result.response.checksum)
                    if raw_id is None:
                        raise OfficialPlayerHistoryError("cached player response has no recoverable immutable raw receipt.")
                    raw_refs[canonical_id] = {"provider_player_id": provider_id, "raw_snapshot_id": raw_id, "checksum": result.response.checksum, "cache_key": result.response.cache_key, "observed_at": result.response.stored_at.isoformat(), "from_cache": result.from_cache}
                    records.extend(row.to_dict() for row in appearances_from_official_element_history(
                        player_id=canonical_id, history=result.payload.get("history", ()), fixtures_by_id=fixtures_by_id,
                        observed_at=result.response.stored_at, source_snapshot_id=raw_id,
                    ))
                    successes += 1
                except Exception as exc:
                    # Advisory collection must tolerate a provider failure per player.
                    failures[canonical_id] = type(exc).__name__
        if failures:
            warnings.append(f"Official player history unavailable for {len(failures)} requested player(s); advisory fallback retained.")
        return OfficialPlayerHistoryAcquisition(
            OFFICIAL_PLAYER_HISTORY_ACQUISITION_SCHEMA_V1, str(season), int(gameweek), bundle.name,
            decision.context_id if decision is not None else None, requested_at.isoformat(), tuple(sorted(canonical_to_provider)), canonical_to_provider,
            tuple(records), raw_refs, failures, tuple(warnings),
            {"players_requested": len(canonical_to_provider), "cache_hits": cache_hits, "network_requests": network_requests,
             "successes": successes, "failures": len(failures), "fixture_rows": len({str(row.get("fixture_id")) for row in records}),
             "appearance_rows": len(records), "acquisition_seconds": round(perf_counter()-started, 6), "cache_ttl_seconds": int(self.cache_ttl.total_seconds())},
        )
