from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptaincyPairValue:
    captain_id: str
    vice_id: str
    captain_ev: float
    vice_ev: float
    captain_p_appearance: float
    vice_p_appearance: float
    captain_bonus: float


def effective_captain_bonus(
    *,
    captain_ev: float,
    vice_ev: float,
    captain_p_appearance: float,
) -> float:
    """
    Additional expected FPL points from captaincy.

    The captain's ordinary EV is already counted once in the XI.
    Captaincy adds one extra copy.

    If the captain does not appear, vice-captain receives the
    captain multiplier. We use marginal-independence approximation.

    expected bonus =
        unconditional captain EV
        + P(captain DNP) * unconditional vice EV
    """

    p_c = max(
        0.0,
        min(
            1.0,
            float(captain_p_appearance),
        ),
    )

    return (
        float(captain_ev)
        + (1.0 - p_c)
        * float(vice_ev)
    )


def best_captaincy_pair(
    *,
    player_ids,
    expected_points,
    p_appearance,
    positions,
    allowed_positions=("MID", "FWD"),
) -> CaptaincyPairValue:

    eligible = [
        pid
        for pid in player_ids
        if positions[pid]
        in allowed_positions
    ]

    if len(eligible) < 2:
        raise ValueError(
            "Need at least two eligible "
            "captaincy players"
        )

    best = None

    for captain_id in eligible:

        for vice_id in eligible:

            if captain_id == vice_id:
                continue

            value = effective_captain_bonus(
                captain_ev=(
                    expected_points[
                        captain_id
                    ]
                ),
                vice_ev=(
                    expected_points[
                        vice_id
                    ]
                ),
                captain_p_appearance=(
                    p_appearance[
                        captain_id
                    ]
                ),
            )

            candidate = (
                value,
                expected_points[
                    captain_id
                ],
                expected_points[
                    vice_id
                ],
                captain_id,
                vice_id,
            )

            if (
                best is None
                or candidate > best[0]
            ):
                best = (
                    candidate,
                    CaptaincyPairValue(
                        captain_id=(
                            captain_id
                        ),
                        vice_id=vice_id,
                        captain_ev=float(
                            expected_points[
                                captain_id
                            ]
                        ),
                        vice_ev=float(
                            expected_points[
                                vice_id
                            ]
                        ),
                        captain_p_appearance=float(
                            p_appearance[
                                captain_id
                            ]
                        ),
                        vice_p_appearance=float(
                            p_appearance[
                                vice_id
                            ]
                        ),
                        captain_bonus=float(
                            value
                        ),
                    ),
                )

    return best[1]
