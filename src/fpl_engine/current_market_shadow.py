"""Forward-looking current-GW bookmaker shadow collection.

This module deliberately sits beside, rather than inside, the V22 production
pipeline.  It records challenger evidence after a successful V22 run and never
returns values to the simulator, projection builder, or Decision Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Sequence

from fpl_engine.data.market_odds import (
    aggregate_market_probabilities,
    devig_selected_quotes,
    select_pit_quotes,
)
from fpl_engine.data.providers.the_odds_api import (
    PROVIDER,
    SUPPORTED_MARKETS,
    CanonicalFixtureCandidate,
    TheOddsApiAdapter,
    TheOddsApiError,
    match_events_to_canonical_fixtures,
    parse_market_quotes,
)
from fpl_engine.models.events.market_shadow import (
    MarketShadowReport,
    build_market_shadow_report,
)


MARKET_SHADOW_ARTIFACT_VERSION = "current_market_shadow_v2"
DEFAULT_SNAPSHOT_FRESHNESS = timedelta(minutes=10)

# These are explicit, provider-facing Premier League names.  They are aliases,
# never identity evidence on their own: the resolved sides still have to match
# a single canonical fixture within the kickoff tolerance.
_PROVIDER_TEAM_ALIASES = {
    "brightonandhovealbion": "brighton",
    "leedsunited": "leeds",
    "manchestercity": "mancity",
    "manchesterunited": "manutd",
    "newcastleunited": "newcastle",
    "nottinghamforest": "nottmforest",
    "tottenhamhotspur": "spurs",
}


@dataclass(frozen=True)
class CurrentMarketShadowResult:
    status: str
    artifact_path: Path
    reused: bool
    mapped_fixture_count: int
    current_gameweek_fixture_count: int
    quote_count: int


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return _utc(value, "timestamp").isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _normal(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _quota_headers(response) -> dict[str, str]:
    headers = getattr(response, "headers", {})
    return {
        key: str(headers[key])
        for key in ("x-requests-last", "x-requests-remaining", "x-requests-used")
        if key in headers
    }


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _production_metadata(run_directory: Path) -> dict:
    """Read immutable V22 provenance without touching its bundle or outputs."""
    try:
        manifest = json.loads(
            (Path(run_directory) / "run_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(manifest, dict):
        return {}
    simulation = manifest.get("simulation")
    simulation = simulation if isinstance(simulation, dict) else {}
    return {
        "pipeline_version": manifest.get("pipeline_version"),
        "model_versions": manifest.get("model_versions", []),
        "simulator_version": simulation.get("simulator_version"),
        "simulation_count": simulation.get("simulations_per_fixture"),
        "base_seed": simulation.get("base_seed"),
        "seed_strategy": simulation.get("seed_strategy"),
    }


def _existing(path: Path) -> CurrentMarketShadowResult | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("artifact_version") != MARKET_SHADOW_ARTIFACT_VERSION:
        return None
    return CurrentMarketShadowResult(
        status=str(payload.get("status", "UNKNOWN")),
        artifact_path=path,
        reused=True,
        mapped_fixture_count=int(payload.get("coverage", {}).get("mapped_fixture_count", 0)),
        current_gameweek_fixture_count=int(payload.get("coverage", {}).get("current_gameweek_fixture_count", 0)),
        quote_count=int(payload.get("coverage", {}).get("quote_count", 0)),
    )


def _is_fresh(path: Path, *, now: datetime, maximum_age: timedelta) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        return False
    age = _utc(now, "clock") - generated_at.astimezone(timezone.utc)
    return timedelta(0) <= age <= maximum_age


def _next_artifact_path(destination: Path, *, now: datetime) -> Path:
    stamp = _utc(now, "clock").strftime("%Y%m%dT%H%M%SZ")
    candidate = destination / f"market_shadow_{stamp}.json"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = destination / f"market_shadow_{stamp}_{suffix}.json"
    return candidate


def _fresh_observation(
    destination: Path,
    *,
    now: datetime,
    model_prediction_timestamp: datetime,
) -> CurrentMarketShadowResult | None:
    """Return only a fresh observation made from this exact model forecast."""
    for path in sorted(destination.glob("market_shadow_*.json"), reverse=True):
        existing = _existing(path)
        if existing is None or not _is_fresh(
            path, now=now, maximum_age=DEFAULT_SNAPSHOT_FRESHNESS,
        ):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_at = _parse_artifact_time(
                payload.get("model_prediction_timestamp"),
                "model_prediction_timestamp",
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if source_at == model_prediction_timestamp:
            return existing
    return None


def _parse_artifact_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO timestamp")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)


def _fixture_rows(
    fixtures: Iterable[object],
    *,
    current_gameweek: int,
    shadow_prediction_timestamp: datetime,
) -> tuple[object, ...]:
    at = _utc(shadow_prediction_timestamp, "shadow_prediction_timestamp")
    output = []
    for fixture in fixtures:
        kickoff = getattr(fixture, "kickoff", None)
        if (
            getattr(fixture, "target_gameweek", None) == current_gameweek
            and isinstance(kickoff, datetime)
            and _utc(kickoff, "fixture.kickoff") > at
        ):
            output.append(fixture)
    return tuple(sorted(output, key=lambda item: (item.kickoff, item.fixture_id)))


def _team_resolver(
    fixtures: Sequence[object],
    canonical_team_names: Mapping[str, str],
) -> tuple[Callable[[str], str | None], Mapping[str, str]]:
    expected_team_ids = {
        team_id
        for fixture in fixtures
        for team_id in (fixture.home_team_id, fixture.away_team_id)
    }
    index: dict[str, str | None] = {}
    for team_id, name in canonical_team_names.items():
        if team_id not in expected_team_ids:
            continue
        key = _normal(name)
        if not key:
            continue
        if key in index and index[key] != team_id:
            index[key] = None
        else:
            index[key] = team_id

    aliases: dict[str, str] = {}
    for provider_name, canonical_name in _PROVIDER_TEAM_ALIASES.items():
        team_id = index.get(canonical_name)
        if team_id is not None:
            aliases[provider_name] = team_id

    resolution_kind = {
        key: "EXACT_CANONICAL_TEAM_NAME"
        for key, value in index.items()
        if value is not None
    }
    resolution_kind.update({
        key: "EXPLICIT_PREMIER_LEAGUE_ALIAS"
        for key in aliases
    })

    def resolve(name: str) -> str | None:
        key = _normal(name)
        return index.get(key, aliases.get(key))

    return resolve, resolution_kind


def _player_resolver(players: Sequence[object]) -> Callable[[str], str | None]:
    index: dict[str, str | None] = {}
    for player in players:
        player_id = getattr(player, "player_id", None)
        if not isinstance(player_id, str) or not player_id:
            continue
        payload = getattr(player, "provider_payload", {})
        if not isinstance(payload, Mapping):
            payload = {}
        names = (
            getattr(player, "display_name", None),
            payload.get("web_name"),
            payload.get("second_name"),
            " ".join(
                str(payload.get(key, "")).strip()
                for key in ("first_name", "second_name")
            ).strip(),
        )
        for name in names:
            key = _normal(name)
            if not key:
                continue
            if key in index and index[key] != player_id:
                index[key] = None
            else:
                index[key] = player_id

    def resolve(name: str) -> str | None:
        return index.get(_normal(name))

    return resolve


def _fixture_mapping_records(
    *,
    fixtures: Sequence[object],
    discovery: object,
    audit: object,
    team_resolver: Callable[[str], str | None],
    resolution_kind: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """Explain every canonical fixture's mapping state without fuzzy matching."""
    event_by_id = {
        item.provider_event_id: item
        for item in getattr(discovery, "events", ())
    }
    match_by_fixture = {
        item.canonical_fixture_id: item
        for item in getattr(audit, "matches", ())
    }
    records: list[dict[str, object]] = []
    for fixture in fixtures:
        match = match_by_fixture.get(fixture.fixture_id)
        if match is not None:
            event = event_by_id[match.provider_event_id]
            records.append({
                "canonical_fixture_id": fixture.fixture_id,
                "provider_event_id": match.provider_event_id,
                "status": "MAPPED",
                "reason": "TEAM_SIDES_AND_KICKOFF_MATCHED",
                "home_team_resolution": resolution_kind.get(
                    _normal(event.home_team), "EXACT_CANONICAL_TEAM_NAME",
                ),
                "away_team_resolution": resolution_kind.get(
                    _normal(event.away_team), "EXACT_CANONICAL_TEAM_NAME",
                ),
                "kickoff_delta_seconds": abs(
                    (fixture.kickoff - event.commence_time).total_seconds(),
                ),
            })
            continue

        matching_sides = [
            event for event in getattr(discovery, "events", ())
            if team_resolver(event.home_team) == fixture.home_team_id
            and team_resolver(event.away_team) == fixture.away_team_id
        ]
        if matching_sides:
            reason = "PROVIDER_EVENT_KICKOFF_MISMATCH"
            event_ids = [item.provider_event_id for item in matching_sides]
        else:
            reason = "PROVIDER_EVENT_MISSING"
            event_ids = []
        records.append({
            "canonical_fixture_id": fixture.fixture_id,
            "provider_event_id": None,
            "status": "UNMAPPED",
            "reason": reason,
            "candidate_provider_event_ids": event_ids,
        })
    return tuple(records)


