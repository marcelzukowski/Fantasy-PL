from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

from fpl_engine.current import (
    _current_history,
)


NOW = datetime(
    2026,
    9,
    12,
    10,
    0,
    tzinfo=timezone.utc,
)

KICKOFF = (
    NOW
    - timedelta(days=7)
)


def fixture():

    return SimpleNamespace(
        fixture_id="fix_test",
        kickoff=KICKOFF,
        known_at=KICKOFF,
        target_gameweek=1,
        home_provider_team_id="1",
        away_provider_team_id="2",
        home_team_id="team_home",
        away_team_id="team_away",
        provider_payload={
            "team_h_score": 1,
            "team_a_score": 0,
        },
    )


def player(
    provider_id,
    provider_team_id,
    team_id,
):

    return SimpleNamespace(
        provider_id=str(
            provider_id
        ),
        provider_team_id=str(
            provider_team_id
        ),
        player_id=(
            f"ply_{provider_id}"
        ),
        team_id=team_id,
        position="MID",
    )


def record(elements):

    return SimpleNamespace(
        entity="event_live_1",
        payload={
            "elements": elements,
        },
        known_at=NOW,
    )


def test_current_history_aggregates_team_xg():

    rows = (
        player(
            101,
            1,
            "team_home",
        ),
        player(
            102,
            1,
            "team_home",
        ),
        player(
            201,
            2,
            "team_away",
        ),
    )

    live = (
        record(
            [
                {
                    "id": 101,
                    "stats": {
                        "expected_goals": "0.40",
                    },
                },
                {
                    "id": 102,
                    "stats": {
                        "expected_goals": "0.60",
                    },
                },
                {
                    "id": 201,
                    "stats": {
                        "expected_goals": "0.75",
                    },
                },
            ]
        ),
    )

    matches, _, _, warnings = (
        _current_history(
            [fixture()],
            list(rows),
            live,
            NOW,
        )
    )

    assert len(matches) == 1

    match = matches[0]

    assert abs(
        match.home_xg - 1.0
    ) < 1e-9

    assert abs(
        match.away_xg - 0.75
    ) < 1e-9

    assert not any(
        "expected_goals is incomplete"
        in warning
        for warning in warnings
    )


def test_current_history_does_not_mix_xg_and_goals():

    rows = (
        player(
            101,
            1,
            "team_home",
        ),
        player(
            201,
            2,
            "team_away",
        ),
    )

    live = (
        record(
            [
                {
                    "id": 101,
                    "stats": {
                        "expected_goals": "0.90",
                    },
                },
                {
                    "id": 201,
                    "stats": {},
                },
            ]
        ),
    )

    matches, _, _, warnings = (
        _current_history(
            [fixture()],
            list(rows),
            live,
            NOW,
        )
    )

    match = matches[0]

    assert match.home_xg is None
    assert match.away_xg is None

    assert any(
        "expected_goals is incomplete"
        in warning
        for warning in warnings
    )


def test_current_history_preserves_goal_fallback():

    rows = (
        player(
            101,
            1,
            "team_home",
        ),
        player(
            201,
            2,
            "team_away",
        ),
    )

    live = (
        record(
            [
                {
                    "id": 101,
                    "stats": {},
                },
                {
                    "id": 201,
                    "stats": {},
                },
            ]
        ),
    )

    matches, _, _, _ = (
        _current_history(
            [fixture()],
            list(rows),
            live,
            NOW,
        )
    )

    match = matches[0]

    assert match.home_goals == 1.0
    assert match.away_goals == 0.0
    assert match.home_xg is None
    assert match.away_xg is None
