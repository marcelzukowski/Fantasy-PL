"""Import smoke tests for the packages required by CORE-001."""

from importlib import import_module
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "package_name",
    [
        "fpl_engine",
        "fpl_engine.data",
        "fpl_engine.features",
        "fpl_engine.models",
        "fpl_engine.simulation",
        "fpl_engine.scoring",
        "fpl_engine.optimizer",
        "fpl_engine.validation",
        "fpl_engine.config",
    ],
)
def test_package_imports_from_src(package_name):
    """Each documented package imports from its local package initializer."""
    package = import_module(package_name)
    source_root = Path(__file__).resolve().parents[1] / "src"
    expected_init = source_root.joinpath(*package_name.split("."), "__init__.py")

    assert expected_init.is_file()
    assert package.__file__ is not None
    assert Path(package.__file__).resolve() == expected_init.resolve()
    assert hasattr(package, "__path__")
