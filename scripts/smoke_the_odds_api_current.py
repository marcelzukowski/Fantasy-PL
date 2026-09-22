from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import httpx

from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.providers.the_odds_api import (
    SUPPORTED_MARKETS,
    TheOddsApiAdapter,
)


CACHE_ROOT = Path(
    "data/cache/the_odds_api"
)

RAW_ROOT = Path(
    "data/raw"
)

OUTPUT_ROOT = Path(
    "scratch/book003"
)


def usage_headers(response):
    headers = response.headers

    return {
        "x_requests_last": headers.get(
            "x-requests-last"
        ),
        "x_requests_used": headers.get(
            "x-requests-used"
        ),
        "x_requests_remaining": headers.get(
            "x-requests-remaining"
        ),
    }


def market_summary(payload):
    bookmakers = payload.get(
        "bookmakers",
        []
    )

    summary = {}

    player_names = set()

    for bookmaker in bookmakers:
        bookmaker_key = bookmaker.get(
            "key",
            "UNKNOWN",
        )

        for market in bookmaker.get(
            "markets",
            [],
        ):
            key = market.get(
                "key"
            )

            if key not in SUPPORTED_MARKETS:
                continue

            row = summary.setdefault(
                key,
                {
                    "bookmakers": set(),
                    "outcomes": 0,
                    "players": set(),
                    "sides": set(),
                    "lines": set(),
                },
            )

            row["bookmakers"].add(
                bookmaker_key
            )

            outcomes = market.get(
                "outcomes",
                [],
            )

            row["outcomes"] += len(
                outcomes
            )

            for outcome in outcomes:
                player = outcome.get(
                    "description"
                )

                if isinstance(
                    player,
                    str,
                ) and player.strip():
                    player = player.strip()

                    row["players"].add(
                        player
                    )

                    player_names.add(
                        player
                    )

                side = outcome.get(
                    "name"
                )

                if isinstance(
                    side,
                    str,
                ):
                    row["sides"].add(
                        side
                    )

                point = outcome.get(
                    "point"
                )

                if point is not None:
                    row["lines"].add(
                        point
                    )

    normalized = {}

    for key, row in summary.items():
        normalized[key] = {
            "bookmaker_count": len(
                row["bookmakers"]
            ),
            "bookmakers": sorted(
                row["bookmakers"]
            ),
            "outcome_count": (
                row["outcomes"]
            ),
            "player_count": len(
                row["players"]
            ),
            "sides": sorted(
                row["sides"]
            ),
            "lines": sorted(
                row["lines"]
            ),
        }

    return (
        normalized,
        sorted(player_names),
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--event-id",
        default=None,
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
    )

    args = parser.parse_args()

    api_key = os.environ.get(
        "THE_ODDS_API_KEY"
    )

    if not api_key:
        raise SystemExit(
            "THE_ODDS_API_KEY is not set"
        )

    if args.days < 1:
        raise SystemExit(
            "--days must be >= 1"
        )

    now = datetime.now(
        timezone.utc
    )

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache = HttpCache(
        CACHE_ROOT
    )

    raw_store = RawStore(
        RAW_ROOT
    )

    with httpx.Client() as client:
        adapter = TheOddsApiAdapter(
            client=client,
            cache=cache,
            raw_store=raw_store,
            api_key=api_key,
            ttl=timedelta(
                minutes=10
            ),
        )

        events = adapter.get_events(
            commence_time_from=(
                now
                - timedelta(hours=3)
            ),
            commence_time_to=(
                now
                + timedelta(
                    days=args.days
                )
            ),
        )

        event_rows = [
            {
                "event_id": (
                    event.provider_event_id
                ),
                "kickoff": (
                    event.commence_time.isoformat()
                ),
                "home_team": (
                    event.home_team
                ),
                "away_team": (
                    event.away_team
                ),
            }
            for event in events.events
        ]

        discovery_output = {
            "retrieved_at": (
                events.retrieved_at.isoformat()
            ),
            "from_cache": (
                events.from_cache
            ),
            "raw_snapshot_id": (
                events.raw_snapshot.snapshot_id
                if events.raw_snapshot
                is not None
                else None
            ),
            "usage": usage_headers(
                events.response
            ),
            "event_count": len(
                event_rows
            ),
            "events": event_rows,
        }

        discovery_path = (
            OUTPUT_ROOT
            / "current_events.json"
        )

        discovery_path.write_text(
            json.dumps(
                discovery_output,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print("=== EPL EVENTS ===")
        print(
            "count:",
            len(event_rows),
        )

        print(
            "from_cache:",
            events.from_cache,
        )

        print(
            "usage:",
            discovery_output["usage"],
        )

        print()

        for index, event in enumerate(
            event_rows,
            start=1,
        ):
            print(
                f"{index:2d}. "
                f"{event['kickoff']} | "
                f"{event['home_team']} vs "
                f"{event['away_team']} | "
                f"{event['event_id']}"
            )

        print()
        print(
            "saved:",
            discovery_path,
        )

        if args.event_id is None:
            print()
            print(
                "DISCOVERY ONLY - "
                "no player-prop request made"
            )
            return

        matching = [
            event
            for event in events.events
            if (
                event.provider_event_id
                == args.event_id
            )
        ]

        if len(matching) != 1:
            raise SystemExit(
                "--event-id must match exactly "
                "one discovered EPL event"
            )

        selected = matching[0]

        odds = adapter.get_event_odds(
            event_id=(
                selected.provider_event_id
            ),
            regions=("us",),
            markets=SUPPORTED_MARKETS,
        )

        (
            markets,
            player_names,
        ) = market_summary(
            odds.payload
        )

        odds_output = {
            "event": {
                "event_id": (
                    selected.provider_event_id
                ),
                "kickoff": (
                    selected.commence_time.isoformat()
                ),
                "home_team": (
                    selected.home_team
                ),
                "away_team": (
                    selected.away_team
                ),
            },
            "retrieved_at": (
                odds.retrieved_at.isoformat()
            ),
            "from_cache": (
                odds.from_cache
            ),
            "raw_snapshot_id": (
                odds.raw_snapshot.snapshot_id
                if odds.raw_snapshot
                is not None
                else None
            ),
            "usage": usage_headers(
                odds.response
            ),
            "bookmaker_count": len(
                odds.payload.get(
                    "bookmakers",
                    [],
                )
            ),
            "markets": markets,
            "provider_player_names": (
                player_names
            ),
        }

        odds_path = (
            OUTPUT_ROOT
            / "current_event_odds.json"
        )

        odds_path.write_text(
            json.dumps(
                odds_output,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        print()
        print("=== PLAYER PROPS ===")

        print(
            selected.home_team,
            "vs",
            selected.away_team,
        )

        print(
            "bookmakers:",
            odds_output[
                "bookmaker_count"
            ],
        )

        print(
            "usage:",
            odds_output["usage"],
        )

        for key in SUPPORTED_MARKETS:
            row = markets.get(
                key
            )

            if row is None:
                print(
                    key,
                    "-> NOT RETURNED",
                )
                continue

            print(
                key,
                "->",
                f"books={row['bookmaker_count']}",
                f"players={row['player_count']}",
                f"outcomes={row['outcome_count']}",
                f"sides={row['sides']}",
                f"lines={row['lines'][:8]}",
            )

        print()
        print(
            "provider player names:",
            len(player_names),
        )

        for name in player_names[:20]:
            print(
                " -",
                name,
            )

        if len(player_names) > 20:
            print(
                f" ... +{len(player_names) - 20}"
            )

        print()
        print(
            "saved:",
            odds_path,
        )


if __name__ == "__main__":
    main()
