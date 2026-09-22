"""FPL decision-engine primitives."""

from .horizon import (
    DecisionError,
    GameweekProjection,
    HorizonValue,
    TransferComparison,
    compare_transfer,
    horizon_value,
)

from .projection_adapter import (
    PlayerDecisionProjection,
    adapt_player_projection,
    adapt_player_projections,
    gameweek_projections_from_row,
    horizon_weights,
    rank_player_projections,
)

from .value import (
    PlayerValue,
    VALID_POSITIONS,
    build_player_value,
    build_player_values,
    rank_player_values,
)

from .transfers import (
    MAX_PLAYERS_PER_TEAM,
    SquadState,
    TransferOption,
    build_team_counts,
    rank_transfer_options,
    single_transfer_options,
)

from .squad_optimizer import (
    LineupTransferPlan,
    MultiGameweekCaptaincyTransferPlan,
    MultiGameweekTransferPlan,
    SquadTransferPlan,
    optimize_multi_gameweek_transfers,
    optimize_multi_gameweek_transfers_with_captaincy,
    optimize_squad_transfers,
    optimize_starting_xi_transfers,
)

from .captaincy import (
    CaptaincyHorizonEvaluation,
    GameweekCaptaincy,
    evaluate_squad_with_captaincy,
)

from .rolling_transfers import (
    RollingTransferPlan,
    optimize_rolling_free_transfers,
)

__all__ = [
    "optimize_rolling_free_transfers",
    "RollingTransferPlan",
    "optimize_multi_gameweek_transfers_with_captaincy",
    "MultiGameweekCaptaincyTransferPlan",
    "evaluate_squad_with_captaincy",
    "GameweekCaptaincy",
    "CaptaincyHorizonEvaluation",
    "optimize_multi_gameweek_transfers",
    "MultiGameweekTransferPlan",
    "optimize_starting_xi_transfers",
    "LineupTransferPlan",
    "optimize_squad_transfers",
    "SquadTransferPlan",
    "single_transfer_options",
    "rank_transfer_options",
    "build_team_counts",
    "TransferOption",
    "SquadState",
    "MAX_PLAYERS_PER_TEAM",
    "DecisionError",
    "GameweekProjection",
    "HorizonValue",
    "PlayerDecisionProjection",
    "PlayerValue",
    "TransferComparison",
    "VALID_POSITIONS",
    "adapt_player_projection",
    "adapt_player_projections",
    "build_player_value",
    "build_player_values",
    "compare_transfer",
    "gameweek_projections_from_row",
    "horizon_value",
    "horizon_weights",
    "rank_player_projections",
    "rank_player_values",
]
