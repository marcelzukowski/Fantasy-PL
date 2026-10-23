from pathlib import Path
import subprocess
import sys

import pytest

from scripts.dev.check import run

ROOT = Path(__file__).resolve().parents[1]


def test_raw_gate_preserves_traceback_security_warning_build_error_and_failure(capfd):
    code = (
        "import sys; print('SECURITY WARNING: tooling sentinel', file=sys.stderr); "
        "print('BUILD ERROR: tooling sentinel', file=sys.stderr); "
        "raise RuntimeError('traceback details must remain visible')"
    )
    with pytest.raises(subprocess.CalledProcessError):
        run([sys.executable, "-c", code])
    output = capfd.readouterr()
    assert "SECURITY WARNING: tooling sentinel" in output.err
    assert "BUILD ERROR: tooling sentinel" in output.err
    assert "Traceback (most recent call last)" in output.err
    assert "RuntimeError: traceback details must remain visible" in output.err


def test_solver_dependency_is_dev_only_and_packaging_contract_is_untouched():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any("ortools" in item.lower() for item in project["project"]["dependencies"])
    spec = (ROOT / "FPLControlCenter_PL.spec").read_text(encoding="utf-8")
    assert "ortools" not in spec
    assert "scripts/dev" not in spec
