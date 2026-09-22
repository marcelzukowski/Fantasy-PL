from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import unicodedata
from difflib import SequenceMatcher

import httpx

from fpl_engine.current import (
    CurrentPipelineConfig,
    CurrentPredictionPipeline,
    OfficialCurrentDataSource,
)
from fpl_engine.data.database import CanonicalDatabase
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.local_fpl_snapshots import LocalFPLSnapshotStore
from fpl_engine.data.odds_identity import (
    OddsPlayerAlias,
    OddsPlayerAliasRegistry,
    normalize_odds_player_alias,
    persist_fixture_identity_matches,
)
from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter
from fpl_engine.data.providers.the_odds_api import (
    CanonicalFixtureCandidate,
    SUPPORTED_MARKETS,
    TheOddsApiAdapter,
    match_events_to_canonical_fixtures,
    parse_market_quotes,
)
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.schemas.entities import ReviewStatus
from fpl_engine.types import PredictionContext


VALIDATION_MARKETS = (
    "player_goal_scorer_anytime",
    "player_assists",
)


def utcnow():
    return datetime.now(timezone.utc)


def season_start(season):
    year = int(season.split("/", 1)[0])
    return datetime(year, 7, 1, tzinfo=timezone.utc)


def team_key(value):
    text = unicodedata.normalize("NFKD", value)

    text = "".join(
        ch
        for ch in text
        if not unicodedata.combining(ch)
    )

    text = text.casefold().replace(
        "&",
        " and ",
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = " ".join(
        text.split()
    )

    replacements = {
        "man city": "manchester city",
        "man utd": "manchester united",
        "man united": "manchester united",
        "nott m forest": "nottingham forest",
        "nottm forest": "nottingham forest",
        "spurs": "tottenham",
        "tottenham hotspur": "tottenham",
        "brighton and hove albion": "brighton",
    }

    text = replacements.get(
        text,
        text,
    )

    if text not in {
        "manchester city",
        "manchester united",
    }:
        for suffix in (
            " city",
            " town",
            " united",
            " hotspur",
        ):
            if text.endswith(suffix):
                text = text[
                    :-len(suffix)
                ].strip()
                break

    return text



def loose_player_name(value):
    value = str(value).translate(
        str.maketrans({
            "?": "o",
            "?": "O",
            "?": "l",
            "?": "L",
            "?": "i",
            "?": "I",
            "?": "d",
            "?": "D",
            "?": "d",
            "?": "D",
            "?": "th",
            "?": "Th",
            "?": "ae",
            "?": "Ae",
            "?": "oe",
            "?": "Oe",
            "?": "ss",
        })
    )

    text = unicodedata.normalize(
        "NFKD",
        value,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.casefold()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


def player_alias_values(row):
    payload = row.get(
        "provider_payload"
    )

    if not isinstance(
        payload,
        dict,
    ):
        payload = {}

    full_name = " ".join(
        str(
            payload.get(key)
            or ""
        ).strip()
        for key in (
            "first_name",
            "second_name",
        )
    ).strip()

    return tuple(
        value
        for value in (
            full_name,
            str(
                payload.get(
                    "web_name"
                )
                or ""
            ).strip(),
            str(
                row.get(
                    "display_name"
                )
                or ""
            ).strip(),
        )
        if value
    )


def safe_player_match(
    provider_name,
    current_players,
    *,
    allowed_team_ids,
):
    provider_loose = (
        loose_player_name(
            provider_name
        )
    )

    provider_tokens = tuple(
        provider_loose.split()
    )

    provider_set = set(
        provider_tokens
    )

    scored = []

    for row in current_players:

        if (
            row.get("team_id")
            not in allowed_team_ids
        ):
            continue

        player_id = str(
            row.get("player_id")
            or ""
        ).strip()

        if not player_id:
            continue

        best_score = 0.0
        best_method = None

        for alias in player_alias_values(
            row
        ):
            loose = loose_player_name(
                alias
            )

            if not loose:
                continue

            tokens = tuple(
                loose.split()
            )

            token_set = set(
                tokens
            )

            # Same textual name after accents,
            # punctuation and whitespace removal.
            if loose == provider_loose:
                score = 1.0
                method = (
                    "loose_exact"
                )

            # Same complete token set but a different
            # provider ordering, e.g.
            # "Magalhaes Gabriel"
            # vs "Gabriel Magalhaes".
            elif (
                len(provider_set) >= 2
                and provider_set == token_set
            ):
                score = 0.995
                method = (
                    "token_set_exact"
                )

            # Useful for e.g.
            # Bruno Fernandes
            # vs Bruno Borges Fernandes,
            # Abdul Fatawu
            # vs Abdul Fatawu Issahaku.
            elif (
                len(provider_set) >= 2
                and len(token_set) >= 2
                and (
                    provider_set
                    <= token_set
                    or token_set
                    <= provider_set
                )
                and (
                    provider_tokens[-1]
                    == tokens[-1]
                    or provider_tokens[0]
                    == tokens[0]
                )
            ):
                score = 0.97
                method = (
                    "unique_token_subset"
                )

            elif (
                provider_tokens
                and tokens
                and provider_tokens[-1]
                    == tokens[-1]
                and len(provider_tokens[0]) >= 3
                and len(tokens[0]) >= 3
                and (
                    provider_tokens[0].startswith(
                        tokens[0]
                    )
                    or tokens[0].startswith(
                        provider_tokens[0]
                    )
                )
            ):
                # e.g. Ben White / Benjamin White.
                # Still restricted to the two teams
                # taking part in this fixture.
                score = 0.96
                method = (
                    "first_name_prefix"
                )

            else:
                ratio = (
                    SequenceMatcher(
                        None,
                        provider_loose,
                        loose,
                    ).ratio()
                )

                # Strong first-name/surname
                # correspondence, restricted
                # to the two clubs in fixture.
                same_first = (
                    provider_tokens
                    and tokens
                    and (
                        provider_tokens[0]
                        == tokens[0]
                        or provider_tokens[0][0]
                        == tokens[0][0]
                    )
                )

                same_last = (
                    provider_tokens
                    and tokens
                    and provider_tokens[-1]
                    == tokens[-1]
                )

                if (
                    ratio >= 0.90
                    and same_first
                    and same_last
                ):
                    score = ratio
                    method = (
                        "high_similarity"
                    )
                else:
                    score = 0.0
                    method = None

            if score > best_score:
                best_score = score
                best_method = method

        if best_score > 0:
            scored.append(
                (
                    best_score,
                    player_id,
                    best_method,
                )
            )

    scored.sort(
        reverse=True
    )

    if not scored:
        return None

    best = scored[0]

    # Fail closed if another player from
    # these two teams is too close.
    if (
        len(scored) > 1
        and scored[1][0]
        >= best[0] - 0.05
    ):
        return None

    if best[0] < 0.90:
        return None

    return (
        best[1],
        best[2],
        best[0],
    )


def provider_player_names(payload):
    names = set()

    for bookmaker in payload.get(
        "bookmakers",
        [],
    ):
        if not isinstance(
            bookmaker,
            dict,
        ):
            continue

        for market in bookmaker.get(
            "markets",
            [],
        ):
            if not isinstance(
                market,
                dict,
            ):
                continue

            if (
                market.get("key")
                not in SUPPORTED_MARKETS
            ):
                continue

            for outcome in market.get(
                "outcomes",
                [],
            ):
                if not isinstance(
                    outcome,
                    dict,
                ):
                    continue

                name = outcome.get(
                    "description"
                )

                if (
                    isinstance(name, str)
                    and name.strip()
                ):
                    names.add(
                        name.strip()
                    )

    return tuple(
        sorted(names)
    )


def exact_player_candidates(
    current_players,
):
    candidates = defaultdict(set)

    for row in current_players:
        player_id = str(
            row.get("player_id")
            or ""
        ).strip()

        payload = row.get(
            "provider_payload"
        )

        if (
            not player_id
            or not isinstance(
                payload,
                dict,
            )
        ):
            continue

        full_name = " ".join(
            str(
                payload.get(key)
                or ""
            ).strip()
            for key in (
                "first_name",
                "second_name",
            )
        ).strip()

        aliases = (
            full_name,
            str(
                payload.get("web_name")
                or ""
            ).strip(),
            str(
                row.get("display_name")
                or ""
            ).strip(),
        )

        for alias in aliases:
            if alias:
                candidates[
                    normalize_odds_player_alias(
                        alias
                    )
                ].add(
                    player_id
                )

    return candidates


def seed_safe_aliases(
    registry,
    provider_names,
    current_players,
    *,
    allowed_team_ids,
    start,
    at,
    retrieved_at,
):
    exact_candidates = (
        exact_player_candidates(
            current_players
        )
    )

    created = 0
    unresolved = []
    methods = defaultdict(int)

    for provider_name in provider_names:

        key = (
            normalize_odds_player_alias(
                provider_name
            )
        )

        player_ids = (
            exact_candidates.get(
                key,
                set(),
            )
        )

        player_id = None
        method = None

        if len(player_ids) == 1:
            player_id = next(
                iter(player_ids)
            )
            method = "exact"

        else:
            match = safe_player_match(
                provider_name,
                current_players,
                allowed_team_ids=(
                    allowed_team_ids
                ),
            )

            if match is not None:
                (
                    player_id,
                    method,
                    _score,
                ) = match

        if player_id is None:
            unresolved.append(
                provider_name
            )
            continue

        was_created = registry.add(
            OddsPlayerAlias(
                provider_player_name=(
                    provider_name
                ),
                player_id=player_id,
                effective_from=start,
                effective_to=None,
                review_status=(
                    ReviewStatus.confirmed
                ),
                created_at=at,
                updated_at=at,
                source_record_id=(
                    "auto_current_"
                    + str(method)
                ),
                retrieved_at=(
                    retrieved_at
                ),
            )
        )

        if was_created:
            created += 1
            methods[
                str(method)
            ] += 1

    return (
        created,
        tuple(
            sorted(unresolved)
        ),
        dict(methods),
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
        "--simulation-count",
        type=int,
        default=64,
    )

    parser.add_argument(
        "--projection-horizon",
        type=int,
        default=6,
        help=(
            "Number of Gameweeks to project. "
            "Default keeps production-compatible "
            "six-GW behaviour."
        ),
    )

    parser.add_argument(
        "--no-goal-allocation-proxy",
        dest="goal_allocation_proxy",
        action="store_false",
        default=True,
        help=(
            "Rollback to frozen EventModels V1 "
            "instead of the promoted canonical "
            "goal-allocation model."
        ),
    )

    parser.add_argument(
        "--goal-allocation-source-season",
        default=None,
        help=(
            "Optional STRICT prior season used "
            "for goal-allocation evidence, "
            "for example 2025-26. "
            "Cannot be combined with --no-goal-allocation-proxy."
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )

    parser.add_argument(
        "--offline-odds-cache",
        action="store_true",
        help=(
            "Use The Odds API HTTP cache only. "
            "Network access is blocked and cache misses fail."
        ),
    )

    args = parser.parse_args()

    if (
        args.goal_allocation_source_season
        and not args.goal_allocation_proxy
    ):
        parser.error(
            "--goal-allocation-source-season "
            "cannot be combined with --no-goal-allocation-proxy"
        )


    api_key = os.environ.get(
        "THE_ODDS_API_KEY"
    )

    if not api_key:
        raise SystemExit(
            "THE_ODDS_API_KEY is not set"
        )

    root = Path(
        __file__
    ).resolve().parents[1]

    raw_store = RawStore(
        root / "data" / "raw"
    )

    official_cache = HttpCache(
        root
        / "data"
        / "interim"
        / "http_cache",
        clock=utcnow,
    )

    odds_cache = HttpCache(
        root
        / "data"
        / "cache"
        / "the_odds_api",
        clock=(
            (
                lambda: datetime(
                    2000,
                    1,
                    1,
                    tzinfo=timezone.utc,
                )
            )
            if args.offline_odds_cache
            else utcnow
        ),
    )

    local = LocalFPLSnapshotStore(
        root / "data" / "snapshots",
        raw_store=raw_store,
    )

    canonical_db = (
        root
        / "data"
        / "processed"
        / "canonical"
        / "current.duckdb"
    )

    alias_path = (
        root
        / "data"
        / "processed"
        / "identity"
        / "odds_player_aliases.json"
    )

    baseline_root = (
        root
        / "scratch"
        / "book003"
        / "current_baseline"
    )

    shadow_root = (
        root
        / "scratch"
        / "book003"
        / "current_market_shadow"
    )

    with httpx.Client() as client:

        official = OfficialFPLAdapter(
            client=client,
            cache=official_cache,
            raw_store=raw_store,
            ttl=timedelta(
                minutes=5
            ),
            clock=utcnow,
        )

        source = OfficialCurrentDataSource(
            official,
            local_snapshots=local,
        )

        refresh_context = (
            PredictionContext(
                prediction_timestamp=(
                    utcnow()
                ),
                target_gameweek=(
                    args.gameweek
                ),
                target_season=(
                    args.season
                ),
            )
        )

        materialized_source = (
            source.refresh(
                refresh_context
            )
        )

        at = utcnow()

        context = PredictionContext(
            prediction_timestamp=at,
            target_gameweek=args.gameweek,
            target_season=args.season,
        )

        baseline_pipeline = (
            CurrentPredictionPipeline(
                source,
                project_root=root,
                config=CurrentPipelineConfig(
                    canonical_database=(
                        canonical_db
                    ),
                    output_root=(
                        baseline_root
                    ),
                    simulations_per_fixture=(
                        args.simulation_count
                    ),
                    random_seed=args.seed,
                    projection_horizon_gameweeks=args.projection_horizon,
                    goal_allocation_proxy_enabled=args.goal_allocation_proxy,
                    goal_allocation_source_season=args.goal_allocation_source_season,
                ),
                progress=lambda message: print(
                    f"[baseline] {message}"
                ),
            )
        )

        baseline = (
            baseline_pipeline.run(
                context,
                materialized_source=(
                    materialized_source
                ),
            )
        )

        current_players = json.loads(
            baseline.artifacts[
                "current_players"
            ].read_text(
                encoding="utf-8"
            )
        )

        current_fixtures = tuple(
            fixture
            for fixture
            in baseline.fixture_horizon
            if (
                fixture.target_gameweek
                == args.gameweek
                and fixture.kickoff
                is not None
            )
        )

        if not current_fixtures:
            raise SystemExit(
                "No scheduled fixtures "
                "found for target Gameweek"
            )

        provider_team_to_canonical = {}

        for fixture in current_fixtures:

            provider_team_to_canonical[
                fixture.home_provider_team_id
            ] = fixture.home_team_id

            provider_team_to_canonical[
                fixture.away_provider_team_id
            ] = fixture.away_team_id

        team_aliases = defaultdict(set)

        teams = (
            materialized_source
            .bootstrap
            .payload
            .get(
                "teams",
                [],
            )
        )

        for team in teams:
            if not isinstance(
                team,
                dict,
            ):
                continue

            provider_id = str(
                team.get("id")
                or ""
            )

            canonical_id = (
                provider_team_to_canonical
                .get(
                    provider_id
                )
            )

            if canonical_id is None:
                continue

            for value in (
                team.get("name"),
                team.get("short_name"),
            ):
                if (
                    isinstance(
                        value,
                        str,
                    )
                    and value.strip()
                ):
                    team_aliases[
                        team_key(value)
                    ].add(
                        canonical_id
                    )

        def team_resolver(
            provider_name,
        ):
            matches = team_aliases.get(
                team_key(
                    provider_name
                ),
                set(),
            )

            if len(matches) != 1:
                return None

            return next(
                iter(matches)
            )

        if args.offline_odds_cache:

            def offline_handler(request):
                raise httpx.ConnectError(
                    (
                        "OFFLINE ODDS CACHE MISS - "
                        "network request blocked"
                    ),
                    request=request,
                )

            odds_client = httpx.Client(
                transport=httpx.MockTransport(
                    offline_handler
                )
            )

        else:
            odds_client = client

        odds = TheOddsApiAdapter(
            client=odds_client,
            cache=odds_cache,
            raw_store=raw_store,
            api_key=api_key,
            ttl=timedelta(
                minutes=5
            ),
            clock=utcnow,
        )

        kickoff_start = (
            min(
                fixture.kickoff
                for fixture
                in current_fixtures
            )
            - timedelta(hours=12)
        )

        kickoff_end = (
            max(
                fixture.kickoff
                for fixture
                in current_fixtures
            )
            + timedelta(hours=12)
        )

        events = odds.get_events(
            commence_time_from=(
                kickoff_start
            ),
            commence_time_to=(
                kickoff_end
            ),
        )

        candidates = tuple(
            CanonicalFixtureCandidate(
                fixture_id=(
                    fixture.fixture_id
                ),
                home_team_id=(
                    fixture.home_team_id
                ),
                away_team_id=(
                    fixture.away_team_id
                ),
                kickoff=fixture.kickoff,
            )
            for fixture
            in current_fixtures
        )

        audit = (
            match_events_to_canonical_fixtures(
                events,
                team_resolver=(
                    team_resolver
                ),
                canonical_fixtures=(
                    candidates
                ),
            )
        )

        if (
            audit.unresolved_team_events
            or audit.unresolved_fixture_events
            or audit.ambiguous_fixture_events
        ):
            raise SystemExit(
                "Bookmaker fixture identity "
                "is incomplete: "
                f"unresolved_team_names="
                f"{audit.unresolved_team_names}, "
                f"unresolved_fixture_events="
                f"{audit.unresolved_fixture_events}, "
                f"ambiguous_fixture_events="
                f"{audit.ambiguous_fixture_events}"
            )

        database = CanonicalDatabase(
            canonical_db
        )

        try:
            persisted = (
                persist_fixture_identity_matches(
                    database,
                    audit,
                    effective_from=(
                        season_start(
                            args.season
                        )
                    ),
                    recorded_at=at,
                    retrieved_at=(
                        events.retrieved_at
                    ),
                    source_record_id=(
                        events.raw_snapshot.snapshot_id
                        if events.raw_snapshot
                        is not None
                        else events.response.cache_key
                    ),
                )
            )
        finally:
            database.close()

        fixture_by_id = {
            fixture.fixture_id: fixture
            for fixture in current_fixtures
        }

        alias_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        registry = (
            OddsPlayerAliasRegistry(
                alias_path
            )
        )

        requested_markets = (
            SUPPORTED_MARKETS
            if args.offline_odds_cache
            else VALIDATION_MARKETS
        )

        all_quotes = []

        unresolved_players = set()

        auto_aliases = 0
        auto_alias_method_counts = (
            defaultdict(int)
        )

        for match in audit.matches:

            result = (
                odds.get_event_odds(
                    event_id=(
                        match.provider_event_id
                    ),
                    regions=("us",),
                    markets=(
                        requested_markets
                    ),
                )
            )

            names = provider_player_names(
                dict(
                    result.payload
                )
            )

            canonical_fixture = (
                fixture_by_id[
                    match.canonical_fixture_id
                ]
            )

            (
                created,
                unresolved,
                alias_methods,
            ) = seed_safe_aliases(
                registry,
                names,
                current_players,
                allowed_team_ids={
                    canonical_fixture.home_team_id,
                    canonical_fixture.away_team_id,
                },
                start=(
                    season_start(
                        args.season
                    )
                ),
                at=at,
                retrieved_at=(
                    result.retrieved_at
                ),
            )

            auto_aliases += created

            for (
                method,
                count,
            ) in alias_methods.items():
                auto_alias_method_counts[
                    method
                ] += count

            unresolved_players.update(
                unresolved
            )

            parsed = (
                parse_market_quotes(
                    result,
                    canonical_fixture_id=(
                        match.canonical_fixture_id
                    ),
                    player_resolver=(
                        registry.resolver(
                            at=at
                        )
                    ),
                )
            )

            all_quotes.extend(
                parsed.quotes
            )

            unresolved_players.update(
                parsed.unresolved_players
            )

        shadow_pipeline = (
            CurrentPredictionPipeline(
                source,
                project_root=root,
                config=CurrentPipelineConfig(
                    canonical_database=(
                        canonical_db
                    ),
                    output_root=(
                        shadow_root
                    ),
                    simulations_per_fixture=(
                        args.simulation_count
                    ),
                    random_seed=args.seed,
                    projection_horizon_gameweeks=args.projection_horizon,
                    goal_allocation_proxy_enabled=args.goal_allocation_proxy,
                    goal_allocation_source_season=args.goal_allocation_source_season,
                ),
                progress=lambda message: print(
                    f"[shadow] {message}"
                ),
            )
        )

        shadow = (
            shadow_pipeline.run(
                context,
                materialized_source=(
                    materialized_source
                ),
                market_quotes=tuple(
                    all_quotes
                ),
            )
        )

    if (
        baseline.projections
        != shadow.projections
    ):
        raise SystemExit(
            "ERROR: market shadow changed "
            "production projections"
        )

    report = json.loads(
        shadow.artifacts[
            "market_shadow"
        ].read_text(
            encoding="utf-8"
        )
    )

    print()
    print(
        "=== LIVE CURRENT "
        "MARKET SHADOW ==="
    )

    print(
        "target_gw:",
        args.gameweek,
    )

    print(
        "canonical_fixtures:",
        len(current_fixtures),
    )

    print(
        "provider_events:",
        len(events.events),
    )

    print(
        "matched_events:",
        len(audit.matches),
    )

    print(
        "fixture_mappings_created:",
        len(persisted.created),
    )

    print(
        "fixture_mappings_reused:",
        len(persisted.reused),
    )

    print(
        "requested_markets:",
        requested_markets,
    )

    print(
        "canonical_market_quotes:",
        len(all_quotes),
    )

    print(
        "auto_exact_player_aliases_created:",
        auto_aliases,
    )

    print(
        "auto_alias_methods:",
        dict(
            sorted(
                auto_alias_method_counts.items()
            )
        ),
    )

    print(
        "unresolved_provider_players:",
        len(unresolved_players),
    )

    for name in sorted(
        unresolved_players
    )[:20]:
        print(
            " -",
            name,
        )

    if len(
        unresolved_players
    ) > 20:
        print(
            " ... +",
            len(
                unresolved_players
            ) - 20,
        )

    print(
        "selected_quote_count:",
        report[
            "selected_quote_count"
        ],
    )

    print(
        "one_sided_bookmaker_groups:",
        report[
            "one_sided_bookmaker_groups"
        ],
    )

    print(
        "consensus_count:",
        report[
            "consensus_count"
        ],
    )

    print(
        "prior_count:",
        report[
            "prior_count"
        ],
    )

    print(
        "players_with_market_prior:",
        report[
            "players_with_market_prior"
        ],
    )

    print(
        "players_without_market_prior:",
        report[
            "players_without_market_prior"
        ],
    )

    print(
        "production_projections_unchanged:",
        True,
    )

    print(
        "market_shadow:",
        shadow.artifacts[
            "market_shadow"
        ],
    )

    print(
        "run_manifest:",
        shadow.artifacts[
            "run_manifest"
        ],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
