import inspect

from fpl_engine.decision.chip_squads import (
    UnlimitedSquadPlan,
    optimize_unlimited_squad,
)

from fpl_engine.decision.rolling_transfers import (
    RollingTransferPlan,
    optimize_rolling_free_transfers,
)


rolling = inspect.signature(
    optimize_rolling_free_transfers
)

wildcard = inspect.signature(
    optimize_unlimited_squad
)


checks = {
    "rolling appearance arg": (
        "appearance_by_player_gameweek"
        in rolling.parameters
    ),

    "wildcard appearance arg": (
        "appearance_by_player_gameweek"
        in wildcard.parameters
    ),

    "wildcard captaincy_weight": (
        "captaincy_weight"
        in wildcard.parameters
    ),

    "rolling vice output": (
        "vice_by_gameweek"
        in RollingTransferPlan.__dataclass_fields__
    ),

    "wildcard captain output": (
        "captain_by_gameweek"
        in UnlimitedSquadPlan.__dataclass_fields__
    ),

    "wildcard vice output": (
        "vice_by_gameweek"
        in UnlimitedSquadPlan.__dataclass_fields__
    ),

    "wildcard total EV": (
        "weighted_total_ev"
        in UnlimitedSquadPlan.__dataclass_fields__
    ),
}


print()
print(
    "=== API CONTRACT ==="
)

for name, passed in checks.items():

    print(
        f"{name:<32} "
        f"{'PASS' if passed else 'FAIL'}"
    )


assert all(
    checks.values()
)
