from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


ROOT = Path(".").resolve()

SOURCE_BASE = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

PROXY = (
    ROOT
    / "scratch"
    / "decision"
    / "captain062_canonical_goal_allocation"
    / "goal_allocation_proxy_canonical.json"
)

MULTI = (
    ROOT
    / "scratch"
    / "decision"
    / "captain063_same_source_multiseed"
)

REPLAY_SCRIPT = (
    ROOT
    / "scripts"
    / "captain060b_exact_offline_replay.py"
)

AGGREGATE_SCRIPT = (
    ROOT
    / "scripts"
    / "captain063_multiseed_aggregate.py"
)

SEEDS = (
    42,
    202627,
    606,
    91991,
)


def tail(
    path: Path,
    count: int = 30,
):

    if not path.exists():
        return ""

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    return "\n".join(
        lines[-count:]
    )


def run_replay(
    *,
    base_run: Path,
    work_root: Path,
    seed: int,
    mode: str,
    log_path: Path,
) -> int:

    env = os.environ.copy()

    env[
        "PYTHONUTF8"
    ] = "1"

    env[
        "PYTHONIOENCODING"
    ] = "utf-8"

    env[
        "CAPTAIN_BASE_RUN"
    ] = str(
        base_run
    )

    env[
        "CAPTAIN_PROXY_PATH"
    ] = str(
        PROXY
    )

    env[
        "CAPTAIN_WORK_ROOT"
    ] = str(
        work_root
    )

    env[
        "CAPTAIN_RANDOM_SEED"
    ] = str(
        seed
    )

    env[
        "CAPTAIN_EVENT_MODE"
    ] = mode


    log_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    with log_path.open(
        "w",
        encoding="utf-8",
    ) as handle:

        completed = subprocess.run(
            [
                sys.executable,
                "-u",
                str(
                    REPLAY_SCRIPT
                ),
            ],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )


    return int(
        completed.returncode
    )


#
# ------------------------------------------------------------
# Preconditions
# ------------------------------------------------------------
#

required = (
    SOURCE_BASE,
    PROXY,
    REPLAY_SCRIPT,
    AGGREGATE_SCRIPT,
)


for path in required:

    if not path.exists():

        raise RuntimeError(
            f"Missing required path: {path}"
        )


if MULTI.exists():

    shutil.rmtree(
        MULTI
    )


MULTI.mkdir(
    parents=True,
    exist_ok=True,
)


season_dir = (
    SOURCE_BASE.parent.name
)

run_stamp = (
    SOURCE_BASE.name
)


print(
    "=== CAPTAIN-063S "
    "SAME-SOURCE PAIRED MULTISEED ==="
)

print(
    "source:",
    SOURCE_BASE.relative_to(
        ROOT
    ),
)

print(
    "proxy:",
    PROXY.relative_to(
        ROOT
    ),
)

print(
    "seeds:",
    list(
        SEEDS
    ),
)

print(
    "source refresh: NO"
)


run_map = []


#
# ------------------------------------------------------------
# For every seed:
#
#   source baseline
#       |
#       +-- V1 replay(seed)
#       |
#       +-- challenger(seed)
#
# Challenger uses the freshly generated
# same-seed V1 run as its comparison baseline.
# ------------------------------------------------------------
#

for seed in SEEDS:

    print()
    print(
        f"--- seed {seed} ---"
    )


    seed_root = (
        MULTI
        / f"seed_{seed}"
    )

    baseline_work = (
        seed_root
        / "baseline"
    )

    challenger_work = (
        seed_root
        / "challenger"
    )

    baseline_log = (
        seed_root
        / "baseline.log"
    )

    challenger_log = (
        seed_root
        / "challenger.log"
    )


    baseline_status = run_replay(
        base_run=SOURCE_BASE,
        work_root=baseline_work,
        seed=seed,
        mode="baseline",
        log_path=baseline_log,
    )


    print(
        "baseline:",
        baseline_status,
    )


    baseline_run = (
        baseline_work
        / "output"
        / season_dir
        / run_stamp
    )


    if (
        baseline_status != 0
        or not baseline_run.exists()
    ):

        print(
            tail(
                baseline_log
            )
        )

        run_map.append({
            "Seed": seed,
            "Timestamp": (
                run_stamp
            ),
            "Baseline": str(
                baseline_run
            ),
            "WorkRoot": str(
                challenger_work
            ),
            "Report": str(
                challenger_work
                / "comparison.json"
            ),
            "Log": str(
                challenger_log
            ),
            "Status": (
                baseline_status
                if baseline_status != 0
                else 1
            ),
            "BaselineStatus": (
                baseline_status
            ),
            "ChallengerStatus": None,
        })

        continue


    challenger_status = (
        run_replay(
            base_run=baseline_run,
            work_root=challenger_work,
            seed=seed,
            mode="challenger",
            log_path=challenger_log,
        )
    )


    print(
        "challenger:",
        challenger_status,
    )


    report_path = (
        challenger_work
        / "comparison.json"
    )


    if challenger_status != 0:

        print(
            tail(
                challenger_log
            )
        )


    run_map.append({
        "Seed": seed,
        "Timestamp": run_stamp,
        "Baseline": str(
            baseline_run
        ),
        "WorkRoot": str(
            challenger_work
        ),
        "Report": str(
            report_path
        ),
        "Log": str(
            challenger_log
        ),
        "Status": (
            challenger_status
        ),
        "BaselineStatus": (
            baseline_status
        ),
        "ChallengerStatus": (
            challenger_status
        ),
    })


