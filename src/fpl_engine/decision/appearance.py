from __future__ import annotations

import math

from collections.abc import (
    Iterable,
    Mapping,
)

from .horizon import DecisionError


AppearanceByPlayerGameweek = dict[
    str,
    dict[int, float],
]


def build_gameweek_appearance(
    *,
    projection_rows: Iterable[Mapping],
    minutes_rows: Iterable[Mapping],
) -> AppearanceByPlayerGameweek:
    """
    Build decision-layer appearance probabilities.

    Source contract
    ---------------
    player_projections.json:
        player_id
        gameweeks[].target_gameweek
        gameweeks[].fixture_ids

    minutes.json:
        player_id
        fixture_id
        p_appearance

    For a single fixture:
        P(appearance in GW) = p_appearance

    For a double/triple gameweek:
        P(appearance at least once)
        = 1 - product(1 - p_fixture)

    No missing probability is guessed.
    """

    minute_index: dict[
        tuple[str, str],
        float,
    ] = {}


    for row in minutes_rows:

        try:
            player_id = str(
                row["player_id"]
            )

            fixture_id = str(
                row["fixture_id"]
            )

            probability = float(
                row["p_appearance"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:

            raise DecisionError(
                "invalid minutes appearance row"
            ) from exc


        if not math.isfinite(
            probability
        ):

            raise DecisionError(
                "non-finite p_appearance for "
                f"{player_id} / {fixture_id}"
            )


        if not (
            0.0
            <= probability
            <= 1.0
        ):

            raise DecisionError(
                "p_appearance outside [0, 1] "
                f"for {player_id} / "
                f"{fixture_id}: "
                f"{probability}"
            )


        key = (
            player_id,
            fixture_id,
        )


        if key in minute_index:

            raise DecisionError(
                "duplicate minutes appearance "
                f"row for {player_id} / "
                f"{fixture_id}"
            )


        minute_index[
            key
        ] = probability


    output: AppearanceByPlayerGameweek = {}


    for row in projection_rows:

        try:
            player_id = str(
                row["player_id"]
            )

        except (
            KeyError,
            TypeError,
        ) as exc:

            raise DecisionError(
                "projection row lacks "
                "player_id"
            ) from exc


        raw_gameweeks = row.get(
            "gameweeks"
        )


        if not isinstance(
            raw_gameweeks,
            list,
        ):

            raise DecisionError(
                "projection row must contain "
                f"gameweeks list: {player_id}"
            )


        player_output: dict[
            int,
            float,
        ] = {}


        for gameweek in raw_gameweeks:

            if not isinstance(
                gameweek,
                Mapping,
            ):

                raise DecisionError(
                    "invalid gameweek projection "
                    f"for {player_id}"
                )


            try:
                target_gameweek = int(
                    gameweek[
                        "target_gameweek"
                    ]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ) as exc:

                raise DecisionError(
                    "gameweek projection lacks "
                    "target_gameweek for "
                    f"{player_id}"
                ) from exc


            if (
                target_gameweek
                in player_output
            ):

                raise DecisionError(
                    "duplicate target gameweek "
                    f"GW{target_gameweek} for "
                    f"{player_id}"
                )


            fixture_ids = gameweek.get(
                "fixture_ids"
            )


            if not isinstance(
                fixture_ids,
                list,
            ):

                raise DecisionError(
                    "gameweek projection lacks "
                    "fixture_ids list for "
                    f"{player_id} "
                    f"GW{target_gameweek}"
                )


            normalized_fixture_ids = tuple(
                str(fixture_id)
                for fixture_id
                in fixture_ids
            )


            if (
                len(
                    normalized_fixture_ids
                )
                != len(
                    set(
                        normalized_fixture_ids
                    )
                )
            ):

                raise DecisionError(
                    "duplicate fixture id for "
                    f"{player_id} "
                    f"GW{target_gameweek}"
                )


            #
            # Blank gameweek:
            # no fixture means no possible
            # FPL appearance.
            #
            if not normalized_fixture_ids:

                player_output[
                    target_gameweek
                ] = 0.0

                continue


            fixture_probabilities = []


            for fixture_id in (
                normalized_fixture_ids
            ):

                key = (
                    player_id,
                    fixture_id,
                )


                if key not in minute_index:

                    raise DecisionError(
                        "missing minutes "
                        "p_appearance for "
                        f"{player_id} / "
                        f"{fixture_id} / "
                        f"GW{target_gameweek}"
                    )


                fixture_probabilities.append(
                    minute_index[
                        key
                    ]
                )


            probability_dnp_all = (
                math.prod(
                    1.0 - probability
                    for probability
                    in fixture_probabilities
                )
            )


            probability_appears = (
                1.0
                - probability_dnp_all
            )


            #
            # Numerical guard only.
            #
            player_output[
                target_gameweek
            ] = max(
                0.0,
                min(
                    1.0,
                    probability_appears,
                ),
            )


        output[
            player_id
        ] = player_output


    return output


def gameweek_appearance(
    appearance_by_player_gameweek:
        Mapping[
            str,
            Mapping[int, float],
        ],
    *,
    player_id: str,
    gameweek: int,
) -> float:
    """
    Strict accessor for optimizer code.

    Missing captaincy availability is an
    input error, not a probability of 1.0.
    """

    player_id = str(
        player_id
    )

    gameweek = int(
        gameweek
    )


    player_rows = (
        appearance_by_player_gameweek.get(
            player_id
        )
    )


    if player_rows is None:

        raise DecisionError(
            "missing appearance data for "
            f"player {player_id}"
        )


    if gameweek not in player_rows:

        raise DecisionError(
            "missing appearance data for "
            f"player {player_id} "
            f"GW{gameweek}"
        )


    probability = float(
        player_rows[
            gameweek
        ]
    )


    if not math.isfinite(
        probability
    ) or not (
        0.0
        <= probability
        <= 1.0
    ):

        raise DecisionError(
            "invalid decision appearance "
            f"probability for "
            f"{player_id} "
            f"GW{gameweek}: "
            f"{probability}"
        )


    return probability
