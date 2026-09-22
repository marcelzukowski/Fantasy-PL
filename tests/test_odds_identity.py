from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.data.odds_identity import (
    OddsIdentityConflictError,
    OddsPlayerAlias,
    OddsPlayerAliasRegistry,
    normalize_odds_player_alias,
    persist_fixture_identity_matches,
)
from fpl_engine.data.providers.the_odds_api import (
    PROVIDER,
    TheOddsApiEventIdentityAudit,
    TheOddsApiEventIdentityMatch,
)
from fpl_engine.data.schemas.entities import (
    MatchMethod,
    ReviewStatus,
)


AT = datetime(
    2026,
    9,
    11,
    12,
    0,
    tzinfo=timezone.utc,
)

SEASON_START = datetime(
    2026,
    8,
    1,
    0,
    0,
    tzinfo=timezone.utc,
)


class _Rows:
    def __init__(
        self,
        rows,
    ):
        self.rows = rows

    def fetchall(
        self,
    ):
        return list(
            self.rows
        )


class _FakeConnection:
    def __init__(
        self,
        database,
    ):
        self.database = database

    def execute(
        self,
        sql,
        params,
    ):
        provider = params[0]
        provider_id = params[1]

        rows = []

        for mapping in (
            self.database.mappings
        ):
            if (
                mapping.provider
                == provider
                and mapping.provider_id
                == provider_id
            ):
                rows.append(
                    (
                        mapping.fixture_id,
                        mapping.review_status.value,
                        mapping.effective_from,
                        mapping.effective_to,
                        mapping.provider_kickoff,
                    )
                )

        return _Rows(
            rows
        )


class _FakeDatabase:
    def __init__(
        self,
    ):
        self.mappings = []
        self.connection = (
            _FakeConnection(self)
        )

    def persist_fixture_mapping(
        self,
        mapping,
    ):
        self.mappings.append(
            mapping
        )


def audit(
    *,
    provider_event_id="event-1",
    fixture_id="fixture-1",
):
    return TheOddsApiEventIdentityAudit(
        matches=(
            TheOddsApiEventIdentityMatch(
                provider_event_id=(
                    provider_event_id
                ),
                canonical_fixture_id=(
                    fixture_id
                ),
                canonical_home_team_id="team-home",
                canonical_away_team_id="team-away",
                provider_commence_time=(
                    datetime(
                        2026,
                        9,
                        13,
                        15,
                        0,
                        tzinfo=timezone.utc,
                    )
                ),
            ),
        ),
        unresolved_team_events=(),
        unresolved_team_names=(),
        unresolved_fixture_events=(),
        ambiguous_fixture_events=(),
    )


def alias(
    *,
    name="Erling Haaland",
    player_id="player-haaland",
    start=SEASON_START,
    end=None,
    status=ReviewStatus.confirmed,
):
    return OddsPlayerAlias(
        provider_player_name=name,
        player_id=player_id,
        effective_from=start,
        effective_to=end,
        review_status=status,
        created_at=AT,
        updated_at=AT,
        source_record_id="manual-test",
        retrieved_at=AT,
    )


def test_fixture_mapping_is_persisted_as_confirmed_cross_provider_bridge():
    database = _FakeDatabase()

    result = persist_fixture_identity_matches(
        database,
        audit(),
        effective_from=SEASON_START,
        recorded_at=AT,
        retrieved_at=AT,
        source_record_id="snapshot-1",
    )

    assert result.created == (
        "event-1",
    )

    assert result.reused == ()

    assert len(
        database.mappings
    ) == 1

    mapping = (
        database.mappings[0]
    )

    assert mapping.provider == PROVIDER
    assert mapping.provider_id == "event-1"
    assert mapping.fixture_id == "fixture-1"

    assert (
        mapping.match_method
        == MatchMethod.cross_provider_bridge
    )

    assert (
        mapping.review_status
        == ReviewStatus.confirmed
    )

    assert (
        mapping.match_confidence
        == 1.0
    )


def test_fixture_mapping_is_idempotent():
    database = _FakeDatabase()

    first = persist_fixture_identity_matches(
        database,
        audit(),
        effective_from=SEASON_START,
        recorded_at=AT,
    )

    second = persist_fixture_identity_matches(
        database,
        audit(),
        effective_from=SEASON_START,
        recorded_at=(
            AT + timedelta(minutes=10)
        ),
    )

    assert first.created == (
        "event-1",
    )

    assert second.reused == (
        "event-1",
    )

    assert len(
        database.mappings
    ) == 1


