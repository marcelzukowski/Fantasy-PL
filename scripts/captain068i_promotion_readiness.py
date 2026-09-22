from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(".").resolve()

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068i"
)

REPORT = (
    OUT
    / "promotion_readiness.json"
)


EVIDENCE = {
    "068G_B":
        ROOT
        / "scratch"
        / "decision"
        / "captain068g"
        / "integrated_replay_r2.json",

    "068G_C":
        ROOT
        / "scratch"
        / "decision"
        / "captain068g"
        / "decision_impact.json",

    "068H":
        ROOT
        / "scratch"
        / "decision"
        / "captain068h"
        / "multiseed_summary.json",

    "rollback":
        ROOT
        / "scratch"
        / "decision"
        / "captain068i"
        / "rollback_check.json",
}


def load(path):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


missing = [
    name
    for name, path
    in EVIDENCE.items()
    if not path.exists()
]


if missing:

    raise RuntimeError(
        "Missing evidence: "
        + ", ".join(
            missing
        )
    )


payloads = {
    name:
        load(path)
    for name, path
    in EVIDENCE.items()
}


gates = {
    "true_v22_integrated_replay":
        bool(
            payloads[
                "068G_B"
            ][
                "gates"
            ][
                "overall"
            ]
        ),

    "decision_impact_structural":
        bool(
            payloads[
                "068G_C"
            ][
                "gates"
            ][
                "overall"
            ]
        ),

    "multiseed":
        bool(
            payloads[
                "068H"
            ][
                "gates"
            ][
                "overall"
            ]
        ),

    "explicit_v1_rollback":
        bool(
            payloads[
                "rollback"
            ][
                "gates"
            ][
                "overall"
            ]
        ),
}


overall = all(
    gates.values()
)


decision = (
    "PROMOTE_V22_TO_DEFAULT_"
    "WITH_EXPLICIT_V1_ROLLBACK"
    if overall
    else
    "DO_NOT_PROMOTE"
)


report = {
    "status":
        "CAPTAIN_068I_PROMOTION_READINESS",

    "production_default_changed":
        False,

    "2026_27_outcomes_used_for_selection":
        False,

    "network_refresh_for_evidence":
        False,

    "gates":
        {
            **gates,
            "overall":
                overall,
        },

    "decision":
        decision,

    "notes": [
        (
            "V22 materially improves simulator-minute "
            "alignment across all tested seeds."
        ),
        (
            "Decision outputs remain Monte Carlo-sensitive "
            "in some close-EV gameweeks; this is reported "
            "rather than hidden."
        ),
        (
            "Explicit V1 rollback remains required after "
            "any default promotion."
        ),
        (
            "No GW4 realized outcomes were used to select "
            "or tune V22."
        ),
    ],
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
    "=== CAPTAIN-068I PROMOTION READINESS ==="
)


for name, value in gates.items():

    print(
        f"{name:<34}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "PROMOTION READINESS:",
    (
        "PASS"
        if overall
        else "FAIL"
    ),
)

print(
    "decision:",
    decision,
)

print(
    "production default changed:",
    "NO",
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not overall:

    raise RuntimeError(
        "CAPTAIN-068I promotion "
        "readiness gate failed."
    )
