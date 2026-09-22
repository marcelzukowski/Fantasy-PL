"""Child-process adapter for the existing exact chip screen and timing policy."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from math import prod
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from fpl_engine.decision.chip_screen import screen_chips_exact
from fpl_engine.decision.chip_timing import ExactChipTimingPolicy, future_fixed_squad_chip_opportunities_exact
from fpl_engine.decision.policy_config import load_exact_chip_timing_config
from fpl_engine.decision.chip_strategy import (
    STRATEGIC_SIMULATIONS_PER_FIXTURE,
    chip_strategy_horizons,
    strategic_chip_opportunities,
)
from fpl_engine.optimizer import chip_available
from fpl_engine.optimizer.v2 import OptimizerV2Config, generate_candidates
from fpl_engine.shadow import ShadowRunError, load_squad_state

from .decision_runner import DesktopDecisionError, _object, shadow_input


class DesktopChipError(ValueError):
    pass


CHIPS = ("wildcard", "free_hit", "bench_boost", "triple_captain")


def _strategy_root(project_root: Path, *, season: str, gameweek: int) -> Path:
    return (
        Path(project_root)
        / "data"
        / "interim"
        / "desktop_chip_strategy"
        / str(season).replace("/", "-")
        / f"gw{int(gameweek):02d}"
    )


def _strategy_context_path(project_root: Path, *, season: str, gameweek: int) -> Path:
    return _strategy_root(project_root, season=season, gameweek=gameweek) / "strategy_context.json"


def _load_strategy_context(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _strategic_bundle(
    *,
    project_root: Path,
    state,
    base_bundle: Path,
    strategic_gameweeks: tuple[int, ...],
    chip_period_end: int,
) -> tuple[Path, bool]:
    """Return a cached, model-only 3k future-horizon bundle when possible."""
    root = Path(project_root).resolve()
    gameweeks = tuple(int(gameweek) for gameweek in strategic_gameweeks)
    if not gameweeks:
        raise DesktopChipError("Strategic scan has no eligible gameweeks in the active chip period.")
    if gameweeks != tuple(range(gameweeks[0], gameweeks[-1] + 1)):
        raise DesktopChipError("Strategic gameweeks must be one contiguous range.")
    if gameweeks[0] < 1 or gameweeks[-1] > int(chip_period_end):
        raise DesktopChipError("Strategic gameweeks cross the active chip-period boundary.")
    projection_start = gameweeks[0]
    projection_horizon = len(gameweeks)
    context_path = _strategy_context_path(root, season=state.season, gameweek=state.current_gameweek)
    context = _load_strategy_context(context_path)
    if context is not None:
        cached = Path(str(context.get("bundle_path", "")))
        if (
            context.get("base_bundle") == str(Path(base_bundle).resolve())
            and context.get("simulations_per_fixture") == STRATEGIC_SIMULATIONS_PER_FIXTURE
            and context.get("projection_start_gameweek") == projection_start
            and context.get("projection_gameweeks") == list(gameweeks)
            and context.get("projection_horizon_gameweeks") == projection_horizon
            and context.get("chip_period_end") == int(chip_period_end)
            and cached.is_file()
        ):
            return cached, True

    output_root = context_path.parent / "predictions"
    canonical_db = context_path.parent / "canonical.duckdb"
    command = [
        str(root / ".venv" / "Scripts" / "python.exe"),
        "-m", "fpl_engine", "predict-current",
        "--season", str(state.season),
        "--gameweek", str(projection_start),
        "--simulation-count", str(STRATEGIC_SIMULATIONS_PER_FIXTURE),
        "--projection-horizon-gameweeks", str(projection_horizon),
        "--seed", "42",
        "--output-root", str(output_root),
        "--canonical-db", str(canonical_db),
        "--skip-market-shadow",
    ]
    print("CHIP_PROGRESS=strategic model-only projection scan", flush=True)
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    for line in completed.stderr.splitlines():
        if line.startswith("[current]"):
            print(f"CHIP_PROGRESS=strategic {line.removeprefix('[current] ').strip()}", flush=True)
    if completed.returncode != 0:
        raise DesktopChipError("Strategic chip scan could not materialize its model-only projection horizon.")
    run_directories = [
        Path(line.strip())
        for line in completed.stdout.splitlines()
        if line.strip() and Path(line.strip()).is_dir()
    ]
    if not run_directories:
        raise DesktopChipError("Strategic chip scan did not return a projection directory.")
    bundle = run_directories[-1] / "shadow_projection_bundle.json"
    if not bundle.is_file():
        raise DesktopChipError("Strategic chip scan did not write a complete projection bundle.")
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps({
        "base_bundle": str(Path(base_bundle).resolve()),
        "bundle_path": str(bundle.resolve()),
        "season": state.season,
        "gameweek": state.current_gameweek,
        "chip_period_end": int(chip_period_end),
        "projection_start_gameweek": projection_start,
        "projection_gameweeks": list(gameweeks),
        "projection_horizon_gameweeks": projection_horizon,
        "simulations_per_fixture": STRATEGIC_SIMULATIONS_PER_FIXTURE,
        "market_shadow": "DISABLED_MODEL_ONLY",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle, False


def _strategy_inputs(payload: dict, bundle: Path, project_root: Path):
    with tempfile.TemporaryDirectory(prefix="fpl-desktop-chip-strategy-") as temporary:
        source = Path(temporary) / "shadow-input.json"
        # The strategic bundle is a separate, later production run.  Retain
        # explicit account state, but let its own timestamp and GW identify
        # the projection contract instead of falsely requiring the near-term
        # bundle's identity.
        strategy_payload = dict(payload)
        for key in ("prediction_timestamp", "season", "current_gameweek"):
            strategy_payload.pop(key, None)
        source.write_text(json.dumps(strategy_payload), encoding="utf-8")
        try:
            return load_squad_state(source, project_root=project_root, prediction_bundle_path=bundle)
        except ShadowRunError as exc:
            raise DesktopChipError(str(exc)) from exc


def _opportunity_payload(row) -> dict:
    return {
        "chip": row.chip,
        "gameweek": row.gameweek,
        "baseline_ev": row.baseline_ev,
        "chip_ev": row.chip_ev,
        "incremental_ev": row.incremental_ev,
    }


def available_chips(state, rules) -> tuple[str, ...]:
    """Use the production rules' availability gate; never infer a chip state."""
    return tuple(chip for chip in CHIPS if chip_available(chip, state, rules))