def test_provider_event_cannot_be_silently_remapped():
    database = _FakeDatabase()

    persist_fixture_identity_matches(
        database,
        audit(
            fixture_id="fixture-A",
        ),
        effective_from=SEASON_START,
        recorded_at=AT,
    )

    with pytest.raises(
        OddsIdentityConflictError
    ):
        persist_fixture_identity_matches(
            database,
            audit(
                fixture_id="fixture-B",
            ),
            effective_from=SEASON_START,
            recorded_at=(
                AT
                + timedelta(minutes=1)
            ),
        )


def test_existing_nonconfirmed_fixture_mapping_fails_closed():
    database = _FakeDatabase()

    confirmed = persist_fixture_identity_matches(
        database,
        audit(),
        effective_from=SEASON_START,
        recorded_at=AT,
    )

    assert confirmed.created == (
        "event-1",
    )

    original = (
        database.mappings[0]
    )

    database.mappings = [
        original.model_copy(
            update={
                "review_status": (
                    ReviewStatus.flagged_for_review
                )
            }
        )
    ]

    with pytest.raises(
        OddsIdentityConflictError
    ):
        persist_fixture_identity_matches(
            database,
            audit(),
            effective_from=SEASON_START,
            recorded_at=AT,
        )


def test_alias_normalization_is_conservative_and_case_insensitive():
    assert (
        normalize_odds_player_alias(
            "  Erling   HAALAND "
        )
        == "erling haaland"
    )


def test_confirmed_alias_persists_and_resolves(
    tmp_path,
):
    path = (
        tmp_path
        / "odds_player_aliases.json"
    )

    registry = (
        OddsPlayerAliasRegistry(
            path
        )
    )

    created = registry.add(
        alias()
    )

    assert created

    assert path.exists()

    assert registry.resolve(
        "erling haaland",
        at=AT,
    ) == "player-haaland"

    assert registry.resolve(
        "  ERLING   HAALAND ",
        at=AT,
    ) == "player-haaland"


def test_alias_registry_is_idempotent(
    tmp_path,
):
    registry = (
        OddsPlayerAliasRegistry(
            tmp_path
            / "aliases.json"
        )
    )

    record = alias()

    assert registry.add(
        record
    )

    assert not registry.add(
        record
    )

    assert len(
        registry.records()
    ) == 1


def test_unresolved_or_review_alias_never_resolves(
    tmp_path,
):
    registry = (
        OddsPlayerAliasRegistry(
            tmp_path
            / "aliases.json"
        )
    )

    registry.add(
        alias(
            player_id=None,
            status=ReviewStatus.unresolved,
        )
    )

    assert registry.resolve(
        "Erling Haaland",
        at=AT,
    ) is None


def test_overlapping_confirmed_alias_to_different_players_fails_closed(
    tmp_path,
):
    registry = (
        OddsPlayerAliasRegistry(
            tmp_path
            / "aliases.json"
        )
    )

    registry.add(
        alias(
            player_id="player-A",
        )
    )

    with pytest.raises(
        OddsIdentityConflictError
    ):
        registry.add(
            alias(
                player_id="player-B",
                start=(
                    SEASON_START
                    + timedelta(days=10)
                ),
            )
        )


def test_non_overlapping_alias_can_change_canonical_player(
    tmp_path,
):
    registry = (
        OddsPlayerAliasRegistry(
            tmp_path
            / "aliases.json"
        )
    )

    boundary = datetime(
        2027,
        6,
        1,
        tzinfo=timezone.utc,
    )

    registry.add(
        alias(
            player_id="player-A",
            end=(
                boundary
                - timedelta(seconds=1)
            ),
        )
    )

    registry.add(
        alias(
            player_id="player-B",
            start=boundary,
        )
    )

    assert registry.resolve(
        "Erling Haaland",
        at=(
            boundary
            - timedelta(days=1)
        ),
    ) == "player-A"

    assert registry.resolve(
        "Erling Haaland",
        at=boundary,
    ) == "player-B"


def test_registry_round_trip_and_resolver_closure(
    tmp_path,
):
    path = (
        tmp_path
        / "aliases.json"
    )

    first = OddsPlayerAliasRegistry(
        path
    )

    first.add(
        alias()
    )

    second = OddsPlayerAliasRegistry(
        path
    )

    records = second.records()

    assert len(records) == 1

    assert (
        records[0].player_id
        == "player-haaland"
    )

    resolver = second.resolver(
        at=AT
    )

    assert resolver(
        "Erling Haaland"
    ) == "player-haaland"

    assert resolver(
        "Unknown Player"
    ) is None
