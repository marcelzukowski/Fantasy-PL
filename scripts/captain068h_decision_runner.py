from __future__ import annotations

from copy import deepcopy
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
    / "captain068h"
)

DECISION = (
    ROOT
    / "scripts"
    / "captain068h_decision_impact.py"
)

BASE42 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v22_real"
)


RUNS = {
    42:
        BASE42,

    202627:
        OUT
        / "seed_202627",

    606:
        OUT
        / "seed_606",

    91991:
        OUT
        / "seed_91991",
}


REPORT_SOURCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "decision_impact.json"
)


def load(
    path,
):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


# ------------------------------------------------------------
# Validate paths.
# ------------------------------------------------------------

for seed, path in RUNS.items():

    if not path.exists():

        raise RuntimeError(
            f"Missing V22 seed run "
            f"{seed}: {path}"
        )


# ------------------------------------------------------------
# Build projection index for ensemble.
# ------------------------------------------------------------

def projection_index(
    payload,
):

    output = {}


    def visit(
        value,
    ):

        if isinstance(
            value,
            dict,
        ):

            if all(
                key in value
                for key in (
                    "player_id",
                    "target_gameweek",
                    "expected_points",
                )
            ):

                key = (
                    str(
                        value[
                            "player_id"
                        ]
                    ),
                    int(
                        value[
                            "target_gameweek"
                        ]
                    ),
                )

                output[
                    key
                ] = value


            for item in value.values():

                visit(
                    item
                )


        elif isinstance(
            value,
            list,
        ):

            for item in value:

                visit(
                    item
                )


    visit(
        payload
    )

    return output


payloads = {
    seed:
        load(
            path
            / "player_projections.json"
        )
    for seed, path
    in RUNS.items()
}


indices = {
    seed:
        projection_index(
            payload
        )
    for seed, payload
    in payloads.items()
}


key_sets = {
    seed:
        set(
            index
        )
    for seed, index
    in indices.items()
}


first_keys = next(
    iter(
        key_sets.values()
    )
)


if any(
    keys != first_keys
    for keys in key_sets.values()
):

    raise RuntimeError(
        "Projection keys differ "
        "between V22 seeds."
    )


ensemble_dir = (
    OUT
    / "ensemble_mean"
)


if ensemble_dir.exists():

    shutil.rmtree(
        ensemble_dir
    )


shutil.copytree(
    BASE42,
    ensemble_dir,
)


ensemble_payload = deepcopy(
    payloads[
        42
    ]
)

ensemble_index = projection_index(
    ensemble_payload
)


for key, row in ensemble_index.items():

    point_values = [
        float(
            indices[
                seed
            ][
                key
            ][
                "expected_points"
            ]
        )
        for seed
        in RUNS
    ]


    row[
        "expected_points"
    ] = (
        sum(
            point_values
        )
        / len(
            point_values
        )
    )


    if all(
        indices[
            seed
        ][
            key
        ].get(
            "expected_minutes"
        )
        is not None
        for seed
        in RUNS
    ):

        minute_values = [
            float(
                indices[
                    seed
                ][
                    key
                ][
                    "expected_minutes"
                ]
            )
            for seed
            in RUNS
        ]


        row[
            "expected_minutes"
        ] = (
            sum(
                minute_values
            )
            / len(
                minute_values
            )
        )


(
    ensemble_dir
    / "player_projections.json"
).write_text(
    json.dumps(
        ensemble_payload,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "ensemble projection:",
    ensemble_dir.relative_to(
        ROOT
    ),
)


# ------------------------------------------------------------
# Run exact decision layer.
# ------------------------------------------------------------

decision_targets = {
    **{
        str(seed):
            path
        for seed, path
        in RUNS.items()
    },

    "ensemble":
        ensemble_dir,
}


results = []


for label, run in decision_targets.items():

    print()
    print(
        "=" * 72
    )

    print(
        "DECISION WORLD:",
        label,
    )

    print(
        "=" * 72
    )


    env = os.environ.copy()

    env[
        "CAPTAIN068H_V22_RUN"
    ] = str(
        run
    )

    env[
        "PYTHONUTF8"
    ] = "1"

    env[
        "PYTHONIOENCODING"
    ] = "utf-8"


    log = (
        OUT
        / f"decision_{label}.log"
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
                    DECISION
                ),
            ],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )


    print(
        "decision status:",
        process.returncode,
    )


    if process.returncode != 0:

        print(
            "\n".join(
                log.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()[
                    -120:
                ]
            )
        )

        raise RuntimeError(
            f"Decision world {label} failed."
        )


    if not REPORT_SOURCE.exists():

        raise RuntimeError(
            "Decision report missing."
        )


    report = load(
        REPORT_SOURCE
    )


    if not report[
        "gates"
    ][
        "overall"
    ]:

        raise RuntimeError(
            f"Decision structural gate "
            f"failed for {label}."
        )


    destination = (
        OUT
        / f"decision_{label}.json"
    )


    shutil.copy2(
        REPORT_SOURCE,
        destination,
    )


    print(
        "decision gate: PASS"
    )


    results.append({
        "world":
            label,

        "run":
            str(
                run.relative_to(
                    ROOT
                )
            ),

        "report":
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


(
    OUT
    / "decision_runs.json"
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
    "MULTISEED DECISION RUNS: PASS"
)
