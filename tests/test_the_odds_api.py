from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.market_odds import (
    MarketKind,
    MarketSide,
)
from fpl_engine.data.providers.the_odds_api import (
    TheOddsApiAdapter,
    TheOddsApiLeakageError,
    TheOddsApiParseError,
    TheOddsApiQuotaExceededError,
    parse_market_quotes,
)
from fpl_engine.data.raw_store import RawStore


NOW = datetime(
    2026,
    9,
    11,
    10,
    0,
    tzinfo=timezone.utc,
)

AT = datetime(
    2026,
    9,
    12,
    12,
    30,
    tzinfo=timezone.utc,
)


def event_payload():
    return {
        "id": "provider-event-1",
        "sport_key": "soccer_epl",
        "sport_title": "EPL",
        "commence_time": "2026-09-13T15:00:00Z",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "bookmakers": [
            {
                "key": "book-a",
                "title": "Book A",
                "last_update": "2026-09-12T12:00:00Z",
                "markets": [
                    {
                        "key": "player_goal_scorer_anytime",
                        "last_update": "2026-09-12T12:01:00Z",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Erling Haaland",
                                "price": 1.80,
                            },
                            {
                                "name": "Yes",
                                "description": "Unknown Player",
                                "price": 4.50,
                            },
                        ],
                    },
                    {
                        "key": "player_assists",
                        "last_update": "2026-09-12T12:02:00Z",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Erling Haaland",
                                "price": 2.60,
                                "point": 0.5,
                            },
                            {
                                "name": "Under",
                                "description": "Erling Haaland",
                                "price": 1.45,
                                "point": 0.5,
                            },
                        ],
                    },
                    {
                        "key": "player_shots",
                        "last_update": "2026-09-12T12:03:00Z",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Erling Haaland",
                                "price": 1.90,
                                "point": 2.5,
                            },
                            {
                                "name": "Under",
                                "description": "Erling Haaland",
                                "price": 1.90,
                                "point": 2.5,
                            },
                        ],
                    },
                    {
                        "key": "player_shots_on_target",
                        "last_update": "2026-09-12T12:04:00Z",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Erling Haaland",
                                "price": 1.80,
                                "point": 1.5,
                            },
                            {
                                "name": "Under",
                                "description": "Erling Haaland",
                                "price": 2.00,
                                "point": 1.5,
                            },
                        ],
                    },
                    {
                        "key": "h2h",
                        "last_update": "2026-09-12T12:00:00Z",
                        "outcomes": [],
                    },
                ],
            }
        ],
    }


def make_adapter(
    tmp_path,
    handler,
):
    transport = httpx.MockTransport(
        handler
    )

    client = httpx.Client(
        transport=transport
    )

    cache = HttpCache(
        tmp_path / "cache",
        clock=lambda: NOW,
    )

    raw = RawStore(
        tmp_path / "raw"
    )

    return (
        TheOddsApiAdapter(
            client=client,
            cache=cache,
            raw_store=raw,
            api_key="SUPER-SECRET",
            ttl=timedelta(minutes=1),
            clock=lambda: NOW,
        ),
        client,
    )


