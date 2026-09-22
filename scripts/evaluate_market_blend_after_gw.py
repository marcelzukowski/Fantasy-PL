from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx

from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter
from fpl_engine.data.raw_store import RawStore
from fpl_engine.models.events.market_blend import (
    ModelEventExpectation,
)
from fpl_engine.models.events.market_prior import (
    PlayerMarketPrior,
)
from fpl_engine.models.events.market_validation import (
    MarketBlendOutcome,
    walk_forward_market_blend,
)


def parse_time(value: str) -> datetime:
    value = value.replace(
        "Z",
        "+00:00",
    )

    result = datetime.fromisoformat(
        value
    )

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise ValueError(
            "timestamp must be timezone-aware"
        )

    return result.astimezone(
        timezone.utc
    )


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def select_pre_deadline_run(
    root: Path,
    *,
    season: str,
    gameweek: int,
) -> Path:

    base = (
        root
        / "scratch"
        / "book003"
        / "current_market_shadow"
        / season.replace("/", "-")
    )

    candidates = []

    for shadow_path in base.glob(
        "*/market_shadow.json"
    ):
        run_dir = shadow_path.parent

        fixture_path = (
            run_dir
            / "fixture_horizon.json"
        )

        player_path = (
            run_dir
            / "current_players.json"
        )

        if (
            not fixture_path.exists()
            or not player_path.exists()
        ):
            continue

        shadow = load_json(
            shadow_path
        )

        fixtures = load_json(
            fixture_path
        )

        gw_fixtures = [
            row
            for row in fixtures
            if (
                row.get(
                    "target_gameweek"
                )
                == gameweek
                and row.get(
                    "kickoff"
                )
            )
        ]

        if not gw_fixtures:
            continue

        first_kickoff = min(
            parse_time(
                row["kickoff"]
            )
            for row in gw_fixtures
        )

        prediction_timestamp = (
            parse_time(
                shadow[
                    "prediction_timestamp"
                ]
            )
        )

        # Strictly pre-deadline / pre-first-kickoff.
        if (
            prediction_timestamp
            < first_kickoff
        ):
            candidates.append(
                (
                    prediction_timestamp,
                    run_dir,
                )
            )

    if not candidates:
        raise SystemExit(
            "No pre-deadline market shadow "
            "snapshot found"
        )

    candidates.sort()

    return candidates[-1][1]


def reconstruct_model(
    payload,
) -> ModelEventExpectation:
    return ModelEventExpectation(
        fixture_id=payload[
            "fixture_id"
        ],
        player_id=payload[
            "player_id"
        ],
        prediction_timestamp=(
            parse_time(
                payload[
                    "prediction_timestamp"
                ]
            )
        ),
        expected_goals=payload[
            "expected_goals"
        ],
        expected_assists=payload[
            "expected_assists"
        ],
        expected_shots=payload[
            "expected_shots"
        ],
        expected_shots_on_target=(
            payload.get(
                "expected_shots_on_target"
            )
        ),
        model_version=payload[
            "model_version"
        ],
    )


