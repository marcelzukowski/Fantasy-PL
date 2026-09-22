from __future__ import annotations

from pathlib import Path
import json
import shutil


ROOT = Path(".").resolve()

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)

REFERENCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v1"
)

TARGET = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068i"
    / "rollback_v1"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068i"
    / "rollback_check.json"
)


FILES = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
    "event_projections.json",
    "goal_allocation_proxy.json",
    "player_projections.json",
    "run_manifest.json",
)


def load(path):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def find_values(
    value,
    key,
):

    output = []

    if isinstance(value, dict):

        for current_key, current_value in value.items():

            if current_key == key:

                output.append(
                    current_value
                )

            output.extend(
                find_values(
                    current_value,
                    key,
                )
            )

    elif isinstance(value, list):

        for item in value:

            output.extend(
                find_values(
                    item,
                    key,
                )
            )

    return output


if not ACCEPTANCE.exists():

    raise RuntimeError(
        "Acceptance report missing."
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
        f"Rollback run missing: {run}"
    )


if TARGET.exists():

    shutil.rmtree(
        TARGET
    )


shutil.copytree(
    run,
    TARGET,
)


manifest = load(
    TARGET
    / "run_manifest.json"
)


versions = sorted({
    str(value)
    for value
    in find_values(
        manifest,
        "simulator_version",
    )
})


identity_gate = any(
    value
    == "fixture_simulator_v1"
    for value in versions
)


comparisons = {}


for filename in FILES:

    left = (
        REFERENCE
        / filename
    )

    right = (
        TARGET
        / filename
    )


    if (
        not left.exists()
        and not right.exists()
    ):

        comparisons[
            filename
        ] = "ABSENT_BOTH"

        continue


    if (
        not left.exists()
        or not right.exists()
    ):

        comparisons[
            filename
        ] = "FAIL_MISSING"

        continue


    comparisons[
        filename
    ] = (
        "PASS"
        if load(left)
        == load(right)
        else "FAIL_DIFFERENT"
    )


#
# run_manifest can legitimately contain run-local metadata.
# Core semantic exactness is therefore checked separately.
#
CORE_EXACT = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
    "event_projections.json",
    "goal_allocation_proxy.json",
    "player_projections.json",
)


core_exact_gate = all(
    comparisons[
        filename
    ]
    == "PASS"
    for filename in CORE_EXACT
)


gate = (
    identity_gate
    and core_exact_gate
)


report = {
    "status":
        "CAPTAIN_068I_V1_ROLLBACK",

    "simulator_versions":
        versions,

    "comparison":
        comparisons,

    "gates": {
        "explicit_v1_identity":
            identity_gate,

        "core_exact":
            core_exact_gate,

        "overall":
            gate,
    },
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-068I EXPLICIT V1 ROLLBACK ==="
)

print(
    "simulator versions:",
    versions,
)

print()


for filename, status in comparisons.items():

    print(
        f"{filename:<28}",
        status,
    )


print()
print(
    "explicit V1 identity:",
    (
        "PASS"
        if identity_gate
        else "FAIL"
    ),
)

print(
    "core exact rollback:",
    (
        "PASS"
        if core_exact_gate
        else "FAIL"
    ),
)

print(
    "ROLLBACK GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not gate:

    raise RuntimeError(
        "CAPTAIN-068I explicit V1 "
        "rollback gate failed."
    )
