"""Optional external price-risk input contract for strategic planning.

No provider is selected here.  A caller may supply cached, attributable
signals; absence is explicit and never results in an HTTP request or a made-up
future price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol


@dataclass(frozen=True)
class PriceChangeSignal:
    player_id: str
    current_price: int
    direction: str
    observed_at: datetime
    source: str
    confidence: float | None = None
    expected_next_change: int | None = None

    def __post_init__(self) -> None:
        if not self.player_id or not self.source:
            raise ValueError("price signals require player_id and source")
        if type(self.current_price) is not int or self.current_price < 0:
            raise ValueError("current_price must use non-negative 0.1m units")
        if self.direction not in {"rise", "fall", "stable"}:
            raise ValueError("direction must be rise, fall or stable")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.expected_next_change is not None and type(self.expected_next_change) is not int:
            raise ValueError("expected_next_change must use integer 0.1m units")

    @property
    def observed_at_utc(self) -> datetime:
        return self.observed_at.astimezone(timezone.utc)


class PriceSignalProvider(Protocol):
    """Optional cached-price input. Implementations must not mutate account state."""

    def signals(self) -> Mapping[str, PriceChangeSignal]: ...
