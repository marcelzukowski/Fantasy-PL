"""Child-process entry point that adapts desktop state to the existing shadow runner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from fpl_engine.optimizer import OptimizerError, SquadState, optimize_lineup, validate_squad
from fpl_engine.shadow import ShadowRunError, load_squad_state, run_shadow
from fpl_engine.strategy import StrategicPlannerV3, StrategicPlannerV3Error
from fpl_engine.reports import DecisionReportV2, ReportSchemaError

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


def _strategy_preview_payload(*, plan, state, pool, projections, rules) -> dict:
    """Apply one existing transfer plan, then use the existing lineup optimizer."""
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
        lineup = optimize_lineup(preview_state, projections, rules)
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


def run_desktop_decision(*, desktop_state_path: Path, prediction_bundle_path: Path, output_dir: Path, project_root: Path) -> Path:
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
            machine, _ = run_shadow(source, project_root=project_root, output_dir=output_dir, prediction_bundle_path=prediction_bundle_path)
        except ShadowRunError as exc:
            raise DesktopDecisionError(str(exc)) from exc
        try:
            strategy_state, pool, projections, _pipeline, _warnings, rules, _freshness = load_squad_state(
                source, project_root=project_root, prediction_bundle_path=prediction_bundle_path,
            )
        except ShadowRunError as exc:
            raise DesktopDecisionError("Decision output cannot build current-GW strategy previews.") from exc
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
    strategic_v3 = None
    strategic_v3_error = None
    try:
        strategic_v3 = StrategicPlannerV3(rules).plan(strategy_state, pool, projections).as_dict()
        strategy_previews["strategic"] = _strategy_preview_payload(
            plan=_strategic_v3_plan(strategic_v3), state=strategy_state, pool=pool,
            projections=projections, rules=rules,
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
                plan=display_plan.plan, state=strategy_state, pool=pool,
                projections=projections, rules=rules,
            )
            # Keep a per-slot identity. Short-term and Balanced may deliberately
            # carry identical transfer sets, but each has its own preview key.
            strategy_preview_identities[key] = _transfer_identity(
                display_plan.plan.transfers_out, display_plan.plan.transfers_in,
            )
        except DesktopDecisionError as exc:
            strategy_unavailable[key] = str(exc)
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
    }
    created_at = datetime.now(timezone.utc)
    destination = output_dir / f"desktop-decision-{created_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        typed_report = DecisionReportV2.create(
            report_id=destination.stem,
            created_at=created_at,
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
    args = parser.parse_args()
    try:
        report = run_desktop_decision(
            desktop_state_path=args.desktop_state, prediction_bundle_path=args.prediction_bundle,
            output_dir=args.output_dir, project_root=Path(__file__).resolve().parents[1],
        )
    except DesktopDecisionError as exc:
        parser.error(str(exc))
    print(f"DECISION_REPORT={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