def _artifact_payload(
    *,
    status: str,
    run_directory: Path,
    season: str,
    current_gameweek: int,
    model_prediction_timestamp: datetime,
    market_snapshot_timestamp: datetime | None,
    shadow_prediction_timestamp: datetime,
    coverage: Mapping[str, object],
    fixture_snapshots: Sequence[Mapping[str, object]],
    comparison: MarketShadowReport | None,
    normalized_probabilities: Sequence[object],
    failure_reason: str | None = None,
    generated_at: datetime | None = None,
) -> dict:
    return {
        "artifact_version": MARKET_SHADOW_ARTIFACT_VERSION,
        "generated_at": _utc(generated_at or datetime.now(timezone.utc), "generated_at"),
        "status": status,
        "production_influence": False,
        "production_run_directory": str(run_directory),
        "production_metadata": _production_metadata(run_directory),
        "season": season,
        "current_gameweek": current_gameweek,
        # V22 is immutable.  This is a later, independently auditable shadow
        # observation that combines its forecast with a fresh market snapshot.
        "model_prediction_timestamp": _utc(
            model_prediction_timestamp, "model_prediction_timestamp",
        ),
        "market_snapshot_timestamp": (
            None if market_snapshot_timestamp is None
            else _utc(market_snapshot_timestamp, "market_snapshot_timestamp")
        ),
        "shadow_prediction_timestamp": _utc(
            shadow_prediction_timestamp, "shadow_prediction_timestamp",
        ),
        "provider": PROVIDER,
        "requested_markets": list(SUPPORTED_MARKETS),
        "coverage": dict(coverage),
        "fixture_snapshots": list(fixture_snapshots),
        "normalized_market_probabilities": list(normalized_probabilities),
        "comparison": comparison,
        "failure_reason": failure_reason,
    }


