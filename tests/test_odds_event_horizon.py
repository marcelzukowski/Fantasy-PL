from datetime import (
    datetime,
    timezone,
)

from scripts.scan_odds_event_horizon import (
    best_event_match,
    fixture_key,
    normalize_team,
)


def test_common_team_aliases():
    assert normalize_team(
        "Man Utd"
    ) == normalize_team(
        "Manchester United"
    )

    assert normalize_team(
        "Wolves"
    ) == normalize_team(
        "Wolverhampton Wanderers"
    )

    assert normalize_team(
        "Nott'm Forest"
    ) == normalize_team(
        "Nottingham Forest"
    )


def test_fixture_key_ignores_order():
    assert fixture_key(
        "Chelsea",
        "Fulham",
    ) == fixture_key(
        "Fulham",
        "Chelsea",
    )


def test_event_match_by_teams_and_time():
    event = {
        "id": "abc",
        "home_team": "Manchester United",
        "away_team": "Chelsea",
        "commence_time": (
            "2026-09-20T15:30:00Z"
        ),
    }

    result, delta = (
        best_event_match(
            home="Man Utd",
            away="Chelsea",
            kickoff=datetime(
                2026,
                9,
                20,
                15,
                30,
                tzinfo=timezone.utc,
            ),
            provider_events=[
                event
            ],
        )
    )

    assert result["id"] == "abc"
    assert delta == 0.0


def test_event_match_rejects_wrong_fixture():
    event = {
        "id": "abc",
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "commence_time": (
            "2026-09-20T15:30:00Z"
        ),
    }

    result, delta = (
        best_event_match(
            home="Arsenal",
            away="Chelsea",
            kickoff=datetime(
                2026,
                9,
                20,
                15,
                30,
                tzinfo=timezone.utc,
            ),
            provider_events=[
                event
            ],
        )
    )

    assert result is None
    assert delta is None
