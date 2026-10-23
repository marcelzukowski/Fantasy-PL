"""Fast local gates; child output is inherited verbatim, including failures."""

import argparse
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OWNED = ("scripts/dev", "tests/properties", "tests/test_developer_tooling.py")
CONTRACTS = (
    "tests/test_strategic_planner_v3.py",
    "tests/test_report_schemas.py",
    "tests/test_packaging_spec.py",
    "tests/properties",
    "tests/test_developer_tooling.py",
)


def run(command):
    print("RUN " + " ".join(map(str, command)), flush=True)
    # No RTK filters, shell interpolation, capture, truncation, or automatic fixes.
    subprocess.run(command, cwd=ROOT, check=True)


def staged_python(git):
    output = subprocess.check_output(
        [git, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], cwd=ROOT
    )
    return [
        name
        for name in output.decode("utf-8").split("\0")
        if name.endswith(".py") and (ROOT / name).is_file()
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    git = shutil.which("git.exe") or shutil.which("git")
    if git is None:
        raise SystemExit("Git executable is required")
    files = staged_python(git) if args.staged else []
    owned_files = sorted(
        {
            str(path.relative_to(ROOT))
            for name in OWNED
            for path in ((ROOT / name).rglob("*.py") if (ROOT / name).is_dir() else [ROOT / name])
            if path.is_file()
        }
    )
    files = sorted(set(files + owned_files))
    if files:
        run([sys.executable, "-m", "ruff", "check", *files])
        for name in files:
            py_compile.compile(str(ROOT / name), doraise=True)
    if owned_files:
        run([sys.executable, "-m", "ruff", "check", "--extend-select", "E4,E7,F", *owned_files])
        run([sys.executable, "-m", "ruff", "format", "--check", *owned_files])
    run([git, "diff", "--check", *(["--cached"] if args.staged else [])])
    run([sys.executable, "-m", "pytest", "-q", *CONTRACTS])


if __name__ == "__main__":
    main()
