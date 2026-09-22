"""SIM-001 deterministic, fixture-scoped random streams."""

from dataclasses import dataclass
import hashlib

import numpy as np


@dataclass(frozen=True)
class SimulationRandom:
    """Derive stable independent streams without using Python's salted hash."""

    base_seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.base_seed, int) or self.base_seed < 0:
            raise ValueError("base_seed must be a non-negative integer")

    def derived_seed(self, fixture_id: str, stream: str = "fixture") -> int:
        if not fixture_id or not stream:
            raise ValueError("fixture_id and stream are required")
        material = f"fpl-engine-v1|{self.base_seed}|{fixture_id}|{stream}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)

    def generator(self, fixture_id: str, stream: str = "fixture") -> np.random.Generator:
        return np.random.default_rng(self.derived_seed(fixture_id, stream))

