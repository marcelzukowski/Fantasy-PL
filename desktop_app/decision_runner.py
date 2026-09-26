"""Child-process entry point that adapts desktop state to the existing shadow runner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from fpl_engine.optimizer import OptimizerError, SquadState, validate_squad
from fpl_engine.shadow import ShadowRunError, load_squad_state, run_shadow
from fpl_engine.strategy import StrategicPlannerV3, StrategicPlannerV3Error
from fpl_engine.reports import DecisionReportV2, ReportReference, ReportSchemaError
from fpl_engine.planning import (
    ChipOpportunityForecastError, DecisionInput, DecisionInputError,
    build_chip_opportunity_forecast, write_chip_opportunity_forecast, build_player_availability_snapshot, write_player_availability_snapshot, PlayerAvailabilityRiskError,
    build_player_minutes_history_snapshot, write_player_minutes_history_snapshot, recent_minutes_evidence, PlayerMinutesHistoryError,
    OfficialPlayerHistoryAcquirer, OfficialPlayerHistoryError, write_official_player_history_acquisition,
)

from .decision_orchestration import planning_context_for_state, validate_decision_bundle
from .transfer_plans import TransferPlanView, horizon_transfer_plans


class DesktopDecisionError(ValueError):
    pass


def _object(path: Path, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopDecisionError(f"Cannot read {label}.") from exc
    if not isinstance(value, dict):
        raise DesktopDecisionError(f"{label} must contain an object.")
    return value


def _chip_state(used: object) -> dict:
    if not isinstance(used, dict):
        used = {}
    return {
        "wildcard_h1": not bool(used.get("wildcard_h1")),
        "wildcard_h2": not bool(used.get("wildcard_h2")),
        "free_hit_h1": not bool(used.get("free_hit_h1")),
        "free_hit_h2": not bool(used.get("free_hit_h2")),
        "bench_boost_h1": not bool(used.get("bench_boost_h1")),
        "bench_boost_h2": not bool(used.get("bench_boost_h2")),
        "triple_captain_h1": not bool(used.get("triple_captain_h1")),
        "triple_captain_h2": not bool(used.get("triple_captain_h2")),
        "last_free_hit_gameweek": None,
    }


def shadow_input(desktop: dict, bundle: dict) -> dict:
    player_ids = desktop.get("player_ids")
    if not isinstance(player_ids, list) or len(player_ids) != 15 or len(set(player_ids)) != 15:
        raise DesktopDecisionError("Decision engine requires an explicit 15-player squad.")
    if str(desktop.get("season")) != str(bundle.get("season")) or int(desktop.get("gameweek", -1)) != int(bundle.get("current_gameweek", -2)):
        raise DesktopDecisionError("Saved projections do not match the selected season and gameweek.")
    purchase = desktop.get("purchase_prices_tenths")
    selling = desktop.get("selling_prices_tenths")
    if not isinstance(purchase, dict) or not isinstance(selling, dict):
        raise DesktopDecisionError("Personal purchase and selling prices are required before a decision can run.")
    missing_purchase = [player_id for player_id in player_ids if player_id not in purchase]
    missing_selling = [player_id for player_id in player_ids if player_id not in selling]
    if missing_purchase or missing_selling:
        details = []
        if missing_purchase:
            details.append("purchase prices: " + ", ".join(sorted(missing_purchase)))
        if missing_selling:
            details.append("selling prices: " + ", ".join(sorted(missing_selling)))
        raise DesktopDecisionError("Account prices are incomplete (" + "; ".join(details) + ").")
    pool = {str(item.get("player_id")): item for item in bundle.get("candidate_pool", []) if isinstance(item, dict)}
    players = []
    for player_id in player_ids:
        row = pool.get(str(player_id))
        if row is None:
            raise DesktopDecisionError(f"Player {player_id} is unavailable in the saved projection universe.")
        players.append({
            "player_id": str(player_id), "position": row.get("position"), "club_id": row.get("club_id"),
            "purchase_price": int(purchase[player_id]), "current_price": int(row.get("current_price")),
            "selling_price": int(selling[player_id]),
        })
    return {
        "prediction_timestamp": bundle.get("prediction_timestamp"), "season": bundle.get("season"),
        "current_gameweek": bundle.get("current_gameweek"), "players": players,
        "bank": int(desktop.get("bank_tenths")), "free_transfers": int(desktop.get("free_transfers")),
        "chip_state": _chip_state(desktop.get("chips_used")),
    }


def _display_metadata(bundle_path: Path, bundle: dict) -> dict[str, dict]:
    names: dict[str, str] = {}
    current_players = bundle_path.parent / "current_players.json"
    try:
        rows = json.loads(current_players.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("player_id"):
            provider = row.get("provider_payload") if isinstance(row.get("provider_payload"), dict) else {}
            names[str(row["player_id"])] = str(row.get("display_name") or row.get("name") or provider.get("web_name") or row["player_id"])
    result = {}
    for row in bundle.get("candidate_pool", []):
        if not isinstance(row, dict) or not row.get("player_id"):
            continue
        player_id = str(row["player_id"])
        result[player_id] = {
            "name": names.get(player_id, player_id), "position": row.get("position"),
            "current_price": row.get("current_price"),
        }
    return result


def _strategy_key(title: str) -> str:
    return {
        "Best short-term": "short_term",
        "Best balanced": "balanced",
        "Best long-term": "long_term",
    }.get(title, "")


def _transfer_identity(outgoing, incoming) -> dict[str, list[str]]:
    """Stable, order-independent identity for one existing transfer plan."""
    return {
        "transfers_out": sorted(str(value) for value in outgoing),
        "transfers_in": sorted(str(value) for value in incoming),
    }


def _strategy_preview_payload(*, plan, decision_input: DecisionInput) -> dict:
    """Apply one existing transfer plan with the run-scoped shared evaluator."""
    state, pool, projections, rules = decision_input.state, decision_input.player_pool, decision_input.projections, decision_input.rules
    outgoing = tuple(plan.transfers_out)
    incoming = tuple(plan.transfers_in)
    owned = {player.player_id: player for player in state.players}
    pool_by_id = {player.player_id: player for player in pool}
    if any(player_id not in owned for player_id in outgoing):
        raise DesktopDecisionError("A selected strategy removes a player outside the current squad.")
    if any(player_id not in pool_by_id for player_id in incoming):
        raise DesktopDecisionError("A selected strategy includes a player outside the production pool.")
    working = dict(owned)
    for player_id in outgoing:
        del working[player_id]
    for player_id in incoming:
        working[player_id] = pool_by_id[player_id]
    if plan.resulting_bank is None:
        raise DesktopDecisionError("A selected strategy lacks its validated budget result.")

    if plan.free_transfers_after is None:
        raise DesktopDecisionError("A selected strategy lacks its validated free-transfer result.")

    preview_state = SquadState(
        players=tuple(working.values()),
        bank=plan.resulting_bank,
        # This lineup is selected for the current gameweek.  The plan's
        # rollover figure belongs to the next gameweek and cannot be used as
        # today's SquadState FT value (a one-transfer plan with 1 FT would
        # otherwise become an invalid zero-FT state).
        free_transfers=state.free_transfers,
        chips=state.chips,
        current_gameweek=state.current_gameweek,
        season=state.season,
        rule_version=state.rule_version,
        prediction_timestamp=state.prediction_timestamp,
    )
    try:
        validate_squad(preview_state, rules)
        lineup = decision_input.lineup_for(preview_state, target_gameweek=state.current_gameweek)
    except OptimizerError as exc:
        raise DesktopDecisionError("A selected strategy cannot produce a valid current-GW lineup.") from exc
    return {
        "transfers_out": list(outgoing), "transfers_in": list(incoming),
        "resulting_bank": plan.resulting_bank,
        "free_transfers_after": plan.free_transfers_after,
        "starting_xi": list(lineup.starting_xi), "bench_order": list(lineup.bench_order),
        "captain": lineup.captain_id, "vice_captain": lineup.vice_captain_id,
    }


def _strategic_action_payload(recommendation: dict) -> dict:
    """Expose the existing V2 action without comparing it to V1 metrics."""
    outgoing = recommendation.get("transfers_out", ())
    incoming = recommendation.get("transfers_in", ())
    if not isinstance(outgoing, list) or not isinstance(incoming, list):
        raise DesktopDecisionError("Optimizer V2 returned an incomplete strategic action.")
    action = str(recommendation.get("action", ""))
    if action not in {"ROLL_FT", "TRANSFER"}:
        raise DesktopDecisionError("Optimizer V2 returned an unsupported strategic action.")
    utility = None
    alternatives = recommendation.get("alternatives", ())
    if isinstance(alternatives, list):
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                continue
            if tuple(str(item) for item in alternative.get("transfers_out", ())) != tuple(str(item) for item in outgoing):
                continue
            if tuple(str(item) for item in alternative.get("transfers_in", ())) != tuple(str(item) for item in incoming):
                continue
            candidate = alternative.get("utility")
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                utility = float(candidate)
            break
    before = recommendation.get("free_transfers_before")
    after = recommendation.get("free_transfers_after")
    bank = recommendation.get("resulting_bank")
    if type(before) is not int or type(after) is not int or type(bank) is not int:
        raise DesktopDecisionError("Optimizer V2 returned incomplete transfer-state data.")
    return {
        "action": action,
        "transfers_out": [str(item) for item in outgoing],
        "transfers_in": [str(item) for item in incoming],
        "hit_cost": recommendation.get("hit_cost"),
        "resulting_bank": bank,
        "free_transfers_before": before,
        "free_transfers_after": after,
        "free_transfers_used": min(len(incoming), before),
        "roll_free_transfer": bool(recommendation.get("roll_free_transfer")),
        "utility": utility,
    }


def _strategic_plan(action: dict) -> TransferPlanView:
    """Adapt the serialized V2 action to the existing preview-only contract."""
    return TransferPlanView(
        label="Strategic", source="Optimizer V2",
        transfers_out=tuple(action["transfers_out"]), transfers_in=tuple(action["transfers_in"]),
        transfer_count=len(action["transfers_in"]),
        free_transfers_used=action["free_transfers_used"], hit_cost=action.get("hit_cost"),
        resulting_bank=action["resulting_bank"], free_transfers_after=action["free_transfers_after"],
        projected_gain=None, impact_1gw=None, impact_3gw=None, impact_6gw=None,
        roll_free_transfer=bool(action["roll_free_transfer"]),
    )


def _strategic_v3_plan(report: dict) -> TransferPlanView:
    """Adapt the V3 current action to the existing preview-only contract."""
    action = report.get("current_action")
    if not isinstance(action, dict):
        raise DesktopDecisionError("Strategic Planner V3 returned no current action.")
    outgoing = tuple(str(value) for value in action.get("transfers_out", ()))
    incoming = tuple(str(value) for value in action.get("transfers_in", ()))
    before = action.get("free_transfers_before")
    after = action.get("free_transfers_after")
    bank = action.get("resulting_bank")
    hit = action.get("hit_cost_points")
    if not all(type(value) is int for value in (before, after, bank, hit)):
        raise DesktopDecisionError("Strategic Planner V3 returned incomplete transfer-state data.")
    return TransferPlanView(
        label="V3 Strategic", source="Strategic Planner V3",
        transfers_out=outgoing, transfers_in=incoming, transfer_count=len(incoming),
        free_transfers_used=min(len(incoming), before), hit_cost=hit,
        resulting_bank=bank, free_transfers_after=after, projected_gain=None,
        impact_1gw=None, impact_3gw=None, impact_6gw=None,
        roll_free_transfer=str(action.get("action")) == "HOLD",
    )


def _add_action_ids(player_ids: set[str], action: object) -> None:
    if not isinstance(action, dict):
        return
    for key in ("transfers_out", "transfers_in"):
        values = action.get(key, ())
        if isinstance(values, (list, tuple)):
            player_ids.update(str(value) for value in values if value)


def _final_advisory_player_ids(*, decision_input: DecisionInput, recommendation: dict,
                                feasible_plans: list, strategic_v3: dict | None,
                                strategy_previews: dict[str, dict]) -> tuple[str, ...]:
    """Bound the optional Official FPL batch to already-frozen decision outputs."""
    player_ids = {str(player.player_id) for player in decision_input.state.players}
    _add_action_ids(player_ids, recommendation)
    for plan in feasible_plans:
        _add_action_ids(player_ids, plan)
    if isinstance(strategic_v3, dict):
        _add_action_ids(player_ids, strategic_v3.get("current_action"))
        for action in strategic_v3.get("path", ()):
            _add_action_ids(player_ids, action)
    for preview in strategy_previews.values():
        if not isinstance(preview, dict):
            continue
        _add_action_ids(player_ids, preview)
        for key in ("captain", "vice_captain"):
            if preview.get(key):
                player_ids.add(str(preview[key]))
        for key in ("starting_xi", "bench_order"):
            values = preview.get(key, ())
            if isinstance(values, (list, tuple)):
                player_ids.update(str(value) for value in values if value)
    owned = {str(player.player_id) for player in decision_input.state.players}
    top_targets = [
        player_id for player_id, projection in sorted(
            decision_input.projections.items(),
            key=lambda row: (-float(row[1].weighted_ev_next_6), row[0]),
        ) if player_id not in owned
    ][:10]
    player_ids.update(top_targets)
    return tuple(sorted(player_ids))


def _deadline_capture_status(deadline: str | None, *, observed_at: datetime) -> tuple[str, str | None]:
    """Gate optional network capture before any provider object is constructed."""
    if not deadline:
        return "SKIPPED_UNVERIFIED_DEADLINE", "Official deadline is unavailable; advisory history was not requested."
    try:
        parsed = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        cutoff = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return "SKIPPED_UNVERIFIED_DEADLINE", "Official deadline is invalid; advisory history was not requested."
    if observed_at >= cutoff:
        return "SKIPPED_AFTER_DEADLINE", "Official deadline has passed; advisory history was not requested."
    return "ELIGIBLE", None


def _existing_history_before_context(bundle_directory: Path, *, cutoff: datetime) -> tuple[tuple, dict, int]:
    """Load only an immutable manual receipt observed no later than the context."""
    candidates = list(Path(bundle_directory).glob("player_minutes_history_records_*.json"))
    legacy = Path(bundle_directory) / "player_minutes_history_records.json"
    if legacy.is_file():
        candidates.append(legacy)
    selected = None
    post_cutoff = 0
    for candidate in sorted(candidates):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            observed = payload.get("requested_at") if isinstance(payload, dict) else None
            observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00")) if isinstance(observed, str) else None
            if isinstance(payload, dict) and observed_at is not None and observed_at <= cutoff:
                selected = payload
            elif isinstance(payload, dict) and observed_at is not None:
                post_cutoff += 1
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
    if not isinstance(selected, dict):
        return (), {}, post_cutoff
    records = selected.get("appearances", ()) if isinstance(selected.get("appearances"), list) else ()
    provenance = {
        "source": "OFFICIAL_FPL",
        "raw_source_references": selected.get("raw_source_references", {}),
        "warnings": selected.get("warnings", ()),
        "acquisition_statistics": selected.get("statistics", {}),
        "source_snapshot_timestamp": selected.get("requested_at"),
        "acquisition_receipt": selected.get("acquisition_receipt"),
        "capture_status": "AVAILABLE",
    }
    return tuple(records), provenance, post_cutoff


def _advisory_snapshots(*, project_root: Path, prediction_bundle_path: Path,
                        decision_input: DecisionInput, player_ids: tuple[str, ...],
                        capture_advisory_history: bool, observed_at: datetime | None = None):
    """Create advisory-only snapshots after policy freeze, never before it."""
    now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    bundle_directory = prediction_bundle_path.parent
    history_records: tuple = ()
    history_provenance: dict = {
        "projection_run_id": decision_input.bundle_identity,
        "source": "LOCAL_OFFICIAL_FPL_CACHE",
        "production_influence": False,
        "requested_player_ids": list(player_ids),
        "requested_count": len(player_ids),
        "capture_status": "NOT_REQUESTED",
    }
    cutoff = datetime.fromisoformat(decision_input.planning_context.prediction_timestamp.replace("Z", "+00:00"))
    if capture_advisory_history:
        capture_status, warning = _deadline_capture_status(decision_input.planning_context.deadline, observed_at=now)
        history_provenance["capture_status"] = capture_status
        if warning:
            history_provenance["warnings"] = (warning,)
        if capture_status == "ELIGIBLE":
            print("DECISION_PROGRESS=collecting advisory player history", flush=True)
            try:
                # Network and scientific/provider dependencies stay in this
                # external worker; the packaged desktop shell only starts it.
                import httpx
                from fpl_engine.data.http_cache import HttpCache
                from fpl_engine.data.raw_store import RawStore
                from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter

                raw_store = RawStore(project_root / "data" / "raw")
                cache = HttpCache(project_root / "data" / "interim" / "http_cache", clock=lambda: now)
                with httpx.Client() as client:
                    adapter = OfficialFPLAdapter(
                        client=client, cache=cache, raw_store=raw_store,
                        clock=lambda: now,
                    )
                    acquisition = OfficialPlayerHistoryAcquirer(
                        adapter=adapter, raw_store=raw_store, clock=lambda: now,
                    ).refresh(
                        bundle_directory=bundle_directory,
                        season=decision_input.state.season,
                        gameweek=decision_input.state.current_gameweek,
                        squad_player_ids=tuple(player.player_id for player in decision_input.state.players),
                        top_targets=0,
                        extra_player_ids=player_ids,
                    )
                receipt = write_official_player_history_acquisition(bundle_directory, acquisition)
                history_records = tuple(acquisition.appearances)
                requested = int(acquisition.statistics.get("players_requested", 0))
                failures = int(acquisition.statistics.get("failures", 0))
                history_provenance.update({
                    "source": "OFFICIAL_FPL",
                    "raw_source_references": acquisition.raw_source_references,
                    "warnings": acquisition.warnings,
                    "acquisition_statistics": acquisition.statistics,
                    "source_snapshot_timestamp": acquisition.requested_at,
                    "acquisition_receipt": str(receipt.resolve().relative_to(project_root.resolve())),
                    "capture_status": "PARTIAL" if failures or requested < len(player_ids) else "AVAILABLE",
                })
            except Exception as exc:
                # The decision and all frozen policies remain valid even when
                # optional provider acquisition cannot complete.
                history_provenance.update({
                    "capture_status": "UNAVAILABLE",
                    "warnings": (f"Official advisory history unavailable: {type(exc).__name__}.",),
                })
    else:
        records, provenance, post_cutoff = _existing_history_before_context(bundle_directory, cutoff=cutoff)
        history_records = records
        if provenance:
            history_provenance.update(provenance)
        if post_cutoff:
            history_provenance["warnings"] = tuple(history_provenance.get("warnings", ())) + (
                f"Excluded {post_cutoff} Official FPL history refresh record(s) observed after this decision cutoff.",
            )

    raw_players = json.loads((bundle_directory / "current_players.json").read_text(encoding="utf-8"))
    metadata = {
        str(row.get("player_id")): row for row in raw_players
        if isinstance(row, dict) and row.get("player_id") is not None
    } if isinstance(raw_players, list) else {}
    freshness_rows = json.loads((bundle_directory / "source_freshness.json").read_text(encoding="utf-8"))
    bootstrap = next(
        (row for row in freshness_rows if isinstance(row, dict) and row.get("entity") == "bootstrap_static"),
        {},
    ) if isinstance(freshness_rows, list) else {}
    source_observed_at = bootstrap.get("known_at")

    minutes_history = build_player_minutes_history_snapshot(
        decision_input, player_ids=player_ids, appearances=history_records, provenance=history_provenance,
        advisory_cutoff=now if capture_advisory_history and history_provenance.get("capture_status") in {"AVAILABLE", "PARTIAL"} else None,
    )
    advisory_input = decision_input.with_advisory("player_minutes_history_snapshot", minutes_history)
    minutes_history_path = write_player_minutes_history_snapshot(project_root, minutes_history)
    minutes_reference = {
        "path": str(minutes_history_path.resolve().relative_to(project_root.resolve())),
        "sha256": sha256(minutes_history_path.read_bytes()).hexdigest(),
    }
    availability = build_player_availability_snapshot(
        advisory_input, player_metadata=metadata, player_ids=player_ids,
        source_observed_at=source_observed_at, source_provenance=bootstrap,
        recent_minutes_by_player=recent_minutes_evidence(minutes_history),
        advisory_cutoff=now if capture_advisory_history and history_provenance.get("capture_status") in {"AVAILABLE", "PARTIAL"} else None,
    )
    availability_input = advisory_input.with_advisory("player_availability_snapshot", availability)
    availability_path = write_player_availability_snapshot(project_root, availability)
    availability_reference = {
        "path": str(availability_path.resolve().relative_to(project_root.resolve())),
        "sha256": sha256(availability_path.read_bytes()).hexdigest(),
    }
    return availability_input, availability_reference, minutes_reference


def run_desktop_decision(*, desktop_state_path: Path, prediction_bundle_path: Path, output_dir: Path,
                         project_root: Path, capture_advisory_history: bool = False) -> Path:
    desktop = _object(desktop_state_path, "desktop squad state")
    bundle = validate_decision_bundle(
        project_root,
        prediction_bundle_path,
        season=str(desktop.get("season")),
        gameweek=int(desktop.get("gameweek", -1)),
        require_canonical_path=False,
    )
    payload = shadow_input(desktop, bundle)
    try:
        planning_context = planning_context_for_state(
            project_root,
            desktop,
            prediction_bundle_path,
            require_canonical_path=False,
        )
    except Exception as exc:
        raise DesktopDecisionError(str(exc)) from exc
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fpl-desktop-decision-") as temporary:
        source = Path(temporary) / "shadow-input.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        try:
            strategy_state, pool, projections, pipeline, warnings, rules, freshness = load_squad_state(
                source, project_root=project_root, prediction_bundle_path=prediction_bundle_path,
            )
            decision_input = DecisionInput.create(
                planning_context=planning_context, state=strategy_state, player_pool=pool,
                projections=projections, pipeline=pipeline, warnings=warnings, rules=rules,
                freshness=freshness, bundle_identity=planning_context.projection_run_id,
            )
        except (ShadowRunError, DecisionInputError) as exc:
            raise DesktopDecisionError("Decision output cannot build a shared validated engine input.") from exc
        try:
            machine, _ = run_shadow(source, project_root=project_root, output_dir=output_dir,
                                    prediction_bundle_path=prediction_bundle_path, decision_input=decision_input)
        except ShadowRunError as exc:
            raise DesktopDecisionError(str(exc)) from exc
    report = _object(machine, "shadow decision report")
    recommendation = report.get("recommendations", {}).get("greedy_1gw")
    if not isinstance(recommendation, dict):
        raise DesktopDecisionError("The decision engine did not return its Greedy 1GW recommendation.")
    optimizer_v1 = report.get("recommendations", {}).get("optimizer_v1", {})
    feasible_plans = optimizer_v1.get("alternatives", []) if isinstance(optimizer_v1, dict) else []
    if not isinstance(feasible_plans, list):
        feasible_plans = []
    optimizer_v2 = report.get("recommendations", {}).get("optimizer_v2")
    if not isinstance(optimizer_v2, dict):
        raise DesktopDecisionError("The decision engine did not return its Optimizer V2 strategic action.")
    strategic_action = _strategic_action_payload(optimizer_v2)
    horizon_report = {"recommendation": recommendation, "feasible_plans": feasible_plans}
    strategy_previews: dict[str, dict] = {}
    strategy_preview_identities: dict[str, dict[str, list[str]]] = {}
    strategy_unavailable: dict[str, str] = {}
    created_at = datetime.now(timezone.utc)
    chip_forecast_reference = None
    chip_forecast = None
    try:
        chip_forecast = build_chip_opportunity_forecast(decision_input, generated_at=created_at)
        forecast_path = write_chip_opportunity_forecast(project_root, chip_forecast)
        chip_forecast_reference = {
            "path": str(forecast_path.resolve().relative_to(project_root.resolve())),
            "sha256": sha256(forecast_path.read_bytes()).hexdigest(),
            "schema_version": chip_forecast.schema_version,
        }
    except (ChipOpportunityForecastError, OSError):
        # An advisory artifact must never invalidate a verified decision.
        chip_forecast = None
    strategic_v3 = None
    strategic_v3_error = None
    try:
        with decision_input.policy_timer("strategic_v3"):
            strategic_v3 = StrategicPlannerV3(decision_input.rules).plan(
                decision_input.state, decision_input.player_pool, decision_input.projections,
                chip_forecast=chip_forecast,
            ).as_dict()
        strategy_previews["strategic"] = _strategy_preview_payload(
            plan=_strategic_v3_plan(strategic_v3), decision_input=decision_input,
        )
    except (StrategicPlannerV3Error, DesktopDecisionError, OptimizerError) as exc:
        strategic_v3_error = str(exc)
        strategy_unavailable["strategic"] = f"V3 unavailable: {exc}"
    for display_plan in horizon_transfer_plans(horizon_report):
        key = _strategy_key(display_plan.title)
        if not key:
            continue
        try:
            strategy_previews[key] = _strategy_preview_payload(
                plan=display_plan.plan, decision_input=decision_input,
            )
            # Keep a per-slot identity. Short-term and Balanced may deliberately
            # carry identical transfer sets, but each has its own preview key.
            strategy_preview_identities[key] = _transfer_identity(
                display_plan.plan.transfers_out, display_plan.plan.transfers_in,
            )
        except DesktopDecisionError as exc:
            strategy_unavailable[key] = str(exc)

    # Policies, captaincy and all previews are now frozen. This optional
    # collection is deliberately after V1/V2/V3 and before final report
    # serialization, so it cannot rerun or influence recommendation logic.
    availability_snapshot_reference = None
    minutes_history_snapshot_reference = None
    final_target_ids = _final_advisory_player_ids(
        decision_input=decision_input, recommendation=recommendation,
        feasible_plans=feasible_plans, strategic_v3=strategic_v3,
        strategy_previews=strategy_previews,
    )
    try:
        decision_input, availability_snapshot_reference, minutes_history_snapshot_reference = _advisory_snapshots(
            project_root=project_root, prediction_bundle_path=prediction_bundle_path,
            decision_input=decision_input, player_ids=final_target_ids,
            capture_advisory_history=capture_advisory_history,
        )
    except (PlayerAvailabilityRiskError, PlayerMinutesHistoryError, OfficialPlayerHistoryError,
            OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        # Advice is optional: keep every already-frozen policy result intact.
        availability_snapshot_reference = None
        minutes_history_snapshot_reference = None
    result = {
        "report_version": 4, "mode": report.get("mode"), "external_mutations": report.get("external_mutations", []), "context_id": planning_context.context_id, "planning_context": planning_context.to_dict(),
        "shadow_report": str(machine), "recommendation": recommendation,
        # These are the existing Optimizer V1 candidate plans, already checked
        # against the account state and FPL constraints by the engine.
        "feasible_plans": feasible_plans,
        # V2 remains independently auditable while V3 is a challenger.
        "strategic_v2": strategic_action,
        "strategic_action": strategic_action,
        "strategic_v3": strategic_v3,
        "strategic_v3_error": strategic_v3_error,
        "strategy_previews": strategy_previews,
        "strategy_preview_identities": strategy_preview_identities,
        "strategy_unavailable": strategy_unavailable,
        "player_metadata": _display_metadata(prediction_bundle_path, bundle),
        "chip_opportunity_forecast": chip_forecast_reference,
        "player_availability_snapshot": availability_snapshot_reference,
        "player_minutes_history_snapshot": minutes_history_snapshot_reference,
    }
    # Report time is finalization time, after optional advisory acquisition.
    report_created_at = datetime.now(timezone.utc)
    destination = output_dir / f"desktop-decision-{report_created_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        typed_report = DecisionReportV2.create(
            report_id=destination.stem,
            created_at=report_created_at,
            planning_context=planning_context,
            mode=result["mode"],
            external_mutations=result["external_mutations"],
            shadow_report=result["shadow_report"],
            recommendation=result["recommendation"],
            feasible_plans=result["feasible_plans"],
            strategic_v2=result["strategic_v2"],
            strategic_v3=result["strategic_v3"],
            strategic_v3_error=result["strategic_v3_error"],
            strategy_previews=result["strategy_previews"],
            strategy_preview_identities=result["strategy_preview_identities"],
            strategy_unavailable=result["strategy_unavailable"],
            player_metadata=result["player_metadata"],
            chip_opportunity_forecast=result["chip_opportunity_forecast"],
            player_availability_snapshot=result["player_availability_snapshot"],
            player_minutes_history_snapshot=result["player_minutes_history_snapshot"],
        )
    except ReportSchemaError as exc:
        raise DesktopDecisionError(f"Decision report schema validation failed: {exc}") from exc
    destination.write_text(json.dumps(typed_report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop-state", type=Path, required=True)
    parser.add_argument("--prediction-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--capture-advisory-history", action="store_true",
                        help="Run optional pre-deadline Official FPL history capture after policy freeze.")
    args = parser.parse_args()
    try:
        report = run_desktop_decision(
            desktop_state_path=args.desktop_state, prediction_bundle_path=args.prediction_bundle,
            output_dir=args.output_dir, project_root=Path(__file__).resolve().parents[1],
            capture_advisory_history=bool(args.capture_advisory_history),
        )
    except DesktopDecisionError as exc:
        parser.error(str(exc))
    print(f"DECISION_REPORT={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
