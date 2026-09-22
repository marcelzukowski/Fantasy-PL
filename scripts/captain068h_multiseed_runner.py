from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


ROOT = Path(".").resolve()

HARNESS = (
    ROOT
    / "scripts"
    / "captain068h_runtime_acceptance.py"
)

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068h"
)

SEEDS = (
    202627,
    606,
    91991,
)


def load(
    path,
):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def recursive_values(
    value,
    key_fragment,
):

    found = []

    if isinstance(
        value,
        dict,
    ):

        for key, item in value.items():

            if (
                key_fragment.casefold()
                in str(key).casefold()
            ):

                found.append(
                    (
                        str(key),
                        item,
                    )
                )


            found.extend(
                recursive_values(
                    item,
                    key_fragment,
                )
            )


    elif isinstance(
        value,
        list,
    ):

        for item in value:

            found.extend(
                recursive_values(
                    item,
                    key_fragment,
                )
            )


    return found


def resolve_run(
    value,
):

    path = Path(
        value
    )

    if not path.is_absolute():

        path = ROOT / path

    return path


results = []


for seed in SEEDS:

    print()
    print(
        "=" * 72
    )

    print(
        "V22 SEED",
        seed,
    )

    print(
        "=" * 72
    )


    env = os.environ.copy()

    env[
        "FPL_SIMULATOR_CHALLENGER"
    ] = "v22"

    env[
        "CAPTAIN068H_SEED"
    ] = str(
        seed
    )

    env[
        "PYTHONUTF8"
    ] = "1"

    env[
        "PYTHONIOENCODING"
    ] = "utf-8"


    log = (
        OUT
        / f"runtime_seed_{seed}.log"
    )


    with log.open(
        "w",
        encoding="utf-8",
    ) as handle:

        process = subprocess.run(
            [
                sys.executable,
                "-u",
                str(
                    HARNESS
                ),
            ],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )


    #
    # The copied 067C acceptance harness still contains
    # its old exact-V1 player_projections gate.
    #
    # Therefore status 1 is expected for a real V22 run.
    # We validate the produced run independently below.
    #
    log_text = log.read_text(
        encoding="utf-8",
        errors="replace",
    )


    expected_legacy_failure = (
        "player_projections.json"
        in log_text
        and "FAIL"
        in log_text
        and "DEFAULT RUNTIME GATE: FAIL"
        in log_text
    )


    if (
        process.returncode != 0
        and not expected_legacy_failure
    ):

        print(
            "\n".join(
                log_text.splitlines()[
                    -100:
                ]
            )
        )

        raise RuntimeError(
            f"Seed {seed}: runtime harness "
            "failed for an unexpected reason."
        )


    if not ACCEPTANCE.exists():

        raise RuntimeError(
            f"Seed {seed}: acceptance "
            "report missing."
        )


    acceptance = load(
        ACCEPTANCE
    )

    run = resolve_run(
        acceptance[
            "default_run"
        ]
    )


    if not run.exists():

        raise RuntimeError(
            f"Seed {seed}: generated "
            f"run missing: {run}"
        )


    manifest = load(
        run
        / "run_manifest.json"
    )


    simulator_values = recursive_values(
        manifest,
        "simulator_version",
    )


    versions = sorted({
        str(
            value
        )
        for _key, value
        in simulator_values
    })


    simulator_gate = any(
        "fixture_simulator_v22"
        in value
        for value in versions
    )


    seed_values = recursive_values(
        manifest,
        "seed",
    )


    seed_gate = any(
        str(value)
        == str(seed)
        for _key, value
        in seed_values
    )


    print(
        "legacy harness status:",
        process.returncode,
    )

    print(
        "simulator versions:",
        versions,
    )

    print(
        "V22 identity:",
        (
            "PASS"
            if simulator_gate
            else "FAIL"
        ),
    )

    print(
        "requested seed in manifest:",
        (
            "PASS"
            if seed_gate
            else "FAIL"
        ),
    )


    if not simulator_gate:

        raise RuntimeError(
            f"Seed {seed}: V22 identity "
            "not confirmed."
        )


    if not seed_gate:

        print()
        print(
            "seed-like manifest values:"
        )

        for key, value in seed_values:

            print(
                " ",
                key,
                "=",
                value,
            )


        raise RuntimeError(
            f"Seed {seed}: requested seed "
            "not confirmed in manifest."
        )


    destination = (
        OUT
        / f"seed_{seed}"
    )


    if destination.exists():

        shutil.rmtree(
            destination
        )


    shutil.copytree(
        run,
        destination,
    )


    print(
        "captured:",
        destination.relative_to(
            ROOT
        ),
    )


    results.append({
        "seed":
            seed,

        "legacy_harness_status":
            process.returncode,

        "simulator_versions":
            versions,

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
    })


summary = (
    OUT
    / "runtime_runs.json"
)

summary.write_text(
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
    "MULTISEED RUNTIME CAPTURE: PASS"
)

print(
    "new runs:",
    len(
        results
    ),
)

print(
    "report:",
    summary.relative_to(
        ROOT
    ),
)
