"""Persistent JSON-lines worker for the desktop manual scenario comparator."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import tempfile


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return value


def _load_worker(root: Path, desktop_path: Path, bundle_path: Path):
    from fpl_engine.planning import DecisionInput, verify_projection_artifacts
    from fpl_engine.shadow import load_squad_state
    from .decision_orchestration import planning_context_for_state
    from .decision_runner import shadow_input

    root, desktop_path, bundle_path = root.resolve(), desktop_path.resolve(), bundle_path.resolve()
    desktop = _json(desktop_path)
    bundle = _json(bundle_path)
    if (bundle.get("pipeline") or {}).get(
        "simulator_version"
    ) != "fixture_simulator_v22_lineup_coherent_logit":
        raise ValueError(
            "The selected projection bundle is not the verified production V22 simulator."
        )
    manifest_path = bundle_path.parent / "run_manifest.json"
    manifest = _json(manifest_path)
    integrity = verify_projection_artifacts(bundle_path, manifest, require_hashes=True)
    context = planning_context_for_state(root, desktop, bundle_path)
    payload = shadow_input(desktop, bundle)
    with tempfile.TemporaryDirectory(prefix="fpl-manual-scenario-") as temporary:
        source = Path(temporary) / "shadow-input.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        state, pool, projections, pipeline, warnings, rules, freshness = load_squad_state(
            source,
            project_root=root,
            prediction_bundle_path=bundle_path,
        )
    shared = DecisionInput.create(
        planning_context=context,
        state=state,
        player_pool=pool,
        projections=projections,
        pipeline=pipeline,
        warnings=warnings,
        rules=rules,
        freshness=freshness,
        bundle_identity=context.projection_run_id,
    )
    input_hash = sha256(
        desktop_path.read_bytes() + bundle_path.read_bytes() + manifest_path.read_bytes()
    ).hexdigest()
    names = _player_metadata(bundle_path, bundle)
    return shared, names, input_hash, integrity


def _player_metadata(bundle_path: Path, bundle: dict) -> dict[str, dict]:
    names: dict[str, dict] = {}
    try:
        kits = json.loads(
            (Path(__file__).resolve().parent / "assets/kits/2026-27/kit_manifest.json").read_text(
                encoding="utf-8"
            )
        ).get("teams", {})
    except (OSError, ValueError):
        kits = {}
    try:
        rows = json.loads((bundle_path.parent / "current_players.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("player_id"):
            continue
        provider = (
            row.get("provider_payload") if isinstance(row.get("provider_payload"), dict) else {}
        )
        name = row.get("display_name") or row.get("name") or provider.get("web_name")
        team = kits.get(str(row.get("provider_team_id") or provider.get("team")), {})
        club = (
            row.get("club_name")
            or row.get("team_name")
            or team.get("name")
            or team.get("short_name")
            or row.get("club")
            or row.get("team")
        )
        names[str(row["player_id"])] = {
            "name": str(name or row["player_id"]),
            "club": club if isinstance(club, str) else None,
            "points_so_far": _finite_number(provider.get("total_points")),
        }

    projections = {
        str(row["player_id"]): row
        for row in bundle.get("projections", [])
        if isinstance(row, dict) and row.get("player_id")
    }
    current_gameweek = bundle.get("current_gameweek")
    fixture_data = {}
    try:
        fixture_rows = json.loads(
            (bundle_path.parent / "fixture_horizon.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        fixture_rows = []
    for fixture in fixture_rows if isinstance(fixture_rows, list) else []:
        if isinstance(fixture, dict) and fixture.get("fixture_id"):
            fixture_data[str(fixture["fixture_id"])] = fixture

    fixtures_by_team: dict[str, list[dict]] = {}
    for fixture in fixture_data.values():
        gameweek = fixture.get("target_gameweek")
        if not isinstance(gameweek, int) or not isinstance(current_gameweek, int):
            continue
        if current_gameweek <= gameweek < current_gameweek + 5:
            for side, other in (("home", "away"), ("away", "home")):
                team_id = fixture.get(f"{side}_provider_team_id")
                opponent = kits.get(str(fixture.get(f"{other}_provider_team_id")), {})
                if team_id is not None:
                    fixtures_by_team.setdefault(str(team_id), []).append(
                        {
                            "fixture_id": str(fixture["fixture_id"]),
                            "gameweek": gameweek,
                            "opponent": opponent.get("short_name"),
                            "venue": "H" if side == "home" else "A",
                            "projected_points": None,
                            "projected_points_source": None,
                        }
                    )

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("player_id"):
            continue
        player_id = str(row["player_id"])
        projection = projections.get(player_id, {})
        gameweeks = {
            gw.get("target_gameweek"): _finite_number(gw.get("expected_points"))
            for gw in projection.get("gameweeks", [])
            if isinstance(gw, dict) and isinstance(gw.get("target_gameweek"), int)
        }
        horizon_gws = (
            range(current_gameweek, current_gameweek + 5)
            if isinstance(current_gameweek, int)
            else ()
        )
        horizon = [gameweeks.get(gw) for gw in horizon_gws]
        known = [value for value in horizon if value is not None]
        provider = (
            row.get("provider_payload") if isinstance(row.get("provider_payload"), dict) else {}
        )
        team_id = row.get("provider_team_id") or provider.get("team")
        team_fixtures = [dict(fixture) for fixture in fixtures_by_team.get(str(team_id), [])]
        fixture_by_id = {fixture["fixture_id"]: fixture for fixture in team_fixtures}
        gameweek_rows = {
            gw.get("target_gameweek"): gw
            for gw in projection.get("gameweeks", [])
            if isinstance(gw, dict) and isinstance(gw.get("target_gameweek"), int)
        }
        gameweek_projections = []
        for gameweek in (
            range(current_gameweek, current_gameweek + 5)
            if isinstance(current_gameweek, int)
            else ()
        ):
            gw = gameweek_rows.get(gameweek, {})
            total = _finite_number(gw.get("expected_points"))
            gameweek_projections.append(
                {
                    "gameweek": gameweek,
                    "projected_points": total,
                    "fixture_count": gw.get("fixture_count")
                    if isinstance(gw.get("fixture_count"), int)
                    else None,
                }
            )
            fixture_ids = gw.get("fixture_ids")
            if (
                total is not None
                and gw.get("fixture_count") == 1
                and isinstance(fixture_ids, list)
                and len(fixture_ids) == 1
            ):
                fixture = fixture_by_id.get(str(fixture_ids[0]))
                verified_fixture = fixture_data.get(str(fixture_ids[0]), {})
                if fixture and verified_fixture.get("target_gameweek") == gameweek:
                    fixture["projected_points"] = total
                    fixture["projected_points_source"] = "single_fixture_gw"
        meta = names.setdefault(player_id, {"name": player_id, "club": None, "points_so_far": None})
        meta.update(
            {
                "next_gw_projection": horizon[0] if horizon else None,
                "next_5gw_total": sum(horizon) if len(known) == 5 else None,
                "gameweek_projections": gameweek_projections,
                "fixtures_5gw": [
                    {key: value for key, value in fixture.items() if key != "fixture_id"}
                    for fixture in sorted(team_fixtures, key=lambda fixture: fixture["gameweek"])
                ],
                "projection_coverage": len(known),
            }
        )
    for row in bundle.get("candidate_pool", []):
        if isinstance(row, dict) and row.get("player_id"):
            player_id = str(row["player_id"])
            current = names.get(player_id, {"name": player_id, "club": None})
            current["club"] = current["club"] or row.get("club_name") or row.get("team_name")
            if not current["club"]:
                current["club"] = str(row.get("club_id", ""))
            names[player_id] = current
    return names


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _ready(shared, names: dict, input_hash: str) -> dict:
    state = shared.state
    owned = {player.player_id: player for player in state.players}
    rows = []
    for player in shared.player_pool:
        item = names.get(player.player_id, {"name": player.player_id, "club": player.club_id})
        rows.append(
            {
                "player_id": player.player_id,
                "name": item["name"],
                "position": player.position,
                "club": item.get("club") or str(player.club_id),
                "price": int(player.current_price),
                "selling_price": None
                if player.player_id not in owned
                else int(owned[player.player_id].selling_price),
                "owned": player.player_id in owned,
                "points_so_far": item.get("points_so_far"),
                "next_gw_projection": item.get("next_gw_projection"),
                "next_5gw_total": item.get("next_5gw_total"),
                "fixtures_5gw": item.get("fixtures_5gw", []),
                "gameweek_projections": item.get("gameweek_projections", []),
                "projection_coverage": item.get("projection_coverage", 0),
            }
        )
    rows.sort(key=lambda row: row["player_id"])
    return {
        "type": "ready",
        "context_id": str(shared.context_id),
        "input_sha256": input_hash,
        "players": rows,
        "bank": int(state.bank),
        "free_transfers": int(state.free_transfers),
        "owned_ids": sorted(owned),
    }


def _emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _command_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop-state", required=True, type=Path)
    parser.add_argument("--prediction-bundle", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    return parser


def main(argv=None) -> int:
    from .manual_scenario_engine import ManualScenarioError, ManualScenarioEvaluator

    args = _command_parser().parse_args(argv)
    try:
        shared, names, input_hash, _ = _load_worker(
            args.root, args.desktop_state, args.prediction_bundle
        )
        evaluator = ManualScenarioEvaluator(shared, input_sha256=input_hash)
        _emit(_ready(shared, names, evaluator.input_sha256))
    except Exception as exc:
        _emit({"type": "error", "id": "", "message": str(exc)})
        return 1

    for line in sys.stdin:
        request_id = ""
        try:
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("Each worker command must be a JSON object.")
            request_id = str(command.get("id", ""))
            action = command.get("command")
            if action == "quit":
                return 0
            if action not in {"validate", "evaluate"}:
                raise ValueError("Unknown worker command.")
            if command.get("context_id") != evaluator.context_id:
                raise ManualScenarioError(
                    "The selected PlanningContext does not match this worker."
                )
            # Detect replaced desktop snapshots and changed bundle/manifests before each command.
            with redirect_stdout(sys.stderr):
                current_shared, _, current_hash, _ = _load_worker(
                    args.root, args.desktop_state, args.prediction_bundle
                )
            if (
                current_hash != input_hash
                or current_shared.context_id != evaluator.context_id
                or evaluator._digest(current_shared) != evaluator._native_digest
            ):
                raise ManualScenarioError(
                    "The verified context or projection artifacts changed; reload this worker."
                )
            outs, ins = command.get("transfers_out", []), command.get("transfers_in", [])
            if not isinstance(outs, list) or not isinstance(ins, list):
                raise ManualScenarioError("Transfer IDs must be JSON arrays.")
            if action == "validate":
                try:
                    summary = evaluator.validate(outs, ins, context_id=command["context_id"])
                    _emit(
                        {
                            "type": "validation",
                            "id": request_id,
                            "context_id": evaluator.context_id,
                            "valid": True,
                            "error": None,
                            "summary": summary,
                        }
                    )
                except ManualScenarioError as exc:
                    _emit(
                        {
                            "type": "validation",
                            "id": request_id,
                            "context_id": evaluator.context_id,
                            "valid": False,
                            "error": str(exc),
                            "summary": None,
                        }
                    )
            else:

                def progress(message):
                    _emit({"type": "progress", "id": request_id, "message": message})

                result = evaluator.evaluate(
                    outs, ins, progress=progress, context_id=command["context_id"]
                )
                _emit({"type": "result", "id": request_id, **result})
        except (KeyboardInterrupt, Exception) as exc:
            _emit({"type": "error", "id": request_id, "message": str(exc) or type(exc).__name__})
    return 0


if __name__ == "__main__":
    from desktop_app.manual_worker_guard import watch_parent

    watch_parent()
    raise SystemExit(main())