def test_current_event_odds_uses_cache_and_raw_store(
    tmp_path,
):
    calls = []

    def handler(request):
        calls.append(
            request
        )

        return httpx.Response(
            200,
            json=event_payload(),
            headers={
                "x-requests-last": "4",
                "x-requests-remaining": "496",
            },
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        first = adapter.get_event_odds(
            event_id="provider-event-1",
        )

        second = adapter.get_event_odds(
            event_id="provider-event-1",
        )
    finally:
        client.close()

    assert len(calls) == 1

    assert not first.from_cache
    assert first.raw_snapshot is not None

    assert second.from_cache
    assert second.raw_snapshot is None

    assert (
        first.payload["id"]
        == "provider-event-1"
    )

    assert (
        "SUPER-SECRET"
        not in (
            first.raw_snapshot.source_url
            or ""
        )
    )


def test_request_uses_decimal_iso_and_supported_markets(
    tmp_path,
):
    captured = {}

    def handler(request):
        captured["url"] = str(
            request.url
        )

        return httpx.Response(
            200,
            json=event_payload(),
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        adapter.get_event_odds(
            event_id="provider-event-1",
        )
    finally:
        client.close()

    url = captured["url"]

    assert "oddsFormat=decimal" in url
    assert "dateFormat=iso" in url
    assert "regions=us" in url

    assert (
        "player_goal_scorer_anytime"
        in url
    )

    assert "player_assists" in url
    assert "player_shots" in url
    assert "player_shots_on_target" in url


def test_historical_response_normalizes_wrapper_and_is_pit_safe(
    tmp_path,
):
    wrapper = {
        "timestamp": "2026-09-12T12:25:00Z",
        "previous_timestamp": "2026-09-12T12:20:00Z",
        "next_timestamp": "2026-09-12T12:30:00Z",
        "data": event_payload(),
    }

    def handler(request):
        return httpx.Response(
            200,
            json=wrapper,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = (
            adapter.get_historical_event_odds(
                event_id="provider-event-1",
                prediction_timestamp=AT,
            )
        )
    finally:
        client.close()

    assert result.historical

    assert (
        result.snapshot_timestamp
        == datetime(
            2026,
            9,
            12,
            12,
            25,
            tzinfo=timezone.utc,
        )
    )

    assert (
        result.snapshot_timestamp
        <= AT
    )

    assert (
        result.payload["id"]
        == "provider-event-1"
    )


def test_historical_snapshot_after_prediction_is_rejected(
    tmp_path,
):
    wrapper = {
        "timestamp": "2026-09-12T12:31:00Z",
        "data": event_payload(),
    }

    def handler(request):
        return httpx.Response(
            200,
            json=wrapper,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        with pytest.raises(
            TheOddsApiLeakageError
        ):
            adapter.get_historical_event_odds(
                event_id="provider-event-1",
                prediction_timestamp=AT,
            )
    finally:
        client.close()


def test_parser_maps_supported_markets_and_audits_unresolved(
    tmp_path,
):
    def handler(request):
        return httpx.Response(
            200,
            json=event_payload(),
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_event_odds(
            event_id="provider-event-1",
        )
    finally:
        client.close()

    parsed = parse_market_quotes(
        result,
        canonical_fixture_id="fixture-123",
        player_resolver=lambda name: (
            "player-haaland"
            if name == "Erling Haaland"
            else None
        ),
    )

    assert (
        parsed.canonical_fixture_id
        == "fixture-123"
    )

    assert parsed.unresolved_players == (
        "Unknown Player",
    )

    assert (
        parsed.skipped_unsupported_markets
        == 1
    )

    assert len(parsed.quotes) == 7

    assert {
        quote.market
        for quote in parsed.quotes
    } == {
        MarketKind.ANYTIME_GOAL,
        MarketKind.ASSIST,
        MarketKind.SHOTS,
        MarketKind.SHOTS_ON_TARGET,
    }

    assert all(
        quote.player_id
        == "player-haaland"
        for quote in parsed.quotes
    )

    assert all(
        quote.fixture_id
        == "fixture-123"
        for quote in parsed.quotes
    )


def test_parser_uses_market_last_update_as_quote_time(
    tmp_path,
):
    def handler(request):
        return httpx.Response(
            200,
            json=event_payload(),
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_event_odds(
            event_id="provider-event-1",
        )
    finally:
        client.close()

    parsed = parse_market_quotes(
        result,
        canonical_fixture_id="fixture-123",
        player_resolver=lambda name: (
            "player-haaland"
            if name == "Erling Haaland"
            else None
        ),
    )

    goal = next(
        quote
        for quote in parsed.quotes
        if quote.market
        == MarketKind.ANYTIME_GOAL
    )

    assert goal.side == MarketSide.YES

    assert goal.quoted_at == datetime(
        2026,
        9,
        12,
        12,
        1,
        tzinfo=timezone.utc,
    )


def test_historical_market_timestamp_after_snapshot_is_rejected(
    tmp_path,
):
    payload = event_payload()

    payload["bookmakers"][0][
        "markets"
    ][0][
        "last_update"
    ] = "2026-09-12T12:26:00Z"

    wrapper = {
        "timestamp": "2026-09-12T12:25:00Z",
        "data": payload,
    }

    def handler(request):
        return httpx.Response(
            200,
            json=wrapper,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = (
            adapter.get_historical_event_odds(
                event_id="provider-event-1",
                prediction_timestamp=AT,
            )
        )
    finally:
        client.close()

    with pytest.raises(
        TheOddsApiLeakageError
    ):
        parse_market_quotes(
            result,
            canonical_fixture_id="fixture-123",
            player_resolver=lambda name: (
                "player-haaland"
            ),
        )


def test_provider_event_id_mismatch_fails_closed(
    tmp_path,
):
    payload = event_payload()
    payload["id"] = "wrong-event"

    def handler(request):
        return httpx.Response(
            200,
            json=payload,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        with pytest.raises(
            TheOddsApiParseError
        ):
            adapter.get_event_odds(
                event_id="provider-event-1",
            )
    finally:
        client.close()


def test_http_429_has_specific_quota_error(
    tmp_path,
):
    def handler(request):
        return httpx.Response(
            429,
            json={
                "message": "quota exceeded"
            },
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        with pytest.raises(
            TheOddsApiQuotaExceededError
        ):
            adapter.get_event_odds(
                event_id="provider-event-1",
            )
    finally:
        client.close()


def test_parser_never_uses_player_name_as_identity(
    tmp_path,
):
    def handler(request):
        return httpx.Response(
            200,
            json=event_payload(),
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_event_odds(
            event_id="provider-event-1",
        )
    finally:
        client.close()

    parsed = parse_market_quotes(
        result,
        canonical_fixture_id="fixture-123",
        player_resolver=lambda name: None,
    )

    assert parsed.quotes == ()

    assert parsed.unresolved_players == (
        "Erling Haaland",
        "Unknown Player",
    )



def discovery_event(
    *,
    event_id="provider-event-1",
    home="Manchester City",
    away="Arsenal",
    kickoff="2026-09-13T15:00:00Z",
):
    return {
        "id": event_id,
        "sport_key": "soccer_epl",
        "sport_title": "EPL",
        "commence_time": kickoff,
        "home_team": home,
        "away_team": away,
    }


def test_current_event_discovery_uses_cache_and_raw_store(
    tmp_path,
):
    calls = []

    def handler(request):
        calls.append(request)

        return httpx.Response(
            200,
            json=[
                discovery_event()
            ],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        first = adapter.get_events()
        second = adapter.get_events()
    finally:
        client.close()

    assert len(calls) == 1
    assert not first.from_cache
    assert first.raw_snapshot is not None
    assert second.from_cache
    assert second.raw_snapshot is None

    assert len(first.events) == 1
    assert (
        first.events[0].provider_event_id
        == "provider-event-1"
    )


def test_event_discovery_sends_commence_filters(
    tmp_path,
):
    captured = {}

    def handler(request):
        captured["url"] = str(
            request.url
        )

        return httpx.Response(
            200,
            json=[],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    start = datetime(
        2026, 9, 13, 0, 0,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026, 9, 14, 0, 0,
        tzinfo=timezone.utc,
    )

    try:
        adapter.get_events(
            commence_time_from=start,
            commence_time_to=end,
        )
    finally:
        client.close()

    url = captured["url"]

    assert "commenceTimeFrom=" in url
    assert "commenceTimeTo=" in url
    assert "dateFormat=iso" in url


def test_historical_event_discovery_is_pit_safe(
    tmp_path,
):
    wrapper = {
        "timestamp": "2026-09-12T12:25:00Z",
        "previous_timestamp": "2026-09-12T12:20:00Z",
        "next_timestamp": "2026-09-12T12:30:00Z",
        "data": [
            discovery_event()
        ],
    }

    def handler(request):
        return httpx.Response(
            200,
            json=wrapper,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_historical_events(
            prediction_timestamp=AT,
        )
    finally:
        client.close()

    assert result.historical

    assert result.snapshot_timestamp == datetime(
        2026, 9, 12, 12, 25,
        tzinfo=timezone.utc,
    )

    assert result.snapshot_timestamp <= AT
    assert len(result.events) == 1


def test_historical_event_discovery_rejects_future_snapshot(
    tmp_path,
):
    wrapper = {
        "timestamp": "2026-09-12T12:31:00Z",
        "data": [
            discovery_event()
        ],
    }

    def handler(request):
        return httpx.Response(
            200,
            json=wrapper,
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        with pytest.raises(
            TheOddsApiLeakageError
        ):
            adapter.get_historical_events(
                prediction_timestamp=AT,
            )
    finally:
        client.close()


def test_event_identity_matches_canonical_fixture(
    tmp_path,
):
    from fpl_engine.data.providers.the_odds_api import (
        CanonicalFixtureCandidate,
        match_events_to_canonical_fixtures,
    )

    def handler(request):
        return httpx.Response(
            200,
            json=[
                discovery_event()
            ],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_events()
    finally:
        client.close()

    fixture = CanonicalFixtureCandidate(
        fixture_id="fixture-123",
        home_team_id="team-city",
        away_team_id="team-arsenal",
        kickoff=datetime(
            2026, 9, 13, 15, 0,
            tzinfo=timezone.utc,
        ),
    )

    teams = {
        "Manchester City": "team-city",
        "Arsenal": "team-arsenal",
    }

    audit = match_events_to_canonical_fixtures(
        result,
        team_resolver=teams.get,
        canonical_fixtures=(fixture,),
    )

    assert len(audit.matches) == 1

    assert (
        audit.matches[0].canonical_fixture_id
        == "fixture-123"
    )

    assert audit.unresolved_team_events == ()
    assert audit.unresolved_fixture_events == ()
    assert audit.ambiguous_fixture_events == ()


def test_event_identity_never_uses_unresolved_team_name_as_id(
    tmp_path,
):
    from fpl_engine.data.providers.the_odds_api import (
        CanonicalFixtureCandidate,
        match_events_to_canonical_fixtures,
    )

    def handler(request):
        return httpx.Response(
            200,
            json=[
                discovery_event()
            ],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_events()
    finally:
        client.close()

    fixture = CanonicalFixtureCandidate(
        fixture_id="fixture-123",
        home_team_id="Manchester City",
        away_team_id="Arsenal",
        kickoff=datetime(
            2026, 9, 13, 15, 0,
            tzinfo=timezone.utc,
        ),
    )

    audit = match_events_to_canonical_fixtures(
        result,
        team_resolver=lambda name: None,
        canonical_fixtures=(fixture,),
    )

    assert audit.matches == ()

    assert audit.unresolved_team_events == (
        "provider-event-1",
    )

    assert audit.unresolved_team_names == (
        "Arsenal",
        "Manchester City",
    )


def test_event_identity_fails_closed_outside_kickoff_tolerance(
    tmp_path,
):
    from fpl_engine.data.providers.the_odds_api import (
        CanonicalFixtureCandidate,
        match_events_to_canonical_fixtures,
    )

    def handler(request):
        return httpx.Response(
            200,
            json=[
                discovery_event()
            ],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_events()
    finally:
        client.close()

    fixture = CanonicalFixtureCandidate(
        fixture_id="fixture-123",
        home_team_id="team-city",
        away_team_id="team-arsenal",
        kickoff=datetime(
            2026, 9, 15, 15, 0,
            tzinfo=timezone.utc,
        ),
    )

    teams = {
        "Manchester City": "team-city",
        "Arsenal": "team-arsenal",
    }

    audit = match_events_to_canonical_fixtures(
        result,
        team_resolver=teams.get,
        canonical_fixtures=(fixture,),
        kickoff_tolerance=timedelta(
            hours=12
        ),
    )

    assert audit.matches == ()

    assert audit.unresolved_fixture_events == (
        "provider-event-1",
    )


def test_event_identity_audits_ambiguous_fixture_match(
    tmp_path,
):
    from fpl_engine.data.providers.the_odds_api import (
        CanonicalFixtureCandidate,
        match_events_to_canonical_fixtures,
    )

    def handler(request):
        return httpx.Response(
            200,
            json=[
                discovery_event()
            ],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    try:
        result = adapter.get_events()
    finally:
        client.close()

    fixtures = (
        CanonicalFixtureCandidate(
            fixture_id="fixture-A",
            home_team_id="team-city",
            away_team_id="team-arsenal",
            kickoff=datetime(
                2026, 9, 13, 14, 0,
                tzinfo=timezone.utc,
            ),
        ),
        CanonicalFixtureCandidate(
            fixture_id="fixture-B",
            home_team_id="team-city",
            away_team_id="team-arsenal",
            kickoff=datetime(
                2026, 9, 13, 16, 0,
                tzinfo=timezone.utc,
            ),
        ),
    )

    teams = {
        "Manchester City": "team-city",
        "Arsenal": "team-arsenal",
    }

    audit = match_events_to_canonical_fixtures(
        result,
        team_resolver=teams.get,
        canonical_fixtures=fixtures,
        kickoff_tolerance=timedelta(
            hours=2
        ),
    )

    assert audit.matches == ()

    assert audit.ambiguous_fixture_events == (
        "provider-event-1",
    )



def test_event_discovery_time_filters_use_second_precision(
    tmp_path,
):
    captured = {}

    def handler(request):
        captured["from"] = (
            request.url.params.get(
                "commenceTimeFrom"
            )
        )

        captured["to"] = (
            request.url.params.get(
                "commenceTimeTo"
            )
        )

        return httpx.Response(
            200,
            json=[],
        )

    adapter, client = make_adapter(
        tmp_path,
        handler,
    )

    start = datetime(
        2026,
        9,
        13,
        0,
        0,
        0,
        123456,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026,
        9,
        14,
        0,
        0,
        0,
        654321,
        tzinfo=timezone.utc,
    )

    try:
        adapter.get_events(
            commence_time_from=start,
            commence_time_to=end,
        )
    finally:
        client.close()

    assert (
        captured["from"]
        == "2026-09-13T00:00:00Z"
    )

    assert (
        captured["to"]
        == "2026-09-14T00:00:00Z"
    )