#
# ------------------------------------------------------------
# Write run map with Python.
# No PowerShell ConvertTo-Json dependency.
# ------------------------------------------------------------
#

run_map_path = (
    MULTI
    / "run_map.json"
)

run_map_path.write_text(
    json.dumps(
        run_map,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


all_success = (
    len(
        run_map
    )
    == len(
        SEEDS
    )
    and all(
        int(
            row[
                "Status"
            ]
        ) == 0
        for row in run_map
    )
)


print()
print(
    "paired runs:",
    (
        "PASS"
        if all_success
        else "FAIL"
    ),
)


if not all_success:

    print()
    print(
        "Run map:"
    )

    for row in run_map:

        print(
            f"  seed="
            f"{row['Seed']} "
            f"baseline="
            f"{row['BaselineStatus']} "
            f"challenger="
            f"{row['ChallengerStatus']}"
        )

    sys.exit(1)


#
# ------------------------------------------------------------
# Validate each comparison BEFORE aggregation.
# ------------------------------------------------------------
#

pair_validation = True


print()
print(
    "=== PAIR VALIDATION ==="
)


for row in run_map:

    report_path = Path(
        row[
            "Report"
        ]
    )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8"
        )
    )


    checks = {
        "upstream": bool(
            report[
                "upstream_pass"
            ]
        ),
        "envelope": bool(
            report[
                "team_goal_envelope_exact"
            ]
        ),
        "offline": (
            not bool(
                report[
                    "network_refresh"
                ]
            )
        ),
        "seed": (
            int(
                report[
                    "seed"
                ]
            )
            == int(
                row[
                    "Seed"
                ]
            )
        ),
        "canonical_proxy": (
            int(
                report[
                    "proxy_players"
                ]
            )
            == 399
        ),
    }


    ok = all(
        checks.values()
    )

    pair_validation = (
        pair_validation
        and ok
    )


    print(
        f"seed={row['Seed']} "
        f"upstream="
        f"{'PASS' if checks['upstream'] else 'FAIL'} "
        f"envelope="
        f"{'PASS' if checks['envelope'] else 'FAIL'} "
        f"offline="
        f"{'PASS' if checks['offline'] else 'FAIL'} "
        f"seed="
        f"{'PASS' if checks['seed'] else 'FAIL'} "
        f"proxy399="
        f"{'PASS' if checks['canonical_proxy'] else 'FAIL'}"
    )


if not pair_validation:

    raise RuntimeError(
        "At least one paired replay "
        "failed isolation validation."
    )


#
# ------------------------------------------------------------
# The existing aggregate script expects
# scratch/decision/captain063_multiseed/run_map.json.
#
# Give it a clean temporary compatibility directory.
# ------------------------------------------------------------
#

legacy_multi = (
    ROOT
    / "scratch"
    / "decision"
    / "captain063_multiseed"
)

if legacy_multi.exists():

    shutil.rmtree(
        legacy_multi
    )

legacy_multi.mkdir(
    parents=True,
    exist_ok=True,
)


(
    legacy_multi
    / "run_map.json"
).write_text(
    json.dumps(
        run_map,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


aggregate_log = (
    MULTI
    / "aggregate.log"
)


with aggregate_log.open(
    "w",
    encoding="utf-8",
) as handle:

    aggregate = subprocess.run(
        [
            sys.executable,
            "-u",
            str(
                AGGREGATE_SCRIPT
            ),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        check=False,
    )


aggregate_status = int(
    aggregate.returncode
)


print()
print(
    "aggregate:",
    aggregate_status,
)


if aggregate_status != 0:

    print(
        tail(
            aggregate_log,
            80,
        )
    )

    sys.exit(
        aggregate_status
    )


#
# Copy final report beside the paired runs.
#
legacy_report = (
    legacy_multi
    / "stability_report.json"
)

final_report = (
    MULTI
    / "stability_report.json"
)

shutil.copy2(
    legacy_report,
    final_report,
)


print()
print(
    "=== AGGREGATE OUTPUT ==="
)

print(
    aggregate_log.read_text(
        encoding="utf-8",
        errors="replace",
    )
)


print(
    "paired report:",
    final_report.relative_to(
        ROOT
    ),
)