def collect_current_gameweek_market_shadow(
    *,
    adapter: TheOddsApiAdapter,
    project_root: Path,
    run_directory: Path,
    season: str,
    current_gameweek: int,
    prediction_timestamp: datetime,
    fixtures: Sequence[object],
    event_projections: Sequence[object],
    players: Sequence[object],
    canonical_team_names: Mapping[str, str],
    progress: Callable[[str], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> CurrentMarketShadowResult:
    """Collect current-GW player props after an already successful V22 run.

    Each mapped fixture receives at most one props call.  All five existing
    blend candidates are calculated from that one immutable response.
    """
    model_at = _utc(prediction_timestamp, "model_prediction_timestamp")
    now = _utc((clock or (lambda: datetime.now(timezone.utc)))(), "clock")
    initial_shadow_at = max(model_at, now)
    progress = progress or (lambda _: None)
    run_directory = Path(run_directory)
    destination = (
        Path(project_root)
        / "data"
        / "processed"
        / "market_shadow"
        / season.replace("/", "-")
        / run_directory.name
    )
    existing = _fresh_observation(
        destination,
        now=now,
        model_prediction_timestamp=model_at,
    )
    if existing is not None:
        progress(f"[shadow-market] snapshot reused: {existing.artifact_path}")
        return existing
    destination.mkdir(parents=True, exist_ok=True)
    artifact_path = _next_artifact_path(destination, now=now)

    current = _fixture_rows(
        fixtures,
        current_gameweek=current_gameweek,
        shadow_prediction_timestamp=initial_shadow_at,
    )
    coverage: dict[str, object] = {
        "current_gameweek_fixture_count": len(current),
        "mapped_fixture_count": 0,
        "props_requested_fixture_count": 0,
        "props_available_fixture_count": 0,
        "quote_count": 0,
        "missing_fixture_ids": [item.fixture_id for item in current],
        "player_prop_coverage": "NONE",
    }
    fixture_snapshots: list[dict] = []

    if not current:
        payload = _artifact_payload(
            status="SKIPPED",
            run_directory=run_directory,
            season=season,
            current_gameweek=current_gameweek,
            model_prediction_timestamp=model_at,
            market_snapshot_timestamp=None,
            shadow_prediction_timestamp=initial_shadow_at,
            coverage=coverage,
            fixture_snapshots=fixture_snapshots,
            comparison=None,
            normalized_probabilities=(),
            failure_reason="No future fixtures are available for the selected current gameweek.",
            generated_at=now,
        )
        _write(artifact_path, payload)
        return CurrentMarketShadowResult("SKIPPED", artifact_path, False, 0, 0, 0)

    try:
        progress("[shadow-market] discovering events")
        discovery = adapter.get_events(
            commence_time_from=min(item.kickoff for item in current) - timedelta(hours=12),
            commence_time_to=max(item.kickoff for item in current) + timedelta(hours=12),
        )
        progress(f"[shadow-market] snapshot: {discovery.retrieved_at.isoformat()}")
        team_resolver, resolution_kind = _team_resolver(
            current, canonical_team_names,
        )
        audit = match_events_to_canonical_fixtures(
            discovery,
            team_resolver=team_resolver,
            canonical_fixtures=tuple(
                CanonicalFixtureCandidate(
                    fixture_id=item.fixture_id,
                    home_team_id=item.home_team_id,
                    away_team_id=item.away_team_id,
                    kickoff=item.kickoff,
                )
                for item in current
            ),
        )
    except TheOddsApiError as exc:
        progress(f"[shadow-market] FAILED/SKIPPED: {type(exc).__name__}")
        progress("[current] production bundle remains valid")
        payload = _artifact_payload(
            status="FAILED",
            run_directory=run_directory,
            season=season,
            current_gameweek=current_gameweek,
            model_prediction_timestamp=model_at,
            market_snapshot_timestamp=None,
            shadow_prediction_timestamp=initial_shadow_at,
            coverage=coverage,
            fixture_snapshots=fixture_snapshots,
            comparison=None,
            normalized_probabilities=(),
            failure_reason=type(exc).__name__,
            generated_at=now,
        )
        _write(artifact_path, payload)
        return CurrentMarketShadowResult("FAILED", artifact_path, False, 0, len(current), 0)

    matches = tuple(audit.matches)
    coverage["mapped_fixture_count"] = len(matches)
    coverage["unmapped_fixture_ids"] = sorted(
        {item.fixture_id for item in current}
        - {item.canonical_fixture_id for item in matches}
    )
    coverage["event_identity_audit"] = audit
    coverage["fixture_mapping"] = _fixture_mapping_records(
        fixtures=current,
        discovery=discovery,
        audit=audit,
        team_resolver=team_resolver,
        resolution_kind=resolution_kind,
    )
    progress(f"[shadow-market] mapped fixtures: {len(matches)}/{len(current)}")
    progress(f"[shadow-market] coverage: {len(matches)}/{len(current)}")

    event_by_fixture = {
        item.fixture_id: item
        for item in event_projections
        if getattr(item, "fixture_id", None) in {row.fixture_id for row in current}
    }
    player_resolver = _player_resolver(players)
    fixture_by_id = {item.fixture_id: item for item in current}
    all_quotes = []
    market_source_timestamps = [
        discovery.snapshot_timestamp or discovery.retrieved_at,
    ]
    mapped_fixture_ids = {item.canonical_fixture_id for item in matches}
    for index, match in enumerate(matches, 1):
        progress(f"[shadow-market] fetching props {index}/{len(matches)}")
        coverage["props_requested_fixture_count"] = index
        snapshot = {
            "canonical_fixture_id": match.canonical_fixture_id,
            "provider_event_id": match.provider_event_id,
            "provider_commence_time": match.provider_commence_time,
            "canonical_kickoff": fixture_by_id[match.canonical_fixture_id].kickoff,
            "requested_markets": list(SUPPORTED_MARKETS),
        }
        try:
            result = adapter.get_event_odds(event_id=match.provider_event_id)
            parsed = parse_market_quotes(
                result,
                canonical_fixture_id=match.canonical_fixture_id,
                player_resolver=player_resolver,
            )
        except TheOddsApiError as exc:
            snapshot.update({"status": "FAILED", "failure_reason": type(exc).__name__})
            fixture_snapshots.append(snapshot)
            continue
        snapshot.update({
            "status": "AVAILABLE" if parsed.quotes else "NO_SUPPORTED_PLAYER_PROPS",
            "fetch_timestamp": result.retrieved_at,
            "snapshot_timestamp": result.snapshot_timestamp or result.retrieved_at,
            "from_cache": result.from_cache,
            "raw_snapshot_id": (
                result.raw_snapshot.snapshot_id
                if result.raw_snapshot is not None
                else None
            ),
            "api_quota": _quota_headers(result.response),
            "quote_count": len(parsed.quotes),
            "quote_timestamps": sorted({quote.quoted_at for quote in parsed.quotes}),
            "unresolved_players": list(parsed.unresolved_players),
            "skipped_unsupported_markets": parsed.skipped_unsupported_markets,
        })
        fixture_snapshots.append(snapshot)
        market_source_timestamps.append(
            result.snapshot_timestamp or result.retrieved_at,
        )
        market_source_timestamps.extend(
            quote.quoted_at for quote in parsed.quotes
        )
        all_quotes.extend(parsed.quotes)

    market_at = max(_utc(item, "market source timestamp") for item in market_source_timestamps)
    shadow_at = max(model_at, now, market_at)
    pit_eligible_fixture_ids = {
        fixture_id
        for fixture_id, fixture in fixture_by_id.items()
        if fixture.kickoff > shadow_at
    }
    for snapshot in fixture_snapshots:
        if snapshot["canonical_fixture_id"] not in pit_eligible_fixture_ids:
            snapshot["pit_status"] = "POST_KICKOFF_REJECTED"
        else:
            snapshot["pit_status"] = "PRE_KICKOFF"
    pit_quotes = [
        quote for quote in all_quotes
        if quote.fixture_id in pit_eligible_fixture_ids
        and quote.quoted_at <= shadow_at
    ]
    coverage["quote_count"] = len(all_quotes)
    coverage["pit_usable_quote_count"] = len(pit_quotes)
    coverage["market_snapshot_timestamp"] = market_at
    coverage["shadow_prediction_timestamp"] = shadow_at
    coverage["post_kickoff_fixture_ids"] = sorted(
        set(fixture_by_id) - pit_eligible_fixture_ids,
    )
    coverage["props_available_fixture_count"] = sum(
        item.get("status") == "AVAILABLE" for item in fixture_snapshots
    )
    coverage["pit_usable_props_fixture_count"] = sum(
        item.get("status") == "AVAILABLE"
        and item.get("pit_status") == "PRE_KICKOFF"
        for item in fixture_snapshots
    )
    coverage["missing_fixture_ids"] = sorted(
        {item.fixture_id for item in current}
        - {
            item["canonical_fixture_id"]
            for item in fixture_snapshots
            if item.get("status") == "AVAILABLE"
        }
    )
    if pit_quotes:
        selected = select_pit_quotes(
            pit_quotes, prediction_timestamp=shadow_at, max_age=timedelta(hours=6),
        )
        fair = devig_selected_quotes(selected.quotes, allow_one_sided=True)
        normalized = aggregate_market_probabilities(
            fair.probabilities,
            prediction_timestamp=shadow_at,
            max_age=timedelta(hours=6),
        )
        current_events = tuple(
            event_by_fixture[fixture_id]
            for fixture_id in sorted(mapped_fixture_ids)
            if fixture_id in event_by_fixture and fixture_id in pit_eligible_fixture_ids
        )
        progress("[shadow-market] evaluating weights")
        for weight in ("0.00", "0.25", "0.50", "0.75", "1.00"):
            progress(f"[shadow-market] evaluating w={weight}")
        comparison = build_market_shadow_report(
            current_events,
            pit_quotes,
            prediction_timestamp=shadow_at,
            model_prediction_timestamp=model_at,
        )
        coverage["player_prop_coverage"] = (
            f"{comparison.players_with_market_prior}/{len(comparison.players)}"
        )
        progress(
            "[shadow-market] player-prop coverage: "
            f"{coverage['player_prop_coverage']}"
        )
        status = "SUCCESS" if not coverage["missing_fixture_ids"] else "PARTIAL"
    else:
        normalized = ()
        comparison = None
        status = "SKIPPED"
        coverage["player_prop_coverage"] = "0/0"
        progress("[shadow-market] player-prop coverage: unavailable")

    payload = _artifact_payload(
        status=status,
        run_directory=run_directory,
        season=season,
        current_gameweek=current_gameweek,
        model_prediction_timestamp=model_at,
        market_snapshot_timestamp=market_at,
        shadow_prediction_timestamp=shadow_at,
        coverage=coverage,
        fixture_snapshots=fixture_snapshots,
        comparison=comparison,
        normalized_probabilities=normalized,
        failure_reason=None,
        generated_at=now,
    )
    _write(artifact_path, payload)
    progress(f"[shadow-market] snapshot saved: {artifact_path}")
    progress("[shadow-market] production influence: false")
    return CurrentMarketShadowResult(
        status,
        artifact_path,
        False,
        len(matches),
        len(current),
        len(all_quotes),
    )


def write_market_shadow_skipped(
    *,
    project_root: Path,
    run_directory: Path,
    season: str,
    current_gameweek: int,
    prediction_timestamp: datetime,
    reason: str,
    clock: Callable[[], datetime] | None = None,
) -> CurrentMarketShadowResult:
    """Persist a non-overwriting explicit skip when credentials are absent."""
    destination = (
        Path(project_root) / "data" / "processed" / "market_shadow"
        / season.replace("/", "-") / Path(run_directory).name
    )
    now = _utc((clock or (lambda: datetime.now(timezone.utc)))(), "clock")
    model_at = _utc(prediction_timestamp, "model_prediction_timestamp")
    existing = _fresh_observation(
        destination, now=now, model_prediction_timestamp=model_at,
    )
    if existing is not None:
        return existing
    destination.mkdir(parents=True, exist_ok=True)
    artifact_path = _next_artifact_path(destination, now=now)
    _write(artifact_path, _artifact_payload(
        status="SKIPPED",
        run_directory=Path(run_directory),
        season=season,
        current_gameweek=current_gameweek,
        model_prediction_timestamp=model_at,
        market_snapshot_timestamp=None,
        shadow_prediction_timestamp=max(model_at, now),
        coverage={
            "current_gameweek_fixture_count": 0,
            "mapped_fixture_count": 0,
            "props_requested_fixture_count": 0,
            "props_available_fixture_count": 0,
            "quote_count": 0,
            "player_prop_coverage": "NONE",
        },
        fixture_snapshots=(),
        comparison=None,
        normalized_probabilities=(),
        failure_reason=reason,
        generated_at=now,
    ))
    return CurrentMarketShadowResult("SKIPPED", artifact_path, False, 0, 0, 0)