def reconstruct_market(
    payload,
) -> PlayerMarketPrior:
    return PlayerMarketPrior(
        fixture_id=payload[
            "fixture_id"
        ],
        player_id=payload[
            "player_id"
        ],
        prediction_timestamp=(
            parse_time(
                payload[
                    "prediction_timestamp"
                ]
            )
        ),
        expected_goals=payload.get(
            "expected_goals"
        ),
        expected_assists=payload.get(
            "expected_assists"
        ),
        expected_shots=payload.get(
            "expected_shots"
        ),
        expected_shots_on_target=(
            payload.get(
                "expected_shots_on_target"
            )
        ),
        # Validation uses the already materialized
        # prior means; rebuilding raw signals is not
        # required here.
        signals=(),
        known_at=parse_time(
            payload["known_at"]
        ),
        warnings=tuple(
            payload.get(
                "warnings",
                (),
            )
        ),
        version=payload.get(
            "version",
            "player_market_prior_v1_poisson_inversion",
        ),
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--season",
        default="2026/27",
    )

    parser.add_argument(
        "--gameweek",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--minimum-observations",
        type=int,
        default=200,
    )

    args = parser.parse_args()

    root = Path(
        __file__
    ).resolve().parents[1]

    run_dir = (
        select_pre_deadline_run(
            root,
            season=args.season,
            gameweek=args.gameweek,
        )
    )

    print(
        "pre_deadline_run:",
        run_dir,
    )

    shadow = load_json(
        run_dir
        / "market_shadow.json"
    )

    players = load_json(
        run_dir
        / "current_players.json"
    )

    fixtures = load_json(
        run_dir
        / "fixture_horizon.json"
    )

    gw_fixture_ids = {
        row["fixture_id"]
        for row in fixtures
        if row.get(
            "target_gameweek"
        ) == args.gameweek
    }

    provider_to_canonical = {
        str(
            row["provider_id"]
        ): row["player_id"]
        for row in players
    }

    canonical_to_name = {
        row["player_id"]: row.get(
            "display_name",
            row["player_id"],
        )
        for row in players
    }

    raw_store = RawStore(
        root / "data" / "raw"
    )

    cache = HttpCache(
        root
        / "data"
        / "interim"
        / "http_cache",
    )

    # Force a fresh Official FPL read.
    # This does NOT use The Odds API.
    with httpx.Client() as client:

        adapter = OfficialFPLAdapter(
            client=client,
            cache=cache,
            raw_store=raw_store,
            ttl=timedelta(0),
        )

        fixture_result = (
            adapter.get_fixtures(
                event=args.gameweek
            )
        )

        live_result = (
            adapter.get_event_live(
                args.gameweek
            )
        )

    provider_fixtures = (
        fixture_result.payload
    )

    if not isinstance(
        provider_fixtures,
        list,
    ):
        raise SystemExit(
            "Official FPL fixtures payload "
            "is not a list"
        )

    finished = [
        row
        for row in provider_fixtures
        if (
            isinstance(row, dict)
            and row.get(
                "finished"
            ) is True
        )
    ]

    if (
        len(finished)
        != len(provider_fixtures)
        or not provider_fixtures
    ):
        print()
        print(
            "GW NOT COMPLETE"
        )
        print(
            "finished:",
            len(finished),
            "/",
            len(provider_fixtures),
        )
        print(
            "Run evaluator again after "
            "all fixtures are finished."
        )
        return 2

    live_payload = (
        live_result.payload
    )

    elements = live_payload.get(
        "elements"
    )

    if not isinstance(
        elements,
        list,
    ):
        raise SystemExit(
            "Official FPL live payload "
            "lacks elements list"
        )

    actual_by_canonical = {}

    for item in elements:

        if not isinstance(
            item,
            dict,
        ):
            continue

        provider_id = str(
            item.get("id")
            or ""
        )

        canonical_id = (
            provider_to_canonical.get(
                provider_id
            )
        )

        if canonical_id is None:
            continue

        stats = item.get(
            "stats"
        )

        if not isinstance(
            stats,
            dict,
        ):
            continue

        actual_by_canonical[
            canonical_id
        ] = {
            "goals": int(
                stats.get(
                    "goals_scored"
                )
                or 0
            ),
            "assists": int(
                stats.get(
                    "assists"
                )
                or 0
            ),
        }

    outcome_known_at = max(
        fixture_result.response.stored_at,
        live_result.response.stored_at,
    )

    outcomes = []

    skipped_no_market = 0
    skipped_no_actual = 0
    skipped_other_gw = 0

    for row in shadow[
        "players"
    ]:

        if (
            row["fixture_id"]
            not in gw_fixture_ids
        ):
            skipped_other_gw += 1
            continue

        market_payload = row.get(
            "market"
        )

        if market_payload is None:
            skipped_no_market += 1
            continue

        actual = (
            actual_by_canonical.get(
                row["player_id"]
            )
        )

        if actual is None:
            skipped_no_actual += 1
            continue

        outcomes.append(
            MarketBlendOutcome(
                model=reconstruct_model(
                    row["model"]
                ),
                market=reconstruct_market(
                    market_payload
                ),
                outcome_known_at=(
                    outcome_known_at
                ),
                goals=actual[
                    "goals"
                ],
                assists=actual[
                    "assists"
                ],
            )
        )

    if not outcomes:
        raise SystemExit(
            "No evaluable market outcomes "
            "were constructed"
        )

    report = (
        walk_forward_market_blend(
            outcomes,
            weights=(
                0.0,
                0.25,
                0.50,
                0.75,
                1.0,
            ),
            minimum_observations=(
                args.minimum_observations
            ),
            minimum_relative_improvement=(
                0.01
            ),
        )
    )

    output = {
        "evaluation_mode": (
            "GW_DIAGNOSTIC_ONLY"
        ),
        "production_promotion_allowed": (
            False
        ),
        "season": args.season,
        "gameweek": args.gameweek,
        "pre_deadline_run": str(
            run_dir
        ),
        "outcome_known_at": (
            outcome_known_at.isoformat()
        ),
        "outcomes": len(
            outcomes
        ),
        "skipped_no_market": (
            skipped_no_market
        ),
        "skipped_no_actual": (
            skipped_no_actual
        ),
        "validation_report": {
            "version": report.version,
            "goal_champion_market_weight": (
                report
                .goal_champion_market_weight
            ),
            "assist_champion_market_weight": (
                report
                .assist_champion_market_weight
            ),
            "goal_promoted_by_module": (
                report.goal_promoted
            ),
            "assist_promoted_by_module": (
                report.assist_promoted
            ),
            "goal_market_observations": (
                report
                .goal_market_observations
            ),
            "assist_market_observations": (
                report
                .assist_market_observations
            ),
            "warnings": list(
                report.warnings
            ),
            "candidates": [
                {
                    "candidate_id": (
                        row.candidate_id
                    ),
                    "market_weight": (
                        row.market_weight
                    ),
                    "goal_observations": (
                        row.goal_observations
                    ),
                    "goal_brier": (
                        row.goal_brier
                    ),
                    "goal_log_loss": (
                        row.goal_log_loss
                    ),
                    "goal_poisson_deviance": (
                        row
                        .goal_poisson_deviance
                    ),
                    "goal_calibration_error": (
                        row
                        .goal_calibration_error
                    ),
                    "assist_observations": (
                        row.assist_observations
                    ),
                    "assist_brier": (
                        row.assist_brier
                    ),
                    "assist_log_loss": (
                        row.assist_log_loss
                    ),
                    "assist_calibration_error": (
                        row
                        .assist_calibration_error
                    ),
                }
                for row in report.candidates
            ],
        },
    }

    output_path = (
        run_dir
        / (
            f"gw{args.gameweek}_"
            "market_validation.json"
        )
    )

    output_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "=== MARKET BLEND GW "
        "DIAGNOSTIC ==="
    )

    print(
        "season/gw:",
        args.season,
        args.gameweek,
    )

    print(
        "outcomes:",
        len(outcomes),
    )

    print(
        "goal_observations:",
        report.goal_market_observations,
    )

    print(
        "assist_observations:",
        report.assist_market_observations,
    )

    print()
    print(
        "weight | goal logloss | "
        "goal deviance | assist logloss"
    )

    for row in report.candidates:
        print(
            f"{row.market_weight:>4.2f}   | "
            f"{row.goal_log_loss:.5f}      | "
            f"{row.goal_poisson_deviance:.5f}       | "
            f"{row.assist_log_loss:.5f}"
        )

    print()
    print(
        "diagnostic_goal_best_weight:",
        report.goal_champion_market_weight,
    )

    print(
        "diagnostic_assist_best_weight:",
        report.assist_champion_market_weight,
    )

    print(
        "module_goal_promoted:",
        report.goal_promoted,
    )

    print(
        "module_assist_promoted:",
        report.assist_promoted,
    )

    print()
    print(
        "PRODUCTION PROMOTION: DISABLED"
    )

    print(
        "Reason: one GW is diagnostic "
        "evidence only; independent "
        "future validation is required."
    )

    print()
    print(
        "saved:",
        output_path,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
