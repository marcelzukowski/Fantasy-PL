from pathlib import Path


path = Path(
    "src/fpl_engine/models/events/model.py"
)

text = path.read_text(
    encoding="utf-8-sig"
)


field = (
    "    goal_allocation_proxy_per90: "
    "float | None = None\n"
)


if "goal_allocation_proxy_per90" not in text:

    anchor = (
        "    signals: tuple[EventFeatureSignal, ...] = ()\n"
    )

    if anchor not in text:
        raise RuntimeError(
            "PlayerFixtureInput signals anchor not found"
        )

    text = text.replace(
        anchor,
        anchor + field,
        1,
    )


old_weights = (
    "        goal_weights = "
    "[rate.raw_expected_npxg for rate in rates]\n"
)

new_weights = (
    "        goal_weights = [\n"
    "            self._goal_allocation_weight(item, rate)\n"
    "            for item, rate in zip(inputs, rates)\n"
    "        ]\n"
)


if old_weights in text:

    text = text.replace(
        old_weights,
        new_weights,
        1,
    )

elif (
    "self._goal_allocation_weight(item, rate)"
    not in text
):

    raise RuntimeError(
        "goal_weights anchor not found"
    )


helper_anchor = (
    "    @staticmethod\n"
    "    def _penalty_weight(item):\n"
)


helper = '''    @staticmethod
    def _goal_allocation_weight(item, rate) -> float:
        """Weight used only to divide the non-penalty team goal envelope.

        Legacy behaviour is byte-for-byte equivalent when no proxy is
        supplied: raw_expected_npxg remains the allocation weight.

        A supplied proxy is a relative total-xG-derived signal. It does not
        replace fixture_npxg_per90 or raw_expected_npxg and therefore does not
        pretend that total historical xG is non-penalty xG.
        """
        proxy = item.goal_allocation_proxy_per90

        if proxy is None:
            return rate.raw_expected_npxg

        if (
            not math.isfinite(proxy)
            or proxy < 0.0
        ):
            raise ValueError(
                "goal_allocation_proxy_per90 must be "
                "finite and non-negative"
            )

        defence_factor = (
            1 / item.opponent_defence_strength
        )

        role = item.tactical_context

        goal_multiplier = (
            role.current_role_multiplier_goal
            if role
            else 1.0
        )

        fixture_proxy = max(
            0.0,
            proxy
            * defence_factor
            * goal_multiplier,
        )

        exposure = (
            item.minutes.expected_minutes
            / 90.0
        )

        return fixture_proxy * exposure

'''


if (
    "def _goal_allocation_weight("
    not in text
):

    if helper_anchor not in text:
        raise RuntimeError(
            "_penalty_weight anchor not found"
        )

    text = text.replace(
        helper_anchor,
        helper + helper_anchor,
        1,
    )


path.write_text(
    text,
    encoding="utf-8",
)

print("CAPTAIN-058 patch: OK")
