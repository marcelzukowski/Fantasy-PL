from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import unicodedata


ROOT = Path(".").resolve()

HARNESS = (
    ROOT
    / "scripts"
    / "captain067c_default_runtime_acceptance.py"
)

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)

WORK = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay.json"
)


if not HARNESS.exists():

    raise RuntimeError(
        f"Missing CAPTAIN-067C harness: "
        f"{HARNESS}"
    )


def load(
    path: Path,
):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def resolve_project_path(
    value,
):

    path = Path(
        value
    )

    if path.is_absolute():
        return path

    return (
        ROOT
        / path
    )


def reset_dir(
    path: Path,
):

    if path.exists():

        shutil.rmtree(
            path
        )

    path.mkdir(
        parents=True,
        exist_ok=True,
    )


reset_dir(
    WORK
)


# ============================================================
# Run the existing no-refresh acceptance harness twice.
# ============================================================

def run_case(
    name: str,
    simulator: str,
):

    print()
    print(
        f"=== {name.upper()} ==="
    )

    print(
        "simulator override:",
        simulator,
    )

    env = os.environ.copy()

    env[
        "FPL_SIMULATOR_CHALLENGER"
    ] = simulator

    env[
        "PYTHONUTF8"
    ] = "1"

    env[
        "PYTHONIOENCODING"
    ] = "utf-8"


    harness_log = (
        WORK
        / f"{name}_harness.log"
    )


    with harness_log.open(
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


    print(
        "harness status:",
        process.returncode,
    )


    if process.returncode != 0:

        tail = (
            harness_log
            .read_text(
                encoding="utf-8",
                errors="replace",
            )
            .splitlines()[
                -80:
            ]
        )

        print(
            "\n".join(
                tail
            )
        )

        raise RuntimeError(
            f"{name}: CAPTAIN-067C "
            f"harness failed"
        )


    if not ACCEPTANCE.exists():

        raise RuntimeError(
            f"{name}: acceptance report "
            "was not created"
        )


    acceptance = load(
        ACCEPTANCE
    )

    source_run = resolve_project_path(
        acceptance[
            "default_run"
        ]
    )


    if not source_run.exists():

        raise RuntimeError(
            f"{name}: default run "
            f"does not exist: "
            f"{source_run}"
        )


    target = (
        WORK
        / name
    )

    if target.exists():

        shutil.rmtree(
            target
        )


    shutil.copytree(
        source_run,
        target,
    )


    print(
        "copied run:",
        target.relative_to(
            ROOT
        ),
    )


    return {
        "name":
            name,

        "simulator":
            simulator,

        "harness_status":
            process.returncode,

        "harness_log":
            str(
                harness_log.relative_to(
                    ROOT
                )
            ),

        "run":
            target,
    }


v1 = run_case(
    "v1",
    "v1",
)

v22 = run_case(
    "v22",
    "v22",
)


# ============================================================
# Artifact comparison
# ============================================================

UPSTREAM = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
    "event_projections.json",
    "goal_allocation_proxy.json",
)


upstream = {}


for filename in UPSTREAM:

    left = (
        v1[
            "run"
        ]
        / filename
    )

    right = (
        v22[
            "run"
        ]
        / filename
    )


    if (
        not left.exists()
        and not right.exists()
    ):

        upstream[
            filename
        ] = "ABSENT_BOTH"

        continue


    if (
        not left.exists()
        or not right.exists()
    ):

        upstream[
            filename
        ] = "FAIL_MISSING"

        continue


    upstream[
        filename
    ] = (
        "PASS"
        if load(
            left
        )
        == load(
            right
        )
        else "FAIL_DIFFERENT"
    )


upstream_gate = all(
    value
    in {
        "PASS",
        "ABSENT_BOTH",
    }
    for value in upstream.values()
)


# ============================================================
# Manifest simulator versions
# ============================================================

def recursively_find_values(
    value,
    key,
):

    found = []

    if isinstance(
        value,
        dict,
    ):

        for current_key, current_value in (
            value.items()
        ):

            if current_key == key:

                found.append(
                    current_value
                )

            found.extend(
                recursively_find_values(
                    current_value,
                    key,
                )
            )


    elif isinstance(
        value,
        list,
    ):

        for item in value:

            found.extend(
                recursively_find_values(
                    item,
                    key,
                )
            )


    return found


