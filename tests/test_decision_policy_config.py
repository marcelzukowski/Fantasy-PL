from pathlib import Path

import pytest

from fpl_engine.decision.policy_config import (
    DecisionPolicyConfigError,
    load_exact_chip_timing_config,
)


def _write(
    root: Path,
    content: str,
):

    path = (
        root
        / "config"
        / "decision_policy.yaml"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content,
        encoding="utf-8",
    )


def test_load_exact_chip_timing_policy(
    tmp_path,
):

    _write(
        tmp_path,
        """
version: 1
policy: test
chip_timing:
  evaluation_horizon_gameweeks: 6
  minimum_incremental_ev: 1.0
  future_opportunity_tolerance: 0.25
  wildcard_minimum_weighted_gain: 8.0
  free_hit_minimum_single_gameweek_gain: 6.0
""",
    )


    config = (
        load_exact_chip_timing_config(
            tmp_path
        )
    )


    assert (
        config
        .evaluation_horizon_gameweeks
        == 6
    )

    assert (
        config
        .minimum_incremental_ev
        == pytest.approx(
            1.0
        )
    )

    assert (
        config
        .future_opportunity_tolerance
        == pytest.approx(
            0.25
        )
    )

    assert (
        config
        .wildcard_minimum_weighted_gain
        == pytest.approx(
            8.0
        )
    )

    assert (
        config
        .free_hit_minimum_single_gameweek_gain
        == pytest.approx(
            6.0
        )
    )


def test_policy_loader_rejects_missing_config(
    tmp_path,
):

    with pytest.raises(
        DecisionPolicyConfigError,
        match="unavailable",
    ):

        load_exact_chip_timing_config(
            tmp_path
        )


def test_policy_loader_rejects_negative_threshold(
    tmp_path,
):

    _write(
        tmp_path,
        """
version: 1
policy: test
chip_timing:
  evaluation_horizon_gameweeks: 6
  minimum_incremental_ev: -1.0
  future_opportunity_tolerance: 0.25
  wildcard_minimum_weighted_gain: 8.0
  free_hit_minimum_single_gameweek_gain: 6.0
""",
    )


    with pytest.raises(
        DecisionPolicyConfigError,
        match="non-negative",
    ):

        load_exact_chip_timing_config(
            tmp_path
        )
