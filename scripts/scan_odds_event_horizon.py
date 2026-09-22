from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import unicodedata

import httpx


FPL_BOOTSTRAP = (
    "https://fantasy.premierleague.com/"
    "api/bootstrap-static/"
)

FPL_FIXTURES = (
    "https://fantasy.premierleague.com/"
    "api/fixtures/"
)

ODDS_EVENTS = (
    "https://api.the-odds-api.com/"
    "v4/sports/soccer_epl/events"
)


TEAM_ALIASES = {
    "man utd": "manchester united",
    "manchester utd": "manchester united",

    "man city": "manchester city",

    "nott m forest": "nottingham forest",
    "nottm forest": "nottingham forest",

    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",

    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",

    "brighton": "brighton and hove albion",
    "brighton hove albion": (
        "brighton and hove albion"
    ),

    "newcastle": "newcastle united",

    "west ham": "west ham united",

    "leeds": "leeds united",

    "bournemouth": "afc bournemouth",

    "sheffield utd": "sheffield united",
}


def utcnow() -> datetime:
    return datetime.now(
        timezone.utc
    )


def parse_time(
    value: str,
) -> datetime:

    result = datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
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


def iso_z(
    value: datetime,
) -> str:

    return (
        value.astimezone(
            timezone.utc
        )
        .isoformat(
            timespec="seconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def normalize_team(
    value: str,
) -> str:

    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    text = text.casefold()

    text = text.replace(
        "&",
        " and ",
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if text.endswith(" fc"):
        text = text[:-3].strip()

    return TEAM_ALIASES.get(
        text,
        text,
    )


def fixture_key(
    home: str,
    away: str,
) -> tuple[str, str]:

    return tuple(
        sorted(
            (
                normalize_team(home),
                normalize_team(away),
            )
        )
    )


def best_event_match(
    *,
    home: str,
    away: str,
    kickoff: datetime,
    provider_events: list[dict],
    max_delta_hours: float = 36.0,
) -> tuple[
    dict | None,
    float | None,
]:

    target_key = fixture_key(
        home,
        away,
    )

    candidates = []

    for event in provider_events:

        event_key = fixture_key(
            event["home_team"],
            event["away_team"],
        )

        if event_key != target_key:
            continue

        provider_kickoff = parse_time(
            event["commence_time"]
        )

        delta_hours = abs(
            (
                provider_kickoff
                - kickoff
            ).total_seconds()
        ) / 3600.0

        if (
            delta_hours
            <= max_delta_hours
        ):
            candidates.append(
                (
                    delta_hours,
                    event,
                )
            )

    if not candidates:
        return None, None

    candidates.sort(
        key=lambda item: item[0]
    )

    return candidates[0][1], candidates[0][0]


def main() -> int:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--from-gw",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--to-gw",
        type=int,
        default=10,
    )

    args = parser.parse_args()

    if args.from_gw <= 0:
        raise SystemExit(
            "--from-gw must be positive"
        )

    if args.to_gw < args.from_gw:
        raise SystemExit(
            "--to-gw must be >= --from-gw"
        )

    api_key = os.getenv(
        "THE_ODDS_API_KEY"
    )

    if not api_key:
        raise SystemExit(
            "THE_ODDS_API_KEY is not set"
        )

    root = Path(
        __file__
    ).resolve().parents[1]

    now = utcnow()

    with httpx.Client(
        timeout=30.0,
    ) as client:

        bootstrap_response = client.get(
            FPL_BOOTSTRAP
        )
        bootstrap_response.raise_for_status()

        fixtures_response = client.get(
            FPL_FIXTURES
        )
        fixtures_response.raise_for_status()

        bootstrap = (
            bootstrap_response.json()
        )

        all_fixtures = (
            fixtures_response.json()
        )

        teams = {
            int(row["id"]): row["name"]
            for row in bootstrap["teams"]
        }

        wanted = [
            row
            for row in all_fixtures
            if (
                row.get("event")
                is not None
                and args.from_gw
                <= int(row["event"])
                <= args.to_gw
                and row.get(
                    "kickoff_time"
                )
            )
        ]

        if not wanted:
            raise SystemExit(
                "No FPL fixtures found "
                "for requested horizon"
            )

        kickoff_times = [
            parse_time(
                row["kickoff_time"]
            )
            for row in wanted
        ]

        commence_from = (
            min(kickoff_times)
            - timedelta(days=1)
        )

        commence_to = (
            max(kickoff_times)
            + timedelta(days=1)
        )

        # IMPORTANT:
        # This is /events only.
        # No odds or player-prop endpoint
        # is called by this script.
        odds_response = client.get(
            ODDS_EVENTS,
            params={
                "apiKey": api_key,
                "dateFormat": "iso",
                "commenceTimeFrom": (
                    iso_z(
                        commence_from
                    )
                ),
                "commenceTimeTo": (
                    iso_z(
                        commence_to
                    )
                ),
            },
        )

        odds_response.raise_for_status()

        provider_events = (
            odds_response.json()
        )

    if not isinstance(
        provider_events,
        list,
    ):
        raise SystemExit(
            "The Odds API events "
            "response is not a list"
        )

    request_cost = (
        odds_response.headers.get(
            "x-requests-last"
        )
    )

    request_used = (
        odds_response.headers.get(
            "x-requests-used"
        )
    )

    request_remaining = (
        odds_response.headers.get(
            "x-requests-remaining"
        )
    )

    rows = []

    summary = []

    for gw in range(
        args.from_gw,
        args.to_gw + 1,
    ):

        gw_fixtures = [
            row
            for row in wanted
            if int(
                row["event"]
            ) == gw
        ]

        matched = 0
        unmatched = []

        days_ahead = []

        for fixture in gw_fixtures:

            home = teams[
                int(
                    fixture["team_h"]
                )
            ]

            away = teams[
                int(
                    fixture["team_a"]
                )
            ]

            kickoff = parse_time(
                fixture[
                    "kickoff_time"
                ]
            )

            provider_event, delta = (
                best_event_match(
                    home=home,
                    away=away,
                    kickoff=kickoff,
                    provider_events=(
                        provider_events
                    ),
                )
            )

            row = {
                "gameweek": gw,
                "home_team": home,
                "away_team": away,
                "fpl_kickoff": (
                    iso_z(kickoff)
                ),
                "matched": (
                    provider_event
                    is not None
                ),
                "provider_event_id": (
                    provider_event.get(
                        "id"
                    )
                    if provider_event
                    else None
                ),
                "provider_home_team": (
                    provider_event.get(
                        "home_team"
                    )
                    if provider_event
                    else None
                ),
                "provider_away_team": (
                    provider_event.get(
                        "away_team"
                    )
                    if provider_event
                    else None
                ),
                "provider_kickoff": (
                    provider_event.get(
                        "commence_time"
                    )
                    if provider_event
                    else None
                ),
                "kickoff_delta_hours": (
                    delta
                ),
            }

            rows.append(
                row
            )

            if provider_event:
                matched += 1

                days_ahead.append(
                    (
                        kickoff
                        - now
                    ).total_seconds()
                    / 86400.0
                )

            else:
                unmatched.append(
                    f"{home} vs {away}"
                )

        total = len(
            gw_fixtures
        )

        rate = (
            matched / total
            if total
            else 0.0
        )

        summary.append({
            "gameweek": gw,
            "fpl_fixtures": total,
            "provider_matches": matched,
            "coverage": rate,
            "unmatched": unmatched,
            "min_days_ahead": (
                min(days_ahead)
                if days_ahead
                else None
            ),
            "max_days_ahead": (
                max(days_ahead)
                if days_ahead
                else None
            ),
        })

    full_gws = [
        row["gameweek"]
        for row in summary
        if (
            row["fpl_fixtures"] > 0
            and row["provider_matches"]
            == row["fpl_fixtures"]
        )
    ]

    any_gws = [
        row["gameweek"]
        for row in summary
        if row["provider_matches"] > 0
    ]

    continuous_full_through = None

    for row in summary:

        if (
            row["fpl_fixtures"] > 0
            and row["provider_matches"]
            == row["fpl_fixtures"]
        ):
            continuous_full_through = (
                row["gameweek"]
            )
        else:
            break

    timestamp = (
        now.strftime(
            "%Y%m%dT%H%M%SZ"
        )
    )

    output_dir = (
        root
        / "scratch"
        / "book004"
        / "market_horizon_scan"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{timestamp}.json"
    )

    payload = {
        "generated_at": (
            iso_z(now)
        ),
        "from_gameweek": (
            args.from_gw
        ),
        "to_gameweek": (
            args.to_gw
        ),
        "provider_events_returned": (
            len(provider_events)
        ),
        "odds_api_headers": {
            "x_requests_last": (
                request_cost
            ),
            "x_requests_used": (
                request_used
            ),
            "x_requests_remaining": (
                request_remaining
            ),
        },
        "summary": summary,
        "fixtures": rows,
        "full_gameweeks": (
            full_gws
        ),
        "gameweeks_with_any_events": (
            any_gws
        ),
        "continuous_full_through": (
            continuous_full_through
        ),
    }

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "=== THE ODDS API FREE EVENT HORIZON ==="
    )

    print(
        "requested_gws:",
        f"{args.from_gw}-"
        f"{args.to_gw}",
    )

    print(
        "provider_events_returned:",
        len(provider_events),
    )

    print()
    print(
        "ODDS API USAGE HEADERS"
    )

    print(
        "x-requests-last:",
        request_cost,
    )

    print(
        "x-requests-used:",
        request_used,
    )

    print(
        "x-requests-remaining:",
        request_remaining,
    )

    print()
    print(
        "=== GAMEWEEK COVERAGE ==="
    )

    for row in summary:

        print(
            f"GW{row['gameweek']:<2}  "
            f"{row['provider_matches']:>2}/"
            f"{row['fpl_fixtures']:<2}  "
            f"{row['coverage']:>6.1%}",
            end="",
        )

        if (
            row["min_days_ahead"]
            is not None
        ):
            print(
                "  kickoff in "
                f"{row['min_days_ahead']:.1f}"
                "-"
                f"{row['max_days_ahead']:.1f}"
                " days"
            )
        else:
            print()

        for fixture in row[
            "unmatched"
        ]:
            print(
                "     MISS:",
                fixture,
            )

    print()
    print(
        "full_gameweeks:",
        full_gws,
    )

    print(
        "gameweeks_with_any_events:",
        any_gws,
    )

    print(
        "continuous_full_through:",
        (
            f"GW{continuous_full_through}"
            if continuous_full_through
            is not None
            else "none"
        ),
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