manifest_v1 = load(
    v1[
        "run"
    ]
    / "run_manifest.json"
)

manifest_v22 = load(
    v22[
        "run"
    ]
    / "run_manifest.json"
)


sim_versions_v1 = sorted({
    str(
        value
    )
    for value in recursively_find_values(
        manifest_v1,
        "simulator_version",
    )
})

sim_versions_v22 = sorted({
    str(
        value
    )
    for value in recursively_find_values(
        manifest_v22,
        "simulator_version",
    )
})


simulator_gate = (
    any(
        "fixture_simulator_v22"
        in value
        for value in sim_versions_v22
    )
    and sim_versions_v1
    != sim_versions_v22
)


# ============================================================
# Projection schema extraction
# ============================================================

def collect_gameweek_rows(
    value,
):

    rows = []


    def visit(
        current,
    ):

        if isinstance(
            current,
            dict,
        ):

            if all(
                key in current
                for key in (
                    "player_id",
                    "target_gameweek",
                    "expected_minutes",
                )
            ):

                rows.append(
                    current
                )


            for item in current.values():

                visit(
                    item
                )


        elif isinstance(
            current,
            list,
        ):

            for item in current:

                visit(
                    item
                )


    visit(
        value
    )


    output = {}


    conflicts = []


    for row in rows:

        key = (
            str(
                row[
                    "player_id"
                ]
            ),
            int(
                row[
                    "target_gameweek"
                ]
            ),
        )


        record = {
            "player_id":
                key[
                    0
                ],

            "target_gameweek":
                key[
                    1
                ],

            "expected_minutes":
                float(
                    row[
                        "expected_minutes"
                    ]
                ),

            "expected_points":
                (
                    float(
                        row[
                            "expected_points"
                        ]
                    )
                    if row.get(
                        "expected_points"
                    )
                    is not None
                    else None
                ),
        }


        if (
            key in output
            and output[
                key
            ]
            != record
        ):

            conflicts.append(
                key
            )


        output[
            key
        ] = record


    return (
        output,
        conflicts,
    )


projection_v1 = load(
    v1[
        "run"
    ]
    / "player_projections.json"
)

projection_v22 = load(
    v22[
        "run"
    ]
    / "player_projections.json"
)


(
    gw_v1,
    conflicts_v1,
) = collect_gameweek_rows(
    projection_v1
)

(
    gw_v22,
    conflicts_v22,
) = collect_gameweek_rows(
    projection_v22
)


projection_key_gate = (
    set(
        gw_v1
    )
    == set(
        gw_v22
    )
    and not conflicts_v1
    and not conflicts_v22
    and len(
        gw_v1
    )
    > 0
)


# ============================================================
# Model-minute source-of-truth map
# ============================================================

horizon = load(
    v1[
        "run"
    ]
    / "fixture_horizon.json"
)

minutes = load(
    v1[
        "run"
    ]
    / "minutes.json"
)


fixture_to_gw = {
    str(
        row[
            "fixture_id"
        ]
    ):
    int(
        row[
            "target_gameweek"
        ]
    )
    for row in horizon
}


model_groups = defaultdict(
    list
)


for row in minutes:

    fixture_id = str(
        row[
            "fixture_id"
        ]
    )

    gameweek = fixture_to_gw.get(
        fixture_id
    )


    if gameweek is None:

        continue


    model_groups[
        (
            str(
                row[
                    "player_id"
                ]
            ),
            gameweek,
        )
    ].append(
        row
    )


#
# Current replay has one fixture/player/GW.
# Do not silently compare DGW aggregates against single fixture
# expectations.
#
single_fixture_model = {
    key:
        rows[
            0
        ]
    for key, rows in model_groups.items()
    if len(
        rows
    )
    == 1
}


comparison_keys = sorted(
    set(
        gw_v1
    )
    & set(
        gw_v22
    )
    & set(
        single_fixture_model
    )
)


if not comparison_keys:

    raise RuntimeError(
        "No single-fixture minute "
        "comparison rows found."
    )


