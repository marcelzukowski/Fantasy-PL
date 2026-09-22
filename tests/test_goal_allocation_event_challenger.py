from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from fpl_engine.models.events.model import (
    EventModels,
)

from fpl_engine.models.events.goal_allocation_v2 import (
    GoalAllocationEventModels,
)


AT = datetime(
    2026,
    9,
    12,
    10,
    0,
    tzinfo=timezone.utc,
)


def _item(
    *,
    player_id="p1",
    npxg=0.35,
    minutes=90.0,
):

    return SimpleNamespace(
        player_id=player_id,
        team_id="team1",
        fixture_id="fixture1",
        prediction_timestamp=AT,
        position="FWD",
        opponent_defence_strength=1.0,
        tactical_context=None,
        minutes=SimpleNamespace(
            p_appearance=1.0,
            p_start=1.0,
            expected_minutes=minutes,
            minute_distribution=(
                0.0,
                1.0,
            ),
            starter_minutes_distribution=(
                0.0,
                1.0,
            ),
            bench_minutes_distribution=(
                1.0,
                0.0,
            ),
            minutes_uncertainty=0.1,
        ),
        talent=SimpleNamespace(
            talent_npxg_per90=npxg,
            talent_xa_per90=0.10,
            talent_shots_per90=2.5,
            talent_shots_on_target_per90=None,
            set_piece_attacking_component=None,
            defensive_contribution_rate=None,
            player_talent_uncertainty=0.1,
        ),
    )


def test_missing_proxy_is_exact_legacy_rate():

    item = _item()

    legacy = EventModels._rate(
        item
    )

    challenger = (
        GoalAllocationEventModels({})
        ._rate(item)
    )

    assert challenger == legacy


def test_proxy_changes_only_internal_allocation_weight():

    item = _item(
        npxg=0.35,
        minutes=90.0,
    )

    legacy = EventModels._rate(
        item
    )

    challenger = (
        GoalAllocationEventModels({
            "p1": 0.55,
        })
        ._rate(item)
    )

    assert (
        challenger.fixture_npxg_per90
        == pytest.approx(
            legacy.fixture_npxg_per90
        )
    )

    assert (
        legacy.raw_expected_npxg
        == pytest.approx(0.35)
    )

    assert (
        challenger.raw_expected_npxg
        == pytest.approx(0.55)
    )


def test_proxy_respects_fixture_context():

    item = _item(
        npxg=0.35,
        minutes=45.0,
    )

    item.opponent_defence_strength = 2.0

    challenger = (
        GoalAllocationEventModels({
            "p1": 0.80,
        })
        ._rate(item)
    )

    assert (
        challenger.raw_expected_npxg
        == pytest.approx(
            0.20
        )
    )


def test_bad_proxy_is_rejected():

    with pytest.raises(
        ValueError
    ):

        GoalAllocationEventModels({
            "p1": -0.1,
        })


def test_proxy_mapping_is_immutable():

    model = (
        GoalAllocationEventModels({
            "p1": 0.55,
        })
    )

    with pytest.raises(
        TypeError
    ):

        model.proxy_by_player[
            "p1"
        ] = 0.20


@dataclass(frozen=True)
class DummyRate:
    player_id: str
    fixture_npxg_per90: float
    raw_expected_npxg: float


@dataclass(frozen=True)
class DummyPlayer:
    rates: DummyRate
    model_version: str
    feature_version: str


@dataclass(frozen=True)
class DummyTeam:
    players: tuple
    model_version: str


def test_public_team_output_restores_npxg_contract(
    monkeypatch,
):

    def fake_base_rate(item):

        return DummyRate(
            player_id=item.player_id,
            fixture_npxg_per90=0.35,
            raw_expected_npxg=0.35,
        )


    def fake_predict_team(
        self,
        players,
        *args,
        **kwargs,
    ):

        players = tuple(
            players
        )

        return DummyTeam(
            players=tuple(
                DummyPlayer(
                    rates=DummyRate(
                        player_id=(
                            item.player_id
                        ),
                        fixture_npxg_per90=(
                            0.55
                        ),
                        raw_expected_npxg=(
                            0.55
                        ),
                    ),
                    model_version=(
                        "event_models_v1"
                    ),
                    feature_version=(
                        "event_features_v1"
                    ),
                )
                for item in players
            ),
            model_version=(
                "event_models_v1"
            ),
        )


    monkeypatch.setattr(
        EventModels,
        "_rate",
        staticmethod(
            fake_base_rate
        ),
    )

    monkeypatch.setattr(
        EventModels,
        "predict_team",
        fake_predict_team,
    )


    model = (
        GoalAllocationEventModels({
            "p1": 0.55,
        })
    )


    result = model.predict_team(
        [
            SimpleNamespace(
                player_id="p1"
            )
        ]
    )


    player = result.players[0]

    assert (
        player.rates
        .fixture_npxg_per90
        == pytest.approx(0.35)
    )

    assert (
        player.rates
        .raw_expected_npxg
        == pytest.approx(0.35)
    )

    assert (
        player.model_version
        == model.MODEL_VERSION
    )

    assert (
        player.feature_version
        == model.FEATURE_VERSION
    )

    assert (
        result.model_version
        == model.MODEL_VERSION
    )
