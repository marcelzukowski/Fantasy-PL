from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Any


class AvailabilityError(ValueError):
    """Availability artifacts are incomplete or inconsistent."""


@dataclass(frozen=True)
class GameweekAvailability:
    player_id: str
    gameweek: int
    fixture_ids: tuple[str, ...]
    expected_minutes: float
    p_appearance: float
    p_start: float
    p_zero_minutes: float


def _probability(
    value: object,
    label: str,
) -> float:

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AvailabilityError(
            f"{label} must be numeric"
        ) from exc

    if (
        not math.isfinite(result)
        or not 0.0 <= result <= 1.0
    ):
        raise AvailabilityError(
            f"{label} must be in [0, 1]"
        )

    return result


def _number(
    value: object,
    label: str,
) -> float:

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AvailabilityError(
            f"{label} must be numeric"
        ) from exc

    if (
        not math.isfinite(result)
        or result < 0.0
    ):
        raise AvailabilityError(
            f"{label} must be finite "
            "and non-negative"
        )

    return result


def build_gameweek_availability(
    projection_rows: Iterable[
        Mapping[str, Any]
    ],
    minute_rows: Iterable[
        Mapping[str, Any]
    ],
    *,
    strict: bool = True,
) -> dict[
    tuple[str, int],
    GameweekAvailability,
]:

    minutes_by_fixture = {}

    for row in minute_rows:

        player_id = str(
            row["player_id"]
        )

        fixture_id = str(
            row["fixture_id"]
        )

        key = (
            player_id,
            fixture_id,
        )

        if key in minutes_by_fixture:
            raise AvailabilityError(
                "duplicate minute projection "
                f"for {player_id} / "
                f"{fixture_id}"
            )

        minutes_by_fixture[
            key
        ] = row

    output = {}

    for projection in projection_rows:

        player_id = str(
            projection["player_id"]
        )

        for gw_row in projection.get(
            "gameweeks",
            (),
        ):

            raw_gameweek = gw_row.get(
                "target_gameweek",
                gw_row.get(
                    "gameweek"
                ),
            )

            if raw_gameweek is None:
                raise AvailabilityError(
                    "gameweek projection "
                    "has no gameweek"
                )

            gameweek = int(
                raw_gameweek
            )

            fixture_ids = tuple(
                str(value)
                for value
                in gw_row.get(
                    "fixture_ids",
                    (),
                )
            )

            rows = []

            for fixture_id in fixture_ids:

                minute_row = (
                    minutes_by_fixture.get(
                        (
                            player_id,
                            fixture_id,
                        )
                    )
                )

                if minute_row is None:

                    if strict:
                        raise AvailabilityError(
                            "missing minute "
                            "projection for "
                            f"{player_id} / "
                            f"{fixture_id}"
                        )

                    continue

                rows.append(
                    minute_row
                )

            if not rows:

                result = (
                    GameweekAvailability(
                        player_id=player_id,
                        gameweek=gameweek,
                        fixture_ids=(
                            fixture_ids
                        ),
                        expected_minutes=0.0,
                        p_appearance=0.0,
                        p_start=0.0,
                        p_zero_minutes=1.0,
                    )
                )

            else:

                expected_minutes = sum(
                    _number(
                        row[
                            "expected_minutes"
                        ],
                        "expected_minutes",
                    )
                    for row in rows
                )

                fixture_appearance = [
                    _probability(
                        row[
                            "p_appearance"
                        ],
                        "p_appearance",
                    )
                    for row in rows
                ]

                fixture_start = [
                    _probability(
                        row[
                            "p_start"
                        ],
                        "p_start",
                    )
                    for row in rows
                ]

                #
                # For DGW:
                #
                # P(appearance in >= 1 match)
                #
                # V1 assumes fixture-level
                # independence elsewhere too.
                #

                p_zero_minutes = (
                    math.prod(
                        1.0 - value
                        for value
                        in fixture_appearance
                    )
                )

                p_appearance = (
                    1.0
                    - p_zero_minutes
                )

                p_start = (
                    1.0
                    - math.prod(
                        1.0 - value
                        for value
                        in fixture_start
                    )
                )

                if (
                    p_start
                    > p_appearance
                    + 1e-9
                ):
                    raise AvailabilityError(
                        "p_start exceeds "
                        "p_appearance for "
                        f"{player_id} GW"
                        f"{gameweek}"
                    )

                result = (
                    GameweekAvailability(
                        player_id=player_id,
                        gameweek=gameweek,
                        fixture_ids=(
                            fixture_ids
                        ),
                        expected_minutes=(
                            expected_minutes
                        ),
                        p_appearance=(
                            p_appearance
                        ),
                        p_start=p_start,
                        p_zero_minutes=(
                            p_zero_minutes
                        ),
                    )
                )

            key = (
                player_id,
                gameweek,
            )

            if key in output:
                raise AvailabilityError(
                    "duplicate availability "
                    f"for {player_id} "
                    f"GW{gameweek}"
                )

            output[
                key
            ] = result

    return output
