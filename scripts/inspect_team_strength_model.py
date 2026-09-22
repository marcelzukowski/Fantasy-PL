from __future__ import annotations

import inspect

from fpl_engine.models.team_strength.model import (
    TeamStrengthConfig,
    TeamStrengthModel,
)


print()
print("============================================")
print("DEFAULT CONFIG")
print("============================================")
print(TeamStrengthConfig())

print()
print("============================================")
print("TeamStrengthConfig SOURCE")
print("============================================")
print(inspect.getsource(TeamStrengthConfig))

print()
print("============================================")
print("TeamStrengthModel SOURCE")
print("============================================")
print(inspect.getsource(TeamStrengthModel))

print()
print("=== END ===")