def abs_errors(
    projection,
    *,
    high_start_only=False,
):

    result = []


    for key in comparison_keys:

        model = single_fixture_model[
            key
        ]

        if (
            high_start_only
            and float(
                model[
                    "p_start"
                ]
            )
            < 0.75
        ):

            continue


        result.append(
            abs(
                float(
                    projection[
                        key
                    ][
                        "expected_minutes"
                    ]
                )
                - float(
                    model[
                        "expected_minutes"
                    ]
                )
            )
        )


    return result


v1_errors = abs_errors(
    gw_v1
)

v22_errors = abs_errors(
    gw_v22
)

v1_high_errors = abs_errors(
    gw_v1,
    high_start_only=True,
)

v22_high_errors = abs_errors(
    gw_v22,
    high_start_only=True,
)


minute_alignment = {
    "rows":
        len(
            comparison_keys
        ),

    "v1_mae":
        mean(
            v1_errors
        ),

    "v22_mae":
        mean(
            v22_errors
        ),

    "v1_high_pstart_mae":
        mean(
            v1_high_errors
        ),

    "v22_high_pstart_mae":
        mean(
            v22_high_errors
        ),

    "high_pstart_rows":
        len(
            v1_high_errors
        ),
}


minute_alignment_gate = all((
    minute_alignment[
        "v22_mae"
    ]
    < minute_alignment[
        "v1_mae"
    ],

    minute_alignment[
        "v22_high_pstart_mae"
    ]
    < minute_alignment[
        "v1_high_pstart_mae"
    ],
))


# ============================================================
# Player names
# ============================================================

players = load(
    v1[
        "run"
    ]
    / "current_players.json"
)


def player_name(
    row,
):

    for key in (
        "display_name",
        "web_name",
        "name",
        "player_name",
    ):

        value = row.get(
            key
        )

        if value:

            return str(
                value
            )


    payload = row.get(
        "provider_payload"
    )


    if isinstance(
        payload,
        dict,
    ):

        for key in (
            "web_name",
            "second_name",
            "first_name",
        ):

            value = payload.get(
                key
            )

            if value:

                return str(
                    value
                )


    return str(
        row.get(
            "player_id",
            "",
        )
    )


names = {
    str(
        row[
            "player_id"
        ]
    ):
    player_name(
        row
    )
    for row in players
}


def normalize(
    value,
):

    value = unicodedata.normalize(
        "NFKD",
        str(
            value
        ),
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(
            character
        )
    )

    return (
        value
        .lower()
        .replace(
            "-",
            "",
        )
        .replace(
            " ",
            "",
        )
        .replace(
            ".",
            "",
        )
    )


def find_player(
    needle,
):

    target = normalize(
        needle
    )

    matches = [
        player_id
        for player_id, name
        in names.items()
        if target
        in normalize(
            name
        )
    ]


    if len(
        matches
    ) != 1:

        return None


    return matches[
        0
    ]


haaland = find_player(
    "Haaland"
)

costinha = find_player(
    "Costinha"
)


# ============================================================
# Named player comparison
# ============================================================

def named_rows(
    player_id,
):

    if player_id is None:

        return []


    rows = []


    for key in comparison_keys:

        if key[
            0
        ] != player_id:

            continue


        model = single_fixture_model[
            key
        ]

        old = gw_v1[
            key
        ]

        new = gw_v22[
            key
        ]


        rows.append({
            "gameweek":
                key[
                    1
                ],

            "model_p_start":
                float(
                    model[
                        "p_start"
                    ]
                ),

            "model_p_appearance":
                float(
                    model[
                        "p_appearance"
                    ]
                ),

            "model_minutes":
                float(
                    model[
                        "expected_minutes"
                    ]
                ),

            "v1_minutes":
                float(
                    old[
                        "expected_minutes"
                    ]
                ),

            "v22_minutes":
                float(
                    new[
                        "expected_minutes"
                    ]
                ),

            "v1_points":
                old[
                    "expected_points"
                ],

            "v22_points":
                new[
                    "expected_points"
                ],

            "minute_error_v1":
                abs(
                    float(
                        old[
                            "expected_minutes"
                        ]
                    )
                    - float(
                        model[
                            "expected_minutes"
                        ]
                    )
                ),

            "minute_error_v22":
                abs(
                    float(
                        new[
                            "expected_minutes"
                        ]
                    )
                    - float(
                        model[
                            "expected_minutes"
                        ]
                    )
                ),
        })


    return sorted(
        rows,
        key=lambda row:
            row[
                "gameweek"
            ],
    )


