"""Point-in-time validation plus lazily loaded offline metrics."""
from .leakage import *


def __getattr__(name: str):
    from . import metrics
    try:
        return getattr(metrics, name)
    except AttributeError:
        raise AttributeError(name) from None
