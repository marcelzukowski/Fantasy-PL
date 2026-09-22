from pathlib import Path

import yaml

from fpl_engine.current import (
    _load_active_model_manifest,
    _minutes_calibration_path,
    _runtime_model_stack,
)

from fpl_engine.models.minutes import (
    MinutesModel,
)

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)


ROOT = Path.cwd()


def test_active_manifest_selects_minutes_v2():

    manifest = (
        _load_active_model_manifest(
            ROOT,
            "2026/27",
        )
    )

    assert (
        manifest["active"]["minutes"]
        == "minutes_hurdle_v2"
    )


def test_runtime_stack_uses_minutes_v2():

    manifest = (
        _load_active_model_manifest(
            ROOT,
            "2026/27",
        )
    )

    _, minutes, _, _ = (
        _runtime_model_stack(
            manifest
        )
    )

    assert isinstance(
        minutes,
        HurdleTimeDecayMinutesModel,
    )


def test_runtime_stack_still_supports_v1():

    manifest = yaml.safe_load(
        (
            ROOT
            / "config"
            / "v1_champions.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    _, minutes, _, _ = (
        _runtime_model_stack(
            manifest
        )
    )

    assert type(minutes) is MinutesModel


def test_v2_calibration_path():

    path = _minutes_calibration_path(
        ROOT,
        "2025-26",
        "minutes_hurdle_v2",
    )

    assert (
        path.name
        == "minutes_calibration_v21_2025-26.json"
    )

    assert path.exists()


def test_v1_calibration_path():

    path = _minutes_calibration_path(
        ROOT,
        "2025-26",
        "minutes_hurdle_v1",
    )

    assert (
        path.name
        == "minutes_calibration_2025-26.json"
    )

    assert path.exists()
