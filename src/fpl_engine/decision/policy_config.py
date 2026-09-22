from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml

from .chip_timing import (
    ExactChipTimingConfig,
)


class DecisionPolicyConfigError(
    RuntimeError
):
    pass


_REQUIRED_CHIP_TIMING = (
    "evaluation_horizon_gameweeks",
    "minimum_incremental_ev",
    "future_opportunity_tolerance",
    "wildcard_minimum_weighted_gain",
    "free_hit_minimum_single_gameweek_gain",
)


def _mapping(
    value,
    name: str,
) -> Mapping:

    if not isinstance(
        value,
        Mapping,
    ):

        raise DecisionPolicyConfigError(
            f"{name} must be a mapping"
        )

    return value


def load_exact_chip_timing_config(
    root: Path,
) -> ExactChipTimingConfig:

    path = (
        Path(root)
        / "config"
        / "decision_policy.yaml"
    )


    try:

        payload = yaml.safe_load(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

    except OSError as exc:

        raise DecisionPolicyConfigError(
            "Decision policy configuration "
            f"is unavailable: {path}"
        ) from exc

    except yaml.YAMLError as exc:

        raise DecisionPolicyConfigError(
            "Decision policy configuration "
            "is invalid YAML"
        ) from exc


    payload = _mapping(
        payload,
        "decision policy root",
    )


    if int(
        payload.get(
            "version",
            -1,
        )
    ) != 1:

        raise DecisionPolicyConfigError(
            "Unsupported decision policy "
            "configuration version"
        )


    raw = _mapping(
        payload.get(
            "chip_timing"
        ),
        "chip_timing",
    )


    missing = [
        key
        for key
        in _REQUIRED_CHIP_TIMING
        if key not in raw
    ]


    if missing:

        raise DecisionPolicyConfigError(
            "chip_timing configuration "
            "is missing: "
            + ", ".join(
                missing
            )
        )


    try:

        config = ExactChipTimingConfig(
            evaluation_horizon_gameweeks=int(
                raw[
                    "evaluation_horizon_gameweeks"
                ]
            ),

            minimum_incremental_ev=float(
                raw[
                    "minimum_incremental_ev"
                ]
            ),

            future_opportunity_tolerance=float(
                raw[
                    "future_opportunity_tolerance"
                ]
            ),

            wildcard_minimum_weighted_gain=float(
                raw[
                    "wildcard_minimum_weighted_gain"
                ]
            ),

            free_hit_minimum_single_gameweek_gain=float(
                raw[
                    "free_hit_minimum_single_gameweek_gain"
                ]
            ),
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise DecisionPolicyConfigError(
            "chip_timing contains invalid "
            "numeric values"
        ) from exc


    if (
        config
        .evaluation_horizon_gameweeks
        < 1
    ):

        raise DecisionPolicyConfigError(
            "evaluation horizon must be positive"
        )


    nonnegative = {
        "minimum_incremental_ev":
            config.minimum_incremental_ev,

        "future_opportunity_tolerance":
            config.future_opportunity_tolerance,

        "wildcard_minimum_weighted_gain":
            config
            .wildcard_minimum_weighted_gain,

        "free_hit_minimum_single_gameweek_gain":
            config
            .free_hit_minimum_single_gameweek_gain,
    }


    bad = [
        name
        for name, value
        in nonnegative.items()
        if value < 0.0
    ]


    if bad:

        raise DecisionPolicyConfigError(
            "decision thresholds must be "
            "non-negative: "
            + ", ".join(
                bad
            )
        )


    return config