haaland_rows = named_rows(
    haaland
)

costinha_rows = named_rows(
    costinha
)


haaland_gate = (
    bool(
        haaland_rows
    )
    and mean(
        row[
            "minute_error_v22"
        ]
        for row in haaland_rows
    )
    < mean(
        row[
            "minute_error_v1"
        ]
        for row in haaland_rows
    )
)


# ============================================================
# Point changes
# ============================================================

point_changes = []


for key in comparison_keys:

    old = gw_v1[
        key
    ]

    new = gw_v22[
        key
    ]


    if (
        old[
            "expected_points"
        ]
        is None
        or new[
            "expected_points"
        ]
        is None
    ):

        continue


    delta = (
        new[
            "expected_points"
        ]
        - old[
            "expected_points"
        ]
    )


    point_changes.append({
        "player_id":
            key[
                0
            ],

        "name":
            names.get(
                key[
                    0
                ],
                key[
                    0
                ],
            ),

        "gameweek":
            key[
                1
            ],

        "v1_points":
            old[
                "expected_points"
            ],

        "v22_points":
            new[
                "expected_points"
            ],

        "delta":
            delta,

        "v1_minutes":
            old[
                "expected_minutes"
            ],

        "v22_minutes":
            new[
                "expected_minutes"
            ],
    })


top_point_changes = sorted(
    point_changes,
    key=lambda row:
        abs(
            row[
                "delta"
            ]
        ),
    reverse=True,
)[
    :20
]


# ============================================================
# GW4 EV rankings
# ============================================================

def gw_rank(
    projection,
    gameweek,
):

    rows = []


    for (
        player_id,
        gw,
    ), row in projection.items():

        if (
            gw != gameweek
            or row[
                "expected_points"
            ]
            is None
        ):

            continue


        rows.append({
            "player_id":
                player_id,

            "name":
                names.get(
                    player_id,
                    player_id,
                ),

            "expected_points":
                row[
                    "expected_points"
                ],

            "expected_minutes":
                row[
                    "expected_minutes"
                ],
        })


    return sorted(
        rows,
        key=lambda row:
            (
                -row[
                    "expected_points"
                ],
                row[
                    "player_id"
                ],
            ),
    )


gw4_v1 = gw_rank(
    gw_v1,
    4,
)[
    :10
]

gw4_v22 = gw_rank(
    gw_v22,
    4,
)[
    :10
]


# ============================================================
# Final gate
# ============================================================

player_projection_changed = (
    projection_v1
    != projection_v22
)


gate = all((
    upstream_gate,
    simulator_gate,
    projection_key_gate,
    minute_alignment_gate,
    haaland_gate,
    player_projection_changed,
))


