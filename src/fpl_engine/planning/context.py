"""Canonical identity for one read-only FPL planning run.

``PlanningContext`` deliberately contains only engine-relevant account state,
projection provenance and verified artifact digests.  It excludes local paths,
Qt state, report creation time and other display-only values.  Its identifier is
the SHA-256 digest of a canonical JSON representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


PLANNING_CONTEXT_SCHEMA = "planning_context_v1"
REQUIRED_ARTIFACTS = (
    "prediction_context",
    "shadow_bundle",
    "current_players",
    "fixture_horizon",
    "minutes",
)


class PlanningContextError(ValueError):
    """A planning run cannot be identified safely."""


class ProjectionArtifactIntegrityError(PlanningContextError):
    """A canonical projection artifact is missing or differs from its manifest."""


@dataclass(frozen=True)
class ProjectionArtifactIntegrity:
    manifest_sha256: str
    artifact_hashes: tuple[tuple[str, str], ...]


_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def _value(source: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _timestamp(value: object, name: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlanningContextError(f"{name} must be an ISO-8601 timestamp") from exc
    else:
        raise PlanningContextError(f"{name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlanningContextError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _file_sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _HASH_CACHE.get(key)
    if cached is not None:
        return cached
    digest = sha256(path.read_bytes()).hexdigest()
    _HASH_CACHE[key] = digest
    return digest


def _safe_artifact_path(run_dir: Path, relative_path: object, artifact: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ProjectionArtifactIntegrityError(
            f"Projection artifact integrity check failed: {artifact} has no manifest path."
        )
    candidate = (run_dir / relative_path).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ProjectionArtifactIntegrityError(
            f"Projection artifact integrity check failed: {artifact} has an unsafe path."
        ) from exc
    return candidate


def verify_projection_artifacts(
    bundle_path: Path,
    manifest: Mapping[str, Any],
    *,
    require_hashes: bool = False,
) -> ProjectionArtifactIntegrity | None:
    """Verify the immutable artifacts consumed by decision, previews and chips.

    Legacy manifests without an ``artifacts`` hash section remain discoverable,
    but cannot create a new verified PlanningContext.
    """
    run_dir = Path(bundle_path).resolve().parent
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        if require_hashes:
            raise ProjectionArtifactIntegrityError(
                "Projection artifact integrity check failed: this projection run has no artifact hash manifest."
            )
        return None
    verified: list[tuple[str, str]] = []
    for artifact in REQUIRED_ARTIFACTS:
        metadata = artifacts.get(artifact)
        if not isinstance(metadata, Mapping):
            raise ProjectionArtifactIntegrityError(
                f"Projection artifact integrity check failed: required artifact {artifact} is missing from the manifest."
            )
        expected = metadata.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ProjectionArtifactIntegrityError(
                f"Projection artifact integrity check failed: {artifact} has no valid SHA-256 digest."
            )
        path = _safe_artifact_path(run_dir, metadata.get("path"), artifact)
        if not path.is_file():
            raise ProjectionArtifactIntegrityError(
                f"Projection artifact integrity check failed: required artifact {artifact} is missing."
            )
        actual = _file_sha256(path)
        if actual != expected:
            raise ProjectionArtifactIntegrityError(
                f"Projection artifact integrity check failed: {artifact} hash mismatch."
            )
        verified.append((artifact, actual))
    return ProjectionArtifactIntegrity(
        manifest_sha256=_file_sha256(run_dir / "run_manifest.json"),
        artifact_hashes=tuple(sorted(verified)),
    )


def _freshness(bundle: Mapping[str, Any]) -> tuple[tuple[str, str | None, str | None, str | None], ...]:
    rows = bundle.get("data_freshness")
    if not isinstance(rows, list):
        return ()
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        source = row.get("source")
        if not isinstance(source, str) or not source:
            continue
        result.append((
            source,
            _timestamp(row.get("known_at"), "data_freshness.known_at"),
            _timestamp(row.get("source_snapshot_timestamp"), "data_freshness.source_snapshot_timestamp"),
            str(row["raw_snapshot_id"]) if row.get("raw_snapshot_id") is not None else None,
        ))
    return tuple(sorted(result))


@dataclass(frozen=True)
class PlanningContext:
    schema_version: str
    season: str
    gameweek: int
    deadline: str | None
    player_ids: tuple[str, ...]
    selling_prices_tenths: tuple[tuple[str, int], ...]
    bank_tenths: int
    free_transfers: int
    chips_used: tuple[tuple[str, bool], ...]
    projection_run_id: str
    prediction_timestamp: str
    simulator_version: str | None
    model_versions: tuple[str, ...]
    simulation_count: int
    optimizer_rule_version: int | None
    scoring_rule_version: int | None
    manifest_sha256: str
    artifact_hashes: tuple[tuple[str, str], ...]
    fpl_sync_timestamp: str | None
    source_state_timestamp: str | None
    data_freshness: tuple[tuple[str, str | None, str | None, str | None], ...]

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "season": self.season,
            "gameweek": self.gameweek,
            "deadline": self.deadline,
            "account": {
                "player_ids": list(self.player_ids),
                "selling_prices_tenths": [[player_id, price] for player_id, price in self.selling_prices_tenths],
                "bank_tenths": self.bank_tenths,
                "free_transfers": self.free_transfers,
                "chips_used": [[chip, used] for chip, used in self.chips_used],
                "fpl_sync_timestamp": self.fpl_sync_timestamp,
                "source_state_timestamp": self.source_state_timestamp,
            },
            "projection": {
                "projection_run_id": self.projection_run_id,
                "prediction_timestamp": self.prediction_timestamp,
                "simulator_version": self.simulator_version,
                "model_versions": list(self.model_versions),
                "simulation_count": self.simulation_count,
                "optimizer_rule_version": self.optimizer_rule_version,
                "scoring_rule_version": self.scoring_rule_version,
                "manifest_sha256": self.manifest_sha256,
                "artifact_hashes": [[name, digest] for name, digest in self.artifact_hashes],
                "data_freshness": [list(row) for row in self.data_freshness],
            },
        }

    @property
    def context_id(self) -> str:
        return sha256(_canonical_json(self.canonical_payload())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["context_id"] = self.context_id
        return payload


def build_planning_context(
    *,
    state: Mapping[str, Any] | object,
    bundle_path: Path,
    bundle: Mapping[str, Any],
    manifest: Mapping[str, Any],
    prediction_context: Mapping[str, Any] | None = None,
) -> PlanningContext:
    """Create the single verified semantic identity for a decision analysis."""
    integrity = verify_projection_artifacts(bundle_path, manifest, require_hashes=True)
    assert integrity is not None
    player_ids = tuple(sorted(str(value) for value in _value(state, "player_ids", ())))
    if len(player_ids) != 15 or len(set(player_ids)) != 15:
        raise PlanningContextError("PlanningContext requires exactly 15 unique player IDs.")
    selling_raw = _value(state, "selling_prices_tenths", {})
    if not isinstance(selling_raw, Mapping):
        raise PlanningContextError("PlanningContext requires owned-player selling prices.")
    selling = tuple(sorted((player_id, int(selling_raw[player_id])) for player_id in player_ids if player_id in selling_raw))
    if len(selling) != len(player_ids) or any(price <= 0 for _, price in selling):
        raise PlanningContextError("PlanningContext requires a positive selling price for every owned player.")
    chips_raw = _value(state, "chips_used", {})
    if not isinstance(chips_raw, Mapping):
        raise PlanningContextError("PlanningContext chip state is invalid.")
    pipeline = bundle.get("pipeline")
    if not isinstance(pipeline, Mapping):
        raise PlanningContextError("PlanningContext requires projection simulation metadata.")
    try:
        gameweek = int(_value(state, "gameweek"))
        bundle_gameweek = int(bundle.get("current_gameweek"))
        simulation_count = int(pipeline.get("simulations_per_fixture"))
        bank = int(_value(state, "bank_tenths"))
        free_transfers = int(_value(state, "free_transfers"))
    except (TypeError, ValueError) as exc:
        raise PlanningContextError("PlanningContext contains invalid account or projection values.") from exc
    season = str(_value(state, "season"))
    if season != str(bundle.get("season")) or gameweek != bundle_gameweek:
        raise PlanningContextError("PlanningContext state and projection bundle do not share the same season and gameweek.")
    if not 1 <= gameweek <= 38 or bank < 0 or not 0 <= free_transfers <= 5 or simulation_count < 1:
        raise PlanningContextError("PlanningContext contains out-of-range account or projection values.")
    context_payload = prediction_context if isinstance(prediction_context, Mapping) else {}
    deadline = next((context_payload.get(key) for key in ("deadline", "target_deadline", "deadline_utc") if context_payload.get(key) is not None), None)
    model_versions_raw = manifest.get("model_versions", ())
    model_versions = tuple(sorted(str(value) for value in model_versions_raw)) if isinstance(model_versions_raw, list) else ()
    prediction_timestamp = _timestamp(bundle.get("prediction_timestamp"), "prediction_timestamp")
    if prediction_timestamp is None:
        raise PlanningContextError("PlanningContext requires a projection prediction timestamp.")
    return PlanningContext(
        schema_version=PLANNING_CONTEXT_SCHEMA,
        season=season,
        gameweek=gameweek,
        deadline=_timestamp(deadline, "deadline"),
        player_ids=player_ids,
        selling_prices_tenths=selling,
        bank_tenths=bank,
        free_transfers=free_transfers,
        chips_used=tuple(sorted((str(key), bool(value)) for key, value in chips_raw.items())),
        projection_run_id=Path(bundle_path).resolve().parent.name,
        prediction_timestamp=prediction_timestamp,
        simulator_version=str(pipeline["simulator_version"]) if pipeline.get("simulator_version") is not None else None,
        model_versions=model_versions,
        simulation_count=simulation_count,
        optimizer_rule_version=(int(manifest["optimizer_rule_version"]) if manifest.get("optimizer_rule_version") is not None else None),
        scoring_rule_version=(int(manifest["scoring_rule_version"]) if manifest.get("scoring_rule_version") is not None else None),
        manifest_sha256=integrity.manifest_sha256,
        artifact_hashes=integrity.artifact_hashes,
        fpl_sync_timestamp=_timestamp(_value(state, "updated_at"), "fpl_sync_timestamp"),
        source_state_timestamp=_timestamp(_value(state, "updated_at"), "source_state_timestamp"),
        data_freshness=_freshness(bundle),
    )


def context_from_report(payload: Mapping[str, Any]) -> PlanningContext | None:
    """Only recognize new, self-identifying reports; legacy reports stay unverified."""
    raw = payload.get("planning_context")
    context_id = payload.get("context_id")
    if not isinstance(raw, Mapping) or not isinstance(context_id, str):
        return None
    # Rebuild through the canonical fields rather than trusting a report ID.
    try:
        account = raw["account"]
        projection = raw["projection"]
        if not isinstance(account, Mapping) or not isinstance(projection, Mapping):
            return None
        context = PlanningContext(
            schema_version=str(raw["schema_version"]), season=str(raw["season"]), gameweek=int(raw["gameweek"]),
            deadline=raw.get("deadline"), player_ids=tuple(str(value) for value in account["player_ids"]),
            selling_prices_tenths=tuple((str(row[0]), int(row[1])) for row in account["selling_prices_tenths"]),
            bank_tenths=int(account["bank_tenths"]), free_transfers=int(account["free_transfers"]),
            chips_used=tuple((str(row[0]), bool(row[1])) for row in account["chips_used"]),
            projection_run_id=str(projection["projection_run_id"]), prediction_timestamp=str(projection["prediction_timestamp"]),
            simulator_version=projection.get("simulator_version"), model_versions=tuple(str(value) for value in projection.get("model_versions", ())),
            simulation_count=int(projection["simulation_count"]), optimizer_rule_version=projection.get("optimizer_rule_version"),
            scoring_rule_version=projection.get("scoring_rule_version"), manifest_sha256=str(projection["manifest_sha256"]),
            artifact_hashes=tuple((str(row[0]), str(row[1])) for row in projection["artifact_hashes"]),
            fpl_sync_timestamp=account.get("fpl_sync_timestamp"), source_state_timestamp=account.get("source_state_timestamp"),
            data_freshness=tuple(tuple(row) for row in projection.get("data_freshness", ())),
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if context.schema_version != PLANNING_CONTEXT_SCHEMA or context.context_id != context_id:
        return None
    return context
