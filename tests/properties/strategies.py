"""Build small legal synthetic inputs from the installed native rule configuration."""

from datetime import datetime, timezone
from pathlib import Path

from hypothesis import settings, strategies as st

from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState, selling_price

ROOT = Path(__file__).resolve().parents[2]
RULES = OptimizerRules.load(ROOT)
FAST = settings(max_examples=25, derandomize=True, deadline=None)


@st.composite
def legal_squads(draw):
    positions = [
        value["canonical_code"]
        for value in RULES.value("positions").values()
        for _ in range(value["squad_count"])
    ]
    cap = int(RULES.value("initial_squad", "maximum_players_per_club"))
    prices = draw(
        st.lists(st.tuples(st.integers(30, 150), st.integers(30, 150)), min_size=15, max_size=15)
    )
    players = tuple(
        SquadPlayer(
            f"synthetic-{index}",
            position,
            f"club-{index // cap}",
            purchase,
            current,
            selling_price(purchase, current, RULES),
        )
        for index, (position, (purchase, current)) in enumerate(zip(positions, prices))
    )
    return SquadState(
        players,
        draw(st.integers(0, 100)),
        draw(st.integers(1, 5)),
        ChipState(),
        8,
        RULES.season,
        RULES.version,
        datetime(2026, 10, 22, tzinfo=timezone.utc),
    )
