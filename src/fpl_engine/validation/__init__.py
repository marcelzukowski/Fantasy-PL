"""Point-in-time validation, canonical metrics, and backtesting."""

from .leakage import *
from .metrics import *
# Advanced validation is intentionally not imported eagerly here.
# Import it explicitly from fpl_engine.validation.advanced.
# Eager importing creates a cycle:
# tactical_context -> validation.leakage -> validation.__init__
# -> validation.advanced -> player_talent -> tactical_context.
