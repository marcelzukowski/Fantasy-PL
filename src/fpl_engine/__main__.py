"""Command-line entry points for local, non-mutating engine workflows."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import httpx

from .current import (
    CurrentInputError, CurrentPipelineConfig, CurrentPipelineError,
    CurrentPredictionPipeline, OfficialCurrentDataSource,
    team_id_squad_ingestion_limitation,
)
from .data.http_cache import HttpCache
from .data.local_fpl_snapshots import LocalFPLSnapshotStore
from .data.providers.the_odds_api import TheOddsApiAdapter
from .data.providers.api_football import APIFootballAdapter, APIFootballQuota
from .data.providers.fpl_api import OfficialFPLAdapter
from .data.raw_store import RawStore
from .current_market_shadow import (
    collect_current_gameweek_market_shadow,
    write_market_shadow_skipped,
)
from .shadow import ShadowRunError, run_shadow
from .types import PredictionContext
from .planning import OfficialPlayerHistoryAcquirer, write_official_player_history_acquisition
from .reports import parse_decision_report


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m fpl_engine")
    commands = parser.add_subparsers(dest="command", required=True)
    shadow = commands.add_parser("shadow", help="write a non-mutating current-season shadow recommendation")
    shadow.add_argument("--squad-state", type=Path, required=True)
    shadow.add_argument("--prediction-bundle", type=Path)
    shadow.add_argument("--output-dir", type=Path)
    shadow.add_argument("--allow-diagnostic", action="store_true", help=argparse.SUPPRESS)
    current = commands.add_parser(
        "predict-current", help="materialize current data and run the existing V1 projection chain",
    )
    current.add_argument("--season", required=True)
    current.add_argument("--gameweek", type=int, required=True)
    current.add_argument("--prediction-timestamp", type=_timestamp)
    current.add_argument("--squad-state", type=Path)
    current.add_argument("--team-id", type=int)
    current.add_argument("--simulation-count", type=int, default=10_000)
    current.add_argument("--projection-horizon-gameweeks", type=int, default=6)
    current.add_argument("--seed", type=int, default=42)
    current.add_argument("--output-root", type=Path)
    current.add_argument("--canonical-db", type=Path)
    current.add_argument("--api-football-league-id", type=int)
    current.add_argument("--api-football-budget", type=int, default=80)
    current.add_argument("--skip-market-shadow", action="store_true")
    history = commands.add_parser("refresh-player-history", help="explicitly acquire advisory Official FPL completed player history")
    history.add_argument("--season", required=True)
    history.add_argument("--gameweek", type=int, required=True)
    history.add_argument("--squad-state", type=Path, required=True)
    history.add_argument("--prediction-bundle", type=Path, required=True)
    history.add_argument("--decision-report", type=Path)
    history.add_argument("--top-targets", type=int, default=10)
    history.add_argument("--cache-ttl-seconds", type=int, default=300)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.command == "shadow":
        try:
            machine, human = run_shadow(
                args.squad_state, project_root=root, output_dir=args.output_dir,
                prediction_bundle_path=args.prediction_bundle,
                allow_diagnostic=args.allow_diagnostic,
            )
        except ShadowRunError as exc:
            parser.error(str(exc))
        print(machine)
        print(human)
    elif args.command == "refresh-player-history":
        if args.cache_ttl_seconds < 0 or args.top_targets < 0:
            parser.error("history cache TTL and top-target count must be non-negative")
        try:
            state_payload = json.loads(args.squad_state.read_text(encoding="utf-8"))
            if not isinstance(state_payload, dict) or not isinstance(state_payload.get("player_ids"), list):
                raise ValueError("squad state must provide player_ids")
            decision = parse_decision_report(json.loads(args.decision_report.read_text(encoding="utf-8"))) if args.decision_report else None
            retrieval_clock = lambda: datetime.now(timezone.utc)
            raw_store = RawStore(root / "data" / "raw")
            cache = HttpCache(root / "data" / "interim" / "http_cache", clock=retrieval_clock)
            with httpx.Client() as client:
                adapter = OfficialFPLAdapter(client=client, cache=cache, raw_store=raw_store, ttl=timedelta(seconds=args.cache_ttl_seconds), clock=retrieval_clock)
                acquisition = OfficialPlayerHistoryAcquirer(adapter=adapter, raw_store=raw_store, cache_ttl=timedelta(seconds=args.cache_ttl_seconds), clock=retrieval_clock).refresh(
                    bundle_directory=args.prediction_bundle.parent, season=args.season, gameweek=args.gameweek,
                    squad_player_ids=tuple(str(value) for value in state_payload["player_ids"]), decision=decision, top_targets=args.top_targets,
                )
            artifact = write_official_player_history_acquisition(args.prediction_bundle.parent, acquisition)
            print(artifact)
            print(json.dumps(acquisition.statistics, sort_keys=True), file=sys.stderr)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == "predict-current":
        if args.team_id is not None:
            parser.error(str(team_id_squad_ingestion_limitation(args.team_id)))
        retrieval_clock = lambda: datetime.now(timezone.utc)
        raw_store = RawStore(root / "data" / "raw")
        cache = HttpCache(root / "data" / "interim" / "http_cache", clock=retrieval_clock)
        local = LocalFPLSnapshotStore(root / "data" / "snapshots", raw_store=raw_store)
        try:
            with httpx.Client() as client:
                official = OfficialFPLAdapter(
                    client=client, cache=cache, raw_store=raw_store,
                    ttl=timedelta(minutes=5), clock=retrieval_clock,
                )
                api_football = None
                api_key = os.environ.get("API_FOOTBALL_KEY")
                if args.api_football_league_id is not None and api_key:
                    api_football = APIFootballAdapter(
                        client=client, api_key=api_key, cache=cache, raw_store=raw_store,
                        quota=APIFootballQuota(args.api_football_budget, clock=retrieval_clock),
                        ttl=timedelta(minutes=30), clock=retrieval_clock,
                    )
                source = OfficialCurrentDataSource(
                    official, local_snapshots=local, api_football=api_football,
                    api_football_league_id=args.api_football_league_id,
                )
                refresh_context = PredictionContext(
                    prediction_timestamp=args.prediction_timestamp or retrieval_clock(),
                    target_gameweek=args.gameweek, target_season=args.season,
                )
                print("[current] provider ingestion", file=sys.stderr)
                materialized_source = source.refresh(refresh_context)
                prediction_timestamp = args.prediction_timestamp or retrieval_clock()
                pipeline = CurrentPredictionPipeline(
                    source, project_root=root,
                    config=CurrentPipelineConfig(
                        canonical_database=args.canonical_db or root / "data" / "processed" / "canonical" / "current.duckdb",
                        output_root=args.output_root or root / "data" / "processed" / "predictions",
                        simulations_per_fixture=args.simulation_count, random_seed=args.seed,
                        projection_horizon_gameweeks=args.projection_horizon_gameweeks,
                    ),
                    progress=lambda message: print(f"[current] {message}", file=sys.stderr),
                )
                print("[current] production V22 simulation", file=sys.stderr)
                result = pipeline.run(PredictionContext(
                    prediction_timestamp=prediction_timestamp,
                    target_gameweek=args.gameweek, target_season=args.season,
                ), squad_state_path=args.squad_state,
                    materialized_source=materialized_source)
                print("[current] projections completed", file=sys.stderr)

                odds_key = os.environ.get("THE_ODDS_API_KEY")
                if args.skip_market_shadow:
                    print("[shadow-market] skipped: disabled for this model-only run", file=sys.stderr)
                elif not odds_key:
                    print("[shadow-market] FAILED/SKIPPED: bookmaker API is not configured", file=sys.stderr)
                    shadow_result = write_market_shadow_skipped(
                        project_root=root,
                        run_directory=result.run_directory,
                        season=args.season,
                        current_gameweek=args.gameweek,
                        prediction_timestamp=prediction_timestamp,
                        reason="THE_ODDS_API_KEY is not configured.",
                    )
                else:
                    try:
                        print("[shadow-market] bookmaker ingestion", file=sys.stderr)
                        print("[shadow-market] provider: the_odds_api", file=sys.stderr)
                        shadow_result = collect_current_gameweek_market_shadow(
                            adapter=TheOddsApiAdapter(
                                client=client,
                                cache=cache,
                                raw_store=raw_store,
                                api_key=odds_key,
                                ttl=timedelta(minutes=10),
                                clock=retrieval_clock,
                            ),
                            project_root=root,
                            run_directory=result.run_directory,
                            season=args.season,
                            current_gameweek=args.gameweek,
                            prediction_timestamp=prediction_timestamp,
                            fixtures=result.fixture_horizon,
                            event_projections=result.event_projections,
                            players=result.current_players,
                            canonical_team_names=result.canonical_team_names,
                            progress=lambda message: print(message, file=sys.stderr),
                        )
                    except Exception as exc:
                        # The V22 bundle is complete before this optional
                        # challenger begins.  Never let shadow failure alter it.
                        print(f"[shadow-market] FAILED/SKIPPED: {type(exc).__name__}", file=sys.stderr)
                        print("[current] production bundle remains valid", file=sys.stderr)
                        shadow_result = write_market_shadow_skipped(
                            project_root=root,
                            run_directory=result.run_directory,
                            season=args.season,
                            current_gameweek=args.gameweek,
                            prediction_timestamp=prediction_timestamp,
                            reason=f"{type(exc).__name__} while collecting market shadow.",
                        )
        except (CurrentPipelineError, ShadowRunError) as exc:
            parser.error(str(exc))
        print(result.run_directory)
        print(result.artifacts["run_manifest"])
        print(result.artifacts["human_report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
