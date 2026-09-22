"""Development-only Event challenger using historical goal-allocation proxy.

Frozen EventModels V1 remains untouched.

The proxy is historical total-xG-derived evidence and is used ONLY as a
relative weight when EventModels divides the non-penalty team goal envelope.

It does not replace:
- talent_npxg_per90,
- fixture_npxg_per90,
- penalty allocation,
- Team Strength expected goals.

Players without historical proxy evidence retain exact legacy behaviour.
"""

from __future__ import annotations

from dataclasses import replace
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.models.events.model import (
    EventModels,
    PlayerFixtureInput,
)
from fpl_engine.models.player_talent.goal_allocation import (
    fixture_goal_allocation_weight,
)


class GoalAllocationEventModels(EventModels):

    MODEL_VERSION = (
        "event_models_goal_allocation_proxy_v1"
    )

    FEATURE_VERSION = (
        "event_features_goal_allocation_proxy_v1"
    )

    def __init__(
        self,
        proxy_by_player: Mapping[str, float],
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            **kwargs,
        )

        clean = {}

        for player_id, raw_value in (
            proxy_by_player.items()
        ):

            if (
                not isinstance(
                    player_id,
                    str,
                )
                or not player_id
            ):
                raise ValueError(
                    "proxy player IDs must be "
                    "canonical non-empty strings"
                )

            value = float(
                raw_value
            )

            if (
                not math.isfinite(value)
                or value < 0.0
            ):
                raise ValueError(
                    "goal allocation proxy must "
                    "be finite and non-negative"
                )

            clean[player_id] = value

        self.proxy_by_player = (
            MappingProxyType(
                clean
            )
        )


    def _rate(
        self,
        item,
    ):
        #
        # Produce the frozen V1 rate first.
        #
        legacy = EventModels._rate(
            item
        )

        proxy = self.proxy_by_player.get(
            item.player_id
        )

        #
        # No historical evidence:
        # exact V1 behaviour.
        #
        if proxy is None:
            return legacy

        role = item.tactical_context

        goal_multiplier = (
            role.current_role_multiplier_goal
            if role is not None
            else 1.0
        )

        allocation_weight = (
            fixture_goal_allocation_weight(
                goal_allocation_proxy_per90=(
                    proxy
                ),
                legacy_raw_expected_npxg=(
                    legacy.raw_expected_npxg
                ),
                expected_minutes=(
                    item.minutes.expected_minutes
                ),
                opponent_defence_strength=(
                    item.opponent_defence_strength
                ),
                goal_multiplier=(
                    goal_multiplier
                ),
            )
        )

        #
        # IMPORTANT:
        #
        # raw_expected_npxg is temporarily used
        # inside EventModels as the allocation
        # weight.
        #
        # predict_team() restores the genuine
        # legacy npxG field before returning the
        # public result.
        #
        return replace(
            legacy,
            raw_expected_npxg=(
                allocation_weight
            ),
        )


    def predict_team(
        self,
        players: Iterable[
            PlayerFixtureInput
        ],
        *args,
        **kwargs,
    ):
        inputs = tuple(
            players
        )

        #
        # Internally EventModels now sees the
        # proxy allocation weight.
        #
        result = super().predict_team(
            inputs,
            *args,
            **kwargs,
        )

        #
        # Restore truthful npxG fields in the
        # returned public contract.
        #
        # GoalEvents/BPS were already computed
        # using the challenger allocation.
        #
        legacy_rates = {
            item.player_id:
                EventModels._rate(item)
            for item in inputs
        }

        revised_players = []

        for player in result.players:

            player_id = (
                player.rates.player_id
            )

            legacy = legacy_rates.get(
                player_id
            )

            rates = player.rates

            if legacy is not None:

                rates = replace(
                    rates,
                    fixture_npxg_per90=(
                        legacy
                        .fixture_npxg_per90
                    ),
                    raw_expected_npxg=(
                        legacy
                        .raw_expected_npxg
                    ),
                )

            revised_players.append(
                replace(
                    player,
                    rates=rates,
                    model_version=(
                        self.MODEL_VERSION
                    ),
                    feature_version=(
                        self.FEATURE_VERSION
                    ),
                )
            )

        return replace(
            result,
            players=tuple(
                revised_players
            ),
            model_version=(
                self.MODEL_VERSION
            ),
        )


    def predict_fixture(
        self,
        *args,
        **kwargs,
    ):
        result = super().predict_fixture(
            *args,
            **kwargs,
        )

        return replace(
            result,
            model_version=(
                self.MODEL_VERSION
            ),
        )
