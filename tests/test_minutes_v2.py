from __future__ import annotations

import math
from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from fpl_engine.features.minutes_dataset import (
    MinutesObservation,
)
from fpl_engine.models.minutes import (
    MinutesContext,
    MinutesModel,
)
from fpl_engine.models.minutes.v2 import (
    DEFAULT_MINUTES_V2_MODEL_CONFIG,
    HurdleTimeDecayMinutesModel,
    MinutesV2TimeConfig,
)


UTC = timezone.utc


def obs(
    fixture_id: str,
    kickoff: datetime,
    minutes: int,
    *,
    started: bool,
) -> MinutesObservation:

    return MinutesObservation(
        "player_1",
        fixture_id,
        kickoff,
        kickoff + timedelta(
            hours=3
        ),
        minutes,
        started,
    )


def context(
    fixture_id: str,
    timestamp: datetime,
) -> MinutesContext:

    return MinutesContext(
        "player_1",
        fixture_id,
        timestamp,
        availability_probability=1.0,
        availability_known_at=timestamp,
        availability_confidence=1.0,
    )


def test_calendar_decay_uses_actual_days():

    model = (
        HurdleTimeDecayMinutesModel()
    )

    prediction = datetime(
        2026, 9, 10, 12, 0,
        tzinfo=UTC,
    )

    rows = (
        obs(
            "f1",
            prediction
            - timedelta(days=30),
            90,
            started=True,
        ),
        obs(
            "f2",
            prediction
            - timedelta(days=1),
            90,
            started=True,
        ),
    )

    weights = (
        model._time_decay_weights(
            rows,
            prediction,
        )
    )

    assert weights[0] == pytest.approx(
        0.5,
        rel=1e-9,
    )

    assert weights[1] == pytest.approx(
        0.5 ** (1 / 30),
        rel=1e-9,
    )


def test_offseason_discount_applies_before_long_break():

    model = (
        HurdleTimeDecayMinutesModel(
            time_config=(
                MinutesV2TimeConfig(
                    half_life_days=30,
                    offseason_gap_days=60,
                    offseason_carryover=0.5,
                )
            )
        )
    )

    prediction = datetime(
        2026, 9, 10, 12, 0,
        tzinfo=UTC,
    )

    old = prediction - timedelta(
        days=110
    )

    recent = prediction - timedelta(
        days=10
    )

    rows = (
        obs(
            "old",
            old,
            90,
            started=True,
        ),
        obs(
            "recent",
            recent,
            90,
            started=True,
        ),
    )

    weights = (
        model._time_decay_weights(
            rows,
            prediction,
        )
    )

    expected_old = (
        0.5 ** (110 / 30)
    ) * 0.5

    expected_recent = (
        0.5 ** (10 / 30)
    )

    assert weights[0] == pytest.approx(
        expected_old,
        rel=1e-9,
    )

    assert weights[1] == pytest.approx(
        expected_recent,
        rel=1e-9,
    )


def test_conditional_starter_distribution_stays_v1():

    v1 = MinutesModel()

    v2 = (
        HurdleTimeDecayMinutesModel()
    )

    prediction = datetime(
        2026, 9, 10, 12, 0,
        tzinfo=UTC,
    )

    rows = []

    for index, minutes in enumerate(
        (
            90,
            84,
            76,
            90,
            68,
            90,
            80,
            90,
            72,
            90,
        )
    ):

        rows.append(
            obs(
                f"f{index}",
                prediction
                - timedelta(
                    days=30 - index,
                ),
                minutes,
                started=True,
            )
        )

    v1_weights = (
        v1._weights(
            len(rows)
        )
    )

    ctx = context(
        "target",
        prediction,
    )

    expected = (
        v1
        .starter_minutes_distribution(
            rows,
            v1_weights,
            ctx,
        )
    )

    actual = (
        v2
        .starter_minutes_distribution(
            rows,
            [1.0] * len(rows),
            ctx,
        )
    )

    assert actual == pytest.approx(
        expected
    )


def test_recent_three_starts_can_outweigh_old_dnps():

    prediction = datetime(
        2026, 9, 12, 12, 0,
        tzinfo=UTC,
    )

    dates_minutes = (
        (
            datetime(
                2026, 4, 19,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 4, 22,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 5, 4,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 5, 9,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 5, 13,
                tzinfo=UTC,
            ),
            0,
        ),
        (
            datetime(
                2026, 5, 19,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 5, 24,
                tzinfo=UTC,
            ),
            0,
        ),
        (
            datetime(
                2026, 8, 23,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 8, 28,
                tzinfo=UTC,
            ),
            90,
        ),
        (
            datetime(
                2026, 9, 5,
                tzinfo=UTC,
            ),
            90,
        ),
    )

    history = []

    for index, (
        kickoff,
        minutes,
    ) in enumerate(
        dates_minutes
    ):

        history.append(
            obs(
                f"history_{index}",
                kickoff,
                minutes,
                started=(
                    minutes > 0
                ),
            )
        )

    ctx = context(
        "target",
        prediction,
    )

    v1 = MinutesModel()

    v2 = (
        HurdleTimeDecayMinutesModel()
    )

    old = v1.predict(
        history,
        ctx,
    )

    new = v2.predict(
        history,
        ctx,
    )

    # Structural test only:
    # fresh evidence should recover faster after a long season break.
    assert (
        new.p_appearance
        > old.p_appearance
    )

    assert (
        new.p_start
        > old.p_start
    )

    # The challenger must remain probabilistically valid.
    assert (
        0.0
        <= new.p_start
        <= new.p_appearance
        <= 1.0
    )

    assert math.isclose(
        sum(
            new.minute_distribution
        ),
        1.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_default_v2_identity_is_explicit():

    assert (
        DEFAULT_MINUTES_V2_MODEL_CONFIG
        .model_version
        == "minutes_hurdle_v2"
    )

    assert (
        DEFAULT_MINUTES_V2_MODEL_CONFIG
        .history_matches
        == 20
    )

    assert (
        DEFAULT_MINUTES_V2_MODEL_CONFIG
        .appearance_prior_alpha
        == 1.0
    )

    assert (
        DEFAULT_MINUTES_V2_MODEL_CONFIG
        .appearance_prior_beta
        == 0.5
    )
