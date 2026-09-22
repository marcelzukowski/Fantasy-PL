import inspect

from fpl_engine.features.minutes_dataset import (
    MinutesObservation,
)
from fpl_engine.models.minutes.validation import (
    walk_forward_minutes,
    _score,
)


print()
print(
    "============================================"
)
print(
    "MinutesObservation"
)
print(
    "============================================"
)

print(
    inspect.signature(
        MinutesObservation
    )
)

print()
print(
    "============================================"
)
print(
    "walk_forward_minutes"
)
print(
    "============================================"
)

print(
    inspect.getsource(
        walk_forward_minutes
    )
)

print()
print(
    "============================================"
)
print(
    "_score"
)
print(
    "============================================"
)

print(
    inspect.getsource(
        _score
    )
)

print()
print(
    "=== END ==="
)
