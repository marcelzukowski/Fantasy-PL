from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
import json
import math
import unicodedata


ROOT = Path(".").resolve()

V1 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v1"
)

V22 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v22_real"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay_r2.json"
)


def load(path):

    return json.loads(
        path.read_text(
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

        for current_key, current_value in (
            value.items()
        ):

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


for path in (
    V1,
    V22,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing replay run: {path}"
        )


# ============================================================
# Simulator identities
# ============================================================

manifest_v1 = load(
    V1
    / "run_manifest.json"
)

manifest_v22 = load(
    V22
    / "run_manifest.json"
)


versions_v1 = sorted({
    str(
        value
    )
    for value in find_values(
        manifest_v1,
        "simulator_version",
    )
})

versions_v22 = sorted({
    str(
        value
    )
    for value in find_values(
        manifest_v22,
        "simulator_version",
    )
})


simulator_gate = all((
    any(
        "fixture_simulator_v1"
        in value
        for value in versions_v1
    ),

    any(
        "fixture_simulator_v22"
        in value
        for value in versions_v22
    ),
))


# ============================================================
# Upstream exactness
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

    left = V1 / filename
    right = V22 / filename


    if (
        not left.exists()
        and not right.exists()
    ):

        upstream[
            filename
        ] = "ABSENT_BOTH"

    elif (
        not left.exists()
        or not right.exists()
    ):

        upstream[
            filename
        ] = "FAIL_MISSING"

    else:

        upstream[
            filename
        ] = (
            "PASS"
            if load(left)
            == load(right)
            else "FAIL_DIFFERENT"
        )


upstream_gate = all(
    status
    in {
        "PASS",
        "ABSENT_BOTH",
    }
    for status in upstream.values()
)


# ============================================================
# Projection extraction
# ============================================================

def collect_projection_rows(
    value,
):

    output = {}


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

                key = (
                    str(
                        current[
                            "player_id"
                        ]
                    ),
                    int(
                        current[
                            "target_gameweek"
                        ]
                    ),
                )

                output[
                    key
                ] = {
                    "expected_minutes":
                        float(
                            current[
                                "expected_minutes"
                            ]
                        ),

                    "expected_points":
                        (
                            float(
                                current[
                                    "expected_points"
                                ]
                            )
                            if current.get(
                                "expected_points"
                            )
                            is not None
                            else None
                        ),
                }


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

    return output


projection_v1 = collect_projection_rows(
    load(
        V1
        / "player_projections.json"
    )
)

projection_v22 = collect_projection_rows(
    load(
        V22
        / "player_projections.json"
    )
)


projection_keys_gate = (
    set(
        projection_v1
    )
    == set(
        projection_v22
    )
    and len(
        projection_v1
    )
    > 0
)


# ============================================================
# Authoritative model minutes
# ============================================================

horizon = load(
    V1
    / "fixture_horizon.json"
)

minutes = load(
    V1
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


groups = defaultdict(
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


    groups[
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


single_fixture = {
    key:
        rows[
            0
        ]
    for key, rows in groups.items()
    if len(
        rows
    )
    == 1
}


keys = sorted(
    set(
        projection_v1
    )
    & set(
        projection_v22
    )
    & set(
        single_fixture
    )
)


if not keys:

    raise RuntimeError(
        "No comparable minute rows."
    )


def errors(
    projection,
    *,
    high=False,
):

    result = []


    for key in keys:

        model = single_fixture[
            key
        ]


        if (
            high
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
                projection[
                    key
                ][
                    "expected_minutes"
                ]
                - float(
                    model[
                        "expected_minutes"
                    ]
                )
            )
        )


    return result


v1_errors = errors(
    projection_v1
)

v22_errors = errors(
    projection_v22
)

v1_high = errors(
    projection_v1,
    high=True,
)

v22_high = errors(
    projection_v22,
    high=True,
)


alignment = {
    "rows":
        len(
            keys
        ),

    "v1_mae":
        mean(
            v1_errors
        ),

    "v22_mae":
        mean(
            v22_errors
        ),

    "high_rows":
        len(
            v1_high
        ),

    "v1_high_mae":
        mean(
            v1_high
        ),

    "v22_high_mae":
        mean(
            v22_high
        ),
}


alignment_gate = all((
    alignment[
        "v22_mae"
    ]
    < alignment[
        "v1_mae"
    ],

    alignment[
        "v22_high_mae"
    ]
    < alignment[
        "v1_high_mae"
    ],
))


# ============================================================
# Names
# ============================================================

players = load(
    V1
    / "current_players.json"
)


def name_of(
    row,
):

    for key in (
        "display_name",
        "web_name",
        "name",
        "player_name",
    ):

        if row.get(
            key
        ):

            return str(
                row[
                    key
                ]
            )


    payload = row.get(
        "provider_payload"
    )

    if isinstance(
        payload,
        dict,
    ):

        if payload.get(
            "web_name"
        ):

            return str(
                payload[
                    "web_name"
                ]
            )


    return str(
        row[
            "player_id"
        ]
    )


names = {
    str(
        row[
            "player_id"
        ]
    ):
    name_of(
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

    return "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    ).lower().replace(
        " ",
        "",
    ).replace(
        "-",
        "",
    )


def resolve(
    needle,
):

    needle = normalize(
        needle
    )

    matches = [
        player_id
        for player_id, name
        in names.items()
        if needle
        in normalize(
            name
        )
    ]

    return (
        matches[
            0
        ]
        if len(
            matches
        )
        == 1
        else None
    )


HAALAND = resolve(
    "Haaland"
)

COSTINHA = resolve(
    "Costinha"
)


def named_rows(
    player_id,
):

    if player_id is None:

        return []


    rows = []


    for key in keys:

        if key[
            0
        ] != player_id:

            continue


        model = single_fixture[
            key
        ]

        old = projection_v1[
            key
        ]

        new = projection_v22[
            key
        ]


        rows.append({
            "gameweek":
                key[
                    1
                ],

            "model_minutes":
                float(
                    model[
                        "expected_minutes"
                    ]
                ),

            "p_start":
                float(
                    model[
                        "p_start"
                    ]
                ),

            "v1_minutes":
                old[
                    "expected_minutes"
                ],

            "v22_minutes":
                new[
                    "expected_minutes"
                ],

            "v1_points":
                old[
                    "expected_points"
                ],

            "v22_points":
                new[
                    "expected_points"
                ],
        })


    return sorted(
        rows,
        key=lambda row:
            row[
                "gameweek"
            ],
    )


haaland_rows = named_rows(
    HAALAND
)

costinha_rows = named_rows(
    COSTINHA
)


haaland_gate = (
    bool(
        haaland_rows
    )
    and mean(
        abs(
            row[
                "v22_minutes"
            ]
            - row[
                "model_minutes"
            ]
        )
        for row in haaland_rows
    )
    < mean(
        abs(
            row[
                "v1_minutes"
            ]
            - row[
                "model_minutes"
            ]
        )
        for row in haaland_rows
    )
)


# ============================================================
# EV changes
# ============================================================

changes = []


for key in keys:

    old = projection_v1[
        key
    ]

    new = projection_v22[
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


    changes.append({
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
            (
                new[
                    "expected_points"
                ]
                - old[
                    "expected_points"
                ]
            ),

        "v1_minutes":
            old[
                "expected_minutes"
            ],

        "v22_minutes":
            new[
                "expected_minutes"
            ],
    })


largest = sorted(
    changes,
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


def rank_gw4(
    projection,
):

    rows = []


    for (
        player_id,
        gameweek,
    ), row in projection.items():

        if (
            gameweek != 4
            or row[
                "expected_points"
            ]
            is None
        ):

            continue


        rows.append({
            "name":
                names.get(
                    player_id,
                    player_id,
                ),

            "points":
                row[
                    "expected_points"
                ],

            "minutes":
                row[
                    "expected_minutes"
                ],
        })


    return sorted(
        rows,
        key=lambda row:
            -row[
                "points"
            ],
    )[
        :10
    ]


gw4_v1 = rank_gw4(
    projection_v1
)

gw4_v22 = rank_gw4(
    projection_v22
)


projections_changed = (
    projection_v1
    != projection_v22
)


gate = all((
    simulator_gate,
    upstream_gate,
    projection_keys_gate,
    alignment_gate,
    haaland_gate,
    projections_changed,
))


report = {
    "status":
        "CAPTAIN_068G_B_R2_"
        "TRUE_V22_REPLAY",

    "network_refresh":
        False,

    "2026_27_outcomes_used":
        False,

    "production_default_changed":
        False,

    "simulator_versions": {
        "v1":
            versions_v1,

        "v22":
            versions_v22,
    },

    "upstream_exact":
        upstream,

    "minute_alignment":
        alignment,

    "haaland":
        haaland_rows,

    "costinha":
        costinha_rows,

    "gw4_top_ev": {
        "v1":
            gw4_v1,

        "v22":
            gw4_v22,
    },

    "largest_ev_changes":
        largest,

    "gates": {
        "simulator_identity":
            simulator_gate,

        "upstream_exact":
            upstream_gate,

        "projection_keys":
            projection_keys_gate,

        "minute_alignment":
            alignment_gate,

        "haaland_alignment":
            haaland_gate,

        "projections_changed":
            projections_changed,

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


print()
print(
    "=== CAPTAIN-068G-B-R2 TRUE V22 REPLAY ==="
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
    "production default changed:",
    "NO",
)


print()
print(
    "=== SIMULATORS ==="
)

print(
    "V1 :",
    versions_v1,
)

print(
    "V22:",
    versions_v22,
)


print()
print(
    "=== UPSTREAM EXACT ==="
)

for filename, status in upstream.items():

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
    alignment[
        "rows"
    ],
)

print(
    "V1 MAE :",
    f"{alignment['v1_mae']:.3f}",
)

print(
    "V22 MAE:",
    f"{alignment['v22_mae']:.3f}",
)

print(
    "high-pStart rows:",
    alignment[
        "high_rows"
    ],
)

print(
    "V1 high-pStart MAE :",
    f"{alignment['v1_high_mae']:.3f}",
)

print(
    "V22 high-pStart MAE:",
    f"{alignment['v22_high_mae']:.3f}",
)


def print_player(
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

        points = ""

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

            points = (
                " | EV "
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
            f"{points}"
        )


print_player(
    "HAALAND",
    haaland_rows,
)

print_player(
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
        f"EV={row['points']:.3f} "
        f"min={row['minutes']:.1f}"
    )


print()
print(
    "=== TOP 10 GW4 EV / TRUE V22 ==="
)

for index, row in enumerate(
    gw4_v22,
    start=1,
):

    print(
        f"{index:2d}. "
        f"{row['name']:<24} "
        f"EV={row['points']:.3f} "
        f"min={row['minutes']:.1f}"
    )


print()
print(
    "=== TOP 12 EV CHANGES ==="
)

for row in largest[
    :12
]:

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

for name, value in report[
    "gates"
].items():

    print(
        f"{name:<28}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "TRUE V22 REPLAY GATE:",
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
        "CAPTAIN-068G-B-R2 "
        "true V22 replay gate failed."
    )