def _strategic_preflight(*, bundle_path: Path, horizons, available: tuple[str, ...]) -> str | None:
    """Return a precise skip reason before launching the costly 3k run."""
    if not available:
        return "no chips remain available in the active chip period"
    gameweeks = tuple(int(gameweek) for gameweek in horizons.strategic_gameweeks)
    if not gameweeks:
        return "no strategic gameweeks remain in the active chip period"
    if gameweeks != tuple(range(gameweeks[0], gameweeks[-1] + 1)):
        return "strategic gameweeks are not one contiguous range"
    if gameweeks[-1] > int(horizons.chip_period_end):
        return "strategic range crosses the active chip-period boundary"
    if not (Path(bundle_path).parent / "minutes.json").is_file():
        return "missing production minutes prerequisite"
    return None


def _minutes_appearance(path: Path, projections, *, horizon: int) -> dict[tuple[str, int], float]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopChipError("The production bundle has no readable minutes output.") from exc
    if not isinstance(rows, list):
        raise DesktopChipError("The production minutes output is invalid.")
    fixture_gameweeks: dict[str, int] = {}
    required: set[tuple[str, int]] = set()
    for player_id, projection in projections.items():
        for row in projection.gameweeks[:horizon]:
            gameweek = int(row.target_gameweek)
            required.add((player_id, gameweek))
            for fixture_id in row.fixture_ids:
                previous = fixture_gameweeks.setdefault(str(fixture_id), gameweek)
                if previous != gameweek:
                    raise DesktopChipError("The production fixture mapping is inconsistent.")
    values: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("player_id") is None or row.get("fixture_id") is None:
            continue
        gameweek = fixture_gameweeks.get(str(row["fixture_id"]))
        if gameweek is None:
            continue
        try:
            value = float(row["p_appearance"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DesktopChipError("The production minutes output is missing appearance probability.") from exc
        if not 0.0 <= value <= 1.0:
            raise DesktopChipError("The production minutes output has an invalid appearance probability.")
        values.setdefault((str(row["player_id"]), gameweek), []).append(value)
    result = {}
    for key in required:
        values_for_gameweek = values.get(key)
        if values_for_gameweek is None:
            player_id, gameweek = key
            projection = projections[player_id]
            target = next(item for item in projection.gameweeks if int(item.target_gameweek) == gameweek)
            if int(target.fixture_count) == 0:
                result[key] = 0.0
                continue
            raise DesktopChipError(f"Production minutes are missing for {player_id} in GW{gameweek}.")
        result[key] = 1.0 - prod(1.0 - item for item in values_for_gameweek)
    return result


def _validate_decision(report_path: Path, *, season: str, gameweek: int, prediction_timestamp: str) -> None:
    report = _object(report_path, "desktop decision report")
    if report.get("external_mutations"):
        raise DesktopChipError("The decision report failed the read-only safety check.")
    shadow_path = report.get("shadow_report")
    if not shadow_path:
        raise DesktopChipError("The compatible decision report is incomplete.")
    shadow = _object(Path(shadow_path), "shadow decision report")
    if (str(shadow.get("season")) != season or int(shadow.get("current_gameweek", -1)) != gameweek
            or str(shadow.get("prediction_timestamp")) != prediction_timestamp):
        raise DesktopChipError("The decision report does not match the selected production bundle.")
    if shadow.get("external_mutations"):
        raise DesktopChipError("The compatible decision output is not read-only.")


def _entry_payload(entry) -> dict:
    return {
        "chip": entry.chip,
        "available": entry.available,
        "incremental_ev": entry.incremental_ev,
        "baseline_ev": entry.baseline_ev,
        "chip_ev": entry.chip_ev,
        "threshold": entry.threshold,
        "future_best_incremental_ev": entry.future_best_incremental_ev,
        "use_now": entry.use_now,
        "reason": entry.reason,
    }


def _exact_projection_rows(projections):
    return {
        player_id: SimpleNamespace(
            player_id=player_id,
            gameweeks=tuple(SimpleNamespace(gameweek=int(item.target_gameweek), expected_points=float(item.expected_points)) for item in projection.gameweeks),
        )
        for player_id, projection in projections.items()
    }


def run_desktop_chip_screen(*, desktop_state_path: Path, prediction_bundle_path: Path, decision_report_path: Path, output_dir: Path, project_root: Path) -> Path:
    print("CHIP_PROGRESS=loading data", flush=True)
    desktop = _object(desktop_state_path, "desktop squad state")
    bundle = _object(prediction_bundle_path, "prediction bundle")
    _validate_decision(decision_report_path, season=str(bundle.get("season")), gameweek=int(bundle.get("current_gameweek", -1)), prediction_timestamp=str(bundle.get("prediction_timestamp")))
    try:
        payload = shadow_input(desktop, bundle)
    except DesktopDecisionError as exc:
        raise DesktopChipError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="fpl-desktop-chip-") as temporary:
        source = Path(temporary) / "shadow-input.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        try:
            state, pool, projections, _, _, rules, _ = load_squad_state(source, project_root=project_root, prediction_bundle_path=prediction_bundle_path)
        except ShadowRunError as exc:
            raise DesktopChipError(str(exc)) from exc
    config = load_exact_chip_timing_config(project_root)
    horizons = chip_strategy_horizons(
        state.current_gameweek,
        exact_horizon_gameweeks=config.evaluation_horizon_gameweeks,
    )
    # Availability is an account/rules fact, so establish it before candidate
    # generation or any exact chip scoring.  This prevents a used first-half
    # chip from consuming work or appearing in progress output.
    available = available_chips(state, rules)
    appearances = _minutes_appearance(
        prediction_bundle_path.parent / "minutes.json",
        projections,
        horizon=horizons.exact_horizon_gameweeks,
    )
    exact_projections = _exact_projection_rows(projections)
    # The existing V2 production candidate generator provides the bounded,
    # deterministic universe consumed by the exact unlimited-squad screen.
    # It is not a GUI heuristic and does not alter the decision calculation.
    print("CHIP_PROGRESS=generating candidates", flush=True)
    generated, candidate_report = generate_candidates(state, pool, projections, OptimizerV2Config())
    screen_pool = {player.player_id: player for player in (*state.players, *generated)}
    positions = {player_id: player.position for player_id, player in screen_pool.items()}
    player_rows = [{"player_id": player.player_id, "position": player.position, "team_id": player.club_id, "current_price": player.current_price} for player in screen_pool.values()]
    screen = screen_chips_exact(
        player_rows=player_rows, positions=positions, projections_by_id=exact_projections,
        p_appearance_by_gameweek=appearances, current_player_ids=(player.player_id for player in state.players),
        selling_prices_tenths={player.player_id: int(player.selling_price) for player in state.players}, bank_tenths=state.bank,
        first_gameweek=state.current_gameweek, wildcard_horizon=horizons.exact_horizon_gameweeks,
        wildcard_weights=tuple(0.95 ** index for index in range(horizons.exact_horizon_gameweeks)),
        max_players_per_team=int(rules.value("initial_squad", "maximum_players_per_club")),
        available_chips=available,
        progress=lambda stage: print(f"CHIP_PROGRESS={stage}", flush=True),
    )
    near_term_future = future_fixed_squad_chip_opportunities_exact(
        squad_player_ids=(player.player_id for player in state.players), positions=positions,
        projections_by_id=exact_projections, p_appearance_by_gameweek=appearances,
        first_gameweek=state.current_gameweek,
        evaluation_horizon_gameweeks=horizons.exact_horizon_gameweeks,
        available_chips=available,
    )
    strategic_scan = None
    strategic_bundle = None
    strategic_reused = False
    strategic_error = None
    strategic_skip_reason = _strategic_preflight(
        bundle_path=prediction_bundle_path,
        horizons=horizons,
        available=available,
    )
    if strategic_skip_reason is not None:
        strategic_error = f"Strategic scan skipped: {strategic_skip_reason}."
        print(f"CHIP_PROGRESS={strategic_error}", flush=True)
    else:
        try:
            strategic_bundle, strategic_reused = _strategic_bundle(
                project_root=project_root,
                state=state,
                base_bundle=prediction_bundle_path,
                strategic_gameweeks=horizons.strategic_gameweeks,
                chip_period_end=horizons.chip_period_end,
            )
            strategy_state, strategy_pool, strategy_projections, _, _, strategy_rules, _ = _strategy_inputs(
                payload, strategic_bundle, project_root,
            )
            strategy_positions = {
                player.player_id: player.position
                for player in (*strategy_pool, *strategy_state.players)
            }
            strategy_rows = [
                {
                    "player_id": player.player_id,
                    "position": player.position,
                    "team_id": player.club_id,
                    "current_price": player.current_price,
                }
                for player in strategy_pool
            ]
            strategy_appearances = _minutes_appearance(
                strategic_bundle.parent / "minutes.json",
                strategy_projections,
                horizon=len(horizons.strategic_gameweeks),
            )
            print("CHIP_PROGRESS=strategic opportunity scoring", flush=True)
            strategic_scan = strategic_chip_opportunities(
                player_rows=strategy_rows,
                positions=strategy_positions,
                projections_by_id=_exact_projection_rows(strategy_projections),
                p_appearance_by_gameweek=strategy_appearances,
                current_player_ids=(player.player_id for player in strategy_state.players),
                selling_prices_tenths={player.player_id: int(player.selling_price) for player in strategy_state.players},
                bank_tenths=strategy_state.bank,
                strategic_gameweeks=horizons.strategic_gameweeks,
                chip_period_end_gameweek=horizons.chip_period_end,
                max_players_per_team=int(strategy_rules.value("initial_squad", "maximum_players_per_club")),
                available_chips=available,
            )
        except DesktopChipError as exc:
            # The exact current decision remains useful when a separate,
            # lower-confidence future scan cannot be materialized.
            strategic_error = f"Strategic scan failed: {exc}"
            print(f"CHIP_PROGRESS={strategic_error}", flush=True)

    future_opportunities = {
        chip: tuple(near_term_future.get(chip, ())) + tuple(
            strategic_scan.opportunities.get(chip, ()) if strategic_scan is not None else ()
        )
        for chip in CHIPS
    }
    print("CHIP_PROGRESS=final chip comparison", flush=True)
    try:
        timing = ExactChipTimingPolicy(config).decide(
            screen=screen,
            future_opportunities=future_opportunities,
            available_chips=available,
        )
    except (ValueError, RuntimeError) as exc:
        raise DesktopChipError("The existing chip calculation could not evaluate this production bundle.") from exc
    evaluations = {entry.chip: _entry_payload(entry) for entry in timing.evaluations}
    selected = evaluations.get(timing.chosen_chip) if timing.chosen_chip else None
    strategic_rows = tuple(
        opportunity
        for chip in CHIPS
        for opportunity in (strategic_scan.opportunities.get(chip, ()) if strategic_scan is not None else ())
        if chip in available
    )
    best_later = max(
        strategic_rows,
        key=lambda row: (row.incremental_ev, -row.gameweek, row.chip),
        default=None,
    )
    current_incremental = selected["incremental_ev"] if selected else None
    materially_stronger_later = (
        best_later
        if best_later is not None
        and (current_incremental is None or best_later.incremental_ev > current_incremental + config.future_opportunity_tolerance)
        else None
    )
    recommendation = {
        "chip": timing.chosen_chip,
        "incremental_ev": selected["incremental_ev"] if selected else None,
        "reason": selected["reason"] if selected else "No available chip clears the existing timing policy.",
        "horizon_gameweeks": horizons.exact_horizon_gameweeks,
        "near_term_start_gameweek": horizons.exact_gameweeks[0],
        "near_term_end_gameweek": horizons.exact_gameweeks[-1],
        "available_chips": list(available),
    }
    result = {
        "report_version": 1, "mode": "ADVISORY / READ ONLY", "external_mutations": [],
        "prediction_bundle": str(prediction_bundle_path), "decision_report": str(decision_report_path),
        "season": state.season, "gameweek": state.current_gameweek,
        "prediction_timestamp": state.prediction_timestamp.isoformat(), "recommendation": recommendation,
        "evaluations": evaluations, "timing_policy_version": ExactChipTimingPolicy.VERSION,
        "candidate_generation": asdict(candidate_report),
        "chip_period": {
            "start_gameweek": state.current_gameweek,
            "end_gameweek": horizons.chip_period_end,
            "exact_gameweeks": list(horizons.exact_gameweeks),
            "strategic_gameweeks": list(horizons.strategic_gameweeks),
            "available_chips": list(available),
        },
        "strategic": {
            "mode": "MODEL_ONLY_STRATEGIC_ESTIMATE",
            "simulations_per_fixture": STRATEGIC_SIMULATIONS_PER_FIXTURE,
            "projection_start_gameweek": (
                horizons.strategic_gameweeks[0] if horizons.strategic_gameweeks else None
            ),
            "projection_gameweeks": list(horizons.strategic_gameweeks),
            "market_shadow_invoked": False,
            "bundle_path": str(strategic_bundle) if strategic_bundle is not None else None,
            "reused": strategic_reused,
            "error": strategic_error,
            "unavailable_gameweeks": (
                {str(gameweek): reason for gameweek, reason in strategic_scan.unavailable_gameweeks.items()}
                if strategic_scan is not None else {}
            ),
            "best_candidate": _opportunity_payload(best_later) if best_later is not None else None,
            "materially_stronger_candidate": (
                _opportunity_payload(materially_stronger_later)
                if materially_stronger_later is not None else None
            ),
            "opportunities": {
                chip: [_opportunity_payload(row) for row in future_opportunities[chip]
                      if row.gameweek in horizons.strategic_gameweeks]
                for chip in CHIPS
            },
        },
    }
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"desktop-chip-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop-state", type=Path, required=True)
    parser.add_argument("--prediction-bundle", type=Path, required=True)
    parser.add_argument("--decision-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_desktop_chip_screen(
            desktop_state_path=args.desktop_state, prediction_bundle_path=args.prediction_bundle,
            decision_report_path=args.decision_report, output_dir=args.output_dir,
            project_root=Path(__file__).resolve().parents[1],
        )
    except DesktopChipError as exc:
        parser.error(str(exc))
    print(f"CHIP_REPORT={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
