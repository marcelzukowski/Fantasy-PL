from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


ROOT = Path(".").resolve()

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068j"
)

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)


def load(path):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def run_and_capture(
    *,
    label,
    script,
    environment,
):

    log = (
        OUT
        / f"{label}.log"
    )


    env = os.environ.copy()

    env.pop(
        "FPL_SIMULATOR_CHALLENGER",
        None,
    )

    env.pop(
        "CAPTAIN068H_SEED",
        None,
    )


    env.update(
        environment
    )


    env[
        "PYTHONUTF8"
    ] = "1"

    env[
        "PYTHONIOENCODING"
    ] = "utf-8"


    with log.open(
        "w",
        encoding="utf-8",
    ) as handle:

        result = subprocess.run(
            [
                sys.executable,
                "-u",
                str(
                    script
                ),
            ],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )


    log_text = log.read_text(
        encoding="utf-8",
        errors="replace",
    )


    #
    # These harnesses descend from CAPTAIN-067C.
    # Its old exact-V1 acceptance can legitimately fail
    # for the new default V22 or because run_manifest now
    # contains new simulator provenance.
    #
    # A traceback/crash is NOT accepted.
    #
    if result.returncode != 0:

        if (
            "DEFAULT RUNTIME GATE: FAIL"
            not in log_text
        ):

            print(
                "\n".join(
                    log_text.splitlines()[
                        -120:
                    ]
                )
            )

            raise RuntimeError(
                f"{label}: unexpected runtime "
                "harness failure."
            )


    if not ACCEPTANCE.exists():

        raise RuntimeError(
            f"{label}: acceptance report missing."
        )


    acceptance = load(
        ACCEPTANCE
    )


    run = Path(
        acceptance[
            "default_run"
        ]
    )


    if not run.is_absolute():

        run = ROOT / run


    if not run.exists():

        raise RuntimeError(
            f"{label}: generated run missing: "
            f"{run}"
        )


    destination = (
        OUT
        / label
    )


    if destination.exists():

        shutil.rmtree(
            destination
        )


    shutil.copytree(
        run,
        destination,
    )


    print()
    print(
        label
    )

    print(
        "legacy harness status:",
        result.returncode,
    )

    print(
        "captured:",
        destination.relative_to(
            ROOT
        ),
    )


    return {
        "label":
            label,

        "legacy_harness_status":
            result.returncode,

        "run":
            str(
                destination.relative_to(
                    ROOT
                )
            ),

        "log":
            str(
                log.relative_to(
                    ROOT
                )
            ),
    }


results = []


#
# REAL production default.
# No FPL_SIMULATOR_CHALLENGER exists in the subprocess.
#
results.append(
    run_and_capture(
        label="default_v22",

        script=(
            ROOT
            / "scripts"
            / "captain068j_default_runtime_acceptance.py"
        ),

        environment={},
    )
)


#
# Explicit rollback.
#
results.append(
    run_and_capture(
        label="explicit_v1",

        script=(
            ROOT
            / "scripts"
            / "captain068h_runtime_acceptance.py"
        ),

        environment={
            "FPL_SIMULATOR_CHALLENGER":
                "v1",

            "CAPTAIN068H_SEED":
                "42",
        },
    )
)


(
    OUT
    / "runtime_capture.json"
).write_text(
    json.dumps(
        results,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print()
print(
    "RUNTIME CAPTURE: PASS"
)