report = {
    "status":
        "CAPTAIN_068G_B_"
        "INTEGRATED_REPLAY",

    "source_harness":
        str(
            HARNESS.relative_to(
                ROOT
            )
        ),

    "network_refresh":
        False,

    "current_2026_27_outcomes_used":
        False,

    "goal_allocation_policy":
        "production default",

    "production_default_simulator_changed":
        False,

    "explicit_challenger_wiring_added":
        True,

    "cases": {
        "v1": {
            "run":
                str(
                    v1[
                        "run"
                    ].relative_to(
                        ROOT
                    )
                ),

            "simulator_versions":
                sim_versions_v1,
        },

        "v22": {
            "run":
                str(
                    v22[
                        "run"
                    ].relative_to(
                        ROOT
                    )
                ),

            "simulator_versions":
                sim_versions_v22,
        },
    },

    "upstream_exact":
        upstream,

    "projection_rows":
        len(
            gw_v1
        ),

    "minute_alignment":
        minute_alignment,

    "haaland":
        haaland_rows,

    "costinha":
        costinha_rows,

    "largest_point_changes":
        top_point_changes,

    "gw4_top_ev": {
        "v1":
            gw4_v1,

        "v22":
            gw4_v22,
    },

    "gates": {
        "upstream_exact":
            upstream_gate,

        "simulator_version":
            simulator_gate,

        "projection_keys":
            projection_key_gate,

        "minute_alignment_improved":
            minute_alignment_gate,

        "haaland_alignment_improved":
            haaland_gate,

        "player_projections_changed":
            player_projection_changed,

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


# ============================================================
# Console
# ============================================================

print()
print(
    "=== CAPTAIN-068G-B "
    "INTEGRATED REPLAY ==="
)

print(
    "network refresh:",
    "NO",
)

print(
    "2026/27 outcomes used:",
    "NO",
)

print(
    "production default simulator changed:",
    "NO",
)


print()
print(
    "=== SIMULATORS ==="
)

print(
    "V1 :",
    sim_versions_v1,
)

print(
    "V22:",
    sim_versions_v22,
)


print()
print(
    "=== UPSTREAM EXACT ==="
)

for filename, status in (
    upstream.items()
):

    print(
        f"{filename:<28}",
        status,
    )


print()
print(
    "=== MODEL -> SIMULATED MINUTES ==="
)

print(
    "rows:",
    minute_alignment[
        "rows"
    ],
)

print(
    "V1 MAE :",
    f"{minute_alignment['v1_mae']:.3f}",
)

print(
    "V22 MAE:",
    f"{minute_alignment['v22_mae']:.3f}",
)

print(
    "high-pStart rows:",
    minute_alignment[
        "high_pstart_rows"
    ],
)

print(
    "V1 high-pStart MAE :",
    f"{minute_alignment['v1_high_pstart_mae']:.3f}",
)

print(
    "V22 high-pStart MAE:",
    f"{minute_alignment['v22_high_pstart_mae']:.3f}",
)


def print_named(
    label,
    rows,
):

    print()
    print(
        f"=== {label} ==="
    )


    if not rows:

        print(
            "not uniquely resolved"
        )

        return


    for row in rows:

        points_text = ""

        if (
            row[
                "v1_points"
            ]
            is not None
            and row[
                "v22_points"
            ]
            is not None
        ):

            points_text = (
                " | pts "
                f"{row['v1_points']:.3f}"
                " -> "
                f"{row['v22_points']:.3f}"
            )


        print(
            f"GW{row['gameweek']} "
            f"model="
            f"{row['model_minutes']:.2f} "
            f"V1="
            f"{row['v1_minutes']:.2f} "
            f"V22="
            f"{row['v22_minutes']:.2f}"
            f"{points_text}"
        )


print_named(
    "HAALAND",
    haaland_rows,
)

print_named(
    "COSTINHA",
    costinha_rows,
)


print()
print(
    "=== TOP 10 GW4 EV / V1 ==="
)

for index, row in enumerate(
    gw4_v1,
    start=1,
):

    print(
        f"{index:2d}. "
        f"{row['name']:<24} "
        f"EV={row['expected_points']:.3f} "
        f"min={row['expected_minutes']:.1f}"
    )


print()
print(
    "=== TOP 10 GW4 EV / V22 ==="
)

for index, row in enumerate(
    gw4_v22,
    start=1,
):

    print(
        f"{index:2d}. "
        f"{row['name']:<24} "
        f"EV={row['expected_points']:.3f} "
        f"min={row['expected_minutes']:.1f}"
    )


print()
print(
    "=== TOP 12 EV CHANGES ==="
)

for row in (
    top_point_changes[
        :12
    ]
):

    print(
        f"GW{row['gameweek']} "
        f"{row['name']:<24} "
        f"EV "
        f"{row['v1_points']:.3f}"
        f" -> "
        f"{row['v22_points']:.3f} "
        f"delta="
        f"{row['delta']:+.3f} "
        f"min "
        f"{row['v1_minutes']:.1f}"
        f" -> "
        f"{row['v22_minutes']:.1f}"
    )


print()
print(
    "=== GATES ==="
)

for name, value in (
    report[
        "gates"
    ].items()
):

    print(
        f"{name:<30}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "INTEGRATED REPLAY GATE:",
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
        "CAPTAIN-068G-B integrated "
        "replay gate failed."
    )
