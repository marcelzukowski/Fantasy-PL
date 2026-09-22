from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(".").resolve()

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068j"
)

DEFAULT = (
    OUT
    / "default_v22"
)

ROLLBACK = (
    OUT
    / "explicit_v1"
)

REFERENCE_V22 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v22_real"
)

REFERENCE_V1 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v1"
)

REPORT = (
    OUT
    / "promotion_acceptance.json"
)


CORE = (
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

    if isinstance(
        value,
        dict,
    ):

        for current_key, item in value.items():

            if current_key == key:

                output.append(
                    item
                )


            output.extend(
                find_values(
                    item,
                    key,
                )
            )


    elif isinstance(
        value,
        list,
    ):

        for item in value:

            output.extend(
                find_values(
                    item,
                    key,
                )
            )


    return output


def compare_core(
    actual,
    reference,
):

    statuses = {}


    for filename in CORE:

        left = (
            actual
            / filename
        )

        right = (
            reference
            / filename
        )


        if (
            not left.exists()
            or not right.exists()
        ):

            statuses[
                filename
            ] = "FAIL_MISSING"

            continue


        statuses[
            filename
        ] = (
            "PASS"
            if load(left)
            == load(right)
            else "FAIL_DIFFERENT"
        )


    return statuses


default_core = compare_core(
    DEFAULT,
    REFERENCE_V22,
)

rollback_core = compare_core(
    ROLLBACK,
    REFERENCE_V1,
)


default_core_gate = all(
    status == "PASS"
    for status
    in default_core.values()
)

rollback_core_gate = all(
    status == "PASS"
    for status
    in rollback_core.values()
)


default_manifest = load(
    DEFAULT
    / "run_manifest.json"
)

rollback_manifest = load(
    ROLLBACK
    / "run_manifest.json"
)


default_versions = sorted({
    str(value)
    for value
    in find_values(
        default_manifest,
        "simulator_version",
    )
})

rollback_versions = sorted({
    str(value)
    for value
    in find_values(
        rollback_manifest,
        "simulator_version",
    )
})


default_identity_gate = any(
    value
    == "fixture_simulator_v22_lineup_coherent_logit"
    for value
    in default_versions
)

rollback_identity_gate = any(
    value
    == "fixture_simulator_v1"
    for value
    in rollback_versions
)


default_policy = default_manifest.get(
    "simulator_policy"
)

rollback_policy = rollback_manifest.get(
    "simulator_policy"
)


default_policy_gate = (
    isinstance(
        default_policy,
        dict,
    )
    and default_policy.get(
        "default"
    )
    == "v22"
    and default_policy.get(
        "runtime_selection"
    )
    == "v22"
    and default_policy.get(
        "explicit_v1_rollback"
    )
    is False
    and set(
        default_policy.get(
            "supported",
            [],
        )
    )
    == {
        "v1",
        "v2",
        "v21",
        "v22",
    }
)


rollback_policy_gate = (
    isinstance(
        rollback_policy,
        dict,
    )
    and rollback_policy.get(
        "default"
    )
    == "v22"
    and rollback_policy.get(
        "runtime_selection"
    )
    == "v1"
    and rollback_policy.get(
        "explicit_v1_rollback"
    )
    is True
)


gate = all((
    default_core_gate,
    rollback_core_gate,
    default_identity_gate,
    rollback_identity_gate,
    default_policy_gate,
    rollback_policy_gate,
))


report = {
    "status":
        "CAPTAIN_068J_DEFAULT_PROMOTION",

    "production_default":
        "v22",

    "explicit_rollback":
        "v1",

    "default_core":
        default_core,

    "rollback_core":
        rollback_core,

    "default_simulator_versions":
        default_versions,

    "rollback_simulator_versions":
        rollback_versions,

    "default_policy":
        default_policy,

    "rollback_policy":
        rollback_policy,

    "gates": {
        "default_exact_validated_v22":
            default_core_gate,

        "rollback_exact_validated_v1":
            rollback_core_gate,

        "default_identity_v22":
            default_identity_gate,

        "rollback_identity_v1":
            rollback_identity_gate,

        "default_policy":
            default_policy_gate,

        "rollback_policy":
            rollback_policy_gate,

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
    "=== CAPTAIN-068J PRODUCTION ACCEPTANCE ==="
)


print()
print(
    "=== DEFAULT / NO ENV ==="
)

print(
    "versions:",
    default_versions,
)


for filename, status in default_core.items():

    print(
        f"{filename:<28}",
        status,
    )


print(
    "policy:",
    default_policy,
)


print()
print(
    "=== EXPLICIT V1 ROLLBACK ==="
)

print(
    "versions:",
    rollback_versions,
)


for filename, status in rollback_core.items():

    print(
        f"{filename:<28}",
        status,
    )


print(
    "policy:",
    rollback_policy,
)


print()
print(
    "=== GATES ==="
)


for name, value in report[
    "gates"
].items():

    print(
        f"{name:<36}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "PRODUCTION PROMOTION GATE:",
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
        "CAPTAIN-068J production "
        "promotion gate failed."
    )
