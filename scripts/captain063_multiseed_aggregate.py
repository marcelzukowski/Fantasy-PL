from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import statistics


ROOT = Path(".").resolve()

MULTI = (
    ROOT
    / "scratch"
    / "decision"
    / "captain063_multiseed"
)

RUN_MAP = (
    MULTI
    / "run_map.json"
)

OUT = (
    MULTI
    / "stability_report.json"
)


raw_map = json.loads(
    RUN_MAP.read_text(
        encoding="utf-8-sig"
    )
)

if isinstance(
    raw_map,
    dict,
):
    raw_map = [
        raw_map
    ]


reports = []


for item in raw_map:

    if int(
        item["Status"]
    ) != 0:
        continue

    path = Path(
        item["Report"]
    )

    if not path.is_absolute():
        path = ROOT / path

    if not path.exists():
        continue

    report = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    reports.append(
        (
            int(
                item["Seed"]
            ),
            report,
        )
    )


if not reports:

    raise RuntimeError(
        "No successful CAPTAIN-063 reports"
    )


expected_seeds = {
    42,
    202627,
    606,
    91991,
}

seen_seeds = {
    seed
    for seed, _
    in reports
}


key_values = defaultdict(
    list
)

captain_counts = defaultdict(
    lambda: defaultdict(
        int
    )
)

vice_counts = defaultdict(
    lambda: defaultdict(
        int
    )
)

top5_counts = defaultdict(
    lambda: defaultdict(
        int
    )
)


upstream_pass = True
envelope_pass = True
network_pass = True


for seed, report in reports:

    upstream_pass = (
        upstream_pass
        and bool(
            report[
                "upstream_pass"
            ]
        )
    )

    envelope_pass = (
        envelope_pass
        and bool(
            report[
                "team_goal_envelope_exact"
            ]
        )
    )

    network_pass = (
        network_pass
        and not bool(
            report[
                "network_refresh"
            ]
        )
    )


    for row in report[
        "key_players"
    ]:

        key = (
            int(
                row[
                    "gameweek"
                ]
            ),
            str(
                row[
                    "label"
                ]
            ),
        )

        key_values[
            key
        ].append({
            "seed": seed,
            "baseline": float(
                row[
                    "baseline_ev"
                ]
            ),
            "challenger": float(
                row[
                    "challenger_ev"
                ]
            ),
            "delta": float(
                row[
                    "delta"
                ]
            ),
        })


    for gw, pair in report.get(
        "fixed_wc_captaincy",
        {}
    ).items():

        challenger = pair[
            "challenger"
        ]

        captain_counts[
            int(gw)
        ][
            challenger[
                "captain"
            ]
        ] += 1

        vice_counts[
            int(gw)
        ][
            challenger[
                "vice"
            ]
        ] += 1


    for gw, block in report[
        "top10"
    ].items():

        for row in block[
            "challenger"
        ][:5]:

            top5_counts[
                int(gw)
            ][
                row[
                    "name"
                ]
            ] += 1


summary_rows = []


for (
    gw,
    label,
), values in sorted(
    key_values.items()
):

    baseline = [
        row[
            "baseline"
        ]
        for row in values
    ]

    challenger = [
        row[
            "challenger"
        ]
        for row in values
    ]

    delta = [
        row[
            "delta"
        ]
        for row in values
    ]


    summary_rows.append({
        "gameweek": gw,
        "label": label,
        "runs": len(
            values
        ),
        "baseline_mean": (
            statistics.mean(
                baseline
            )
        ),
        "challenger_mean": (
            statistics.mean(
                challenger
            )
        ),
        "delta_mean": (
            statistics.mean(
                delta
            )
        ),
        "delta_min": min(
            delta
        ),
        "delta_max": max(
            delta
        ),
        "delta_positive_runs": sum(
            value > 0.0
            for value in delta
        ),
        "delta_negative_runs": sum(
            value < 0.0
            for value in delta
        ),
    })


output = {
    "status": (
        "DEVELOPMENT_ONLY_"
        "MULTISEED_STABILITY"
    ),
    "expected_seeds": sorted(
        expected_seeds
    ),
    "successful_seeds": sorted(
        seen_seeds
    ),
    "all_four_seeds": (
        seen_seeds
        == expected_seeds
    ),
    "upstream_all_pass": (
        upstream_pass
    ),
    "team_goal_envelope_all_pass": (
        envelope_pass
    ),
    "network_refresh_all_no": (
        network_pass
    ),
    "key_player_summary": (
        summary_rows
    ),
    "captain_counts": {
        str(gw): dict(
            sorted(
                values.items(),
                key=lambda item:
                    (
                        -item[1],
                        item[0],
                    ),
            )
        )
        for gw, values
        in sorted(
            captain_counts.items()
        )
    },
    "vice_counts": {
        str(gw): dict(
            sorted(
                values.items(),
                key=lambda item:
                    (
                        -item[1],
                        item[0],
                    ),
            )
        )
        for gw, values
        in sorted(
            vice_counts.items()
        )
    },
    "top5_counts": {
        str(gw): dict(
            sorted(
                values.items(),
                key=lambda item:
                    (
                        -item[1],
                        item[0],
                    ),
            )
        )
        for gw, values
        in sorted(
            top5_counts.items()
        )
    },
}


OUT.write_text(
    json.dumps(
        output,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-063 "
    "FOUR-SEED STABILITY ==="
)

print(
    "successful seeds:",
    sorted(
        seen_seeds
    ),
)

print(
    "all four:",
    (
        "PASS"
        if seen_seeds
        == expected_seeds
        else "FAIL"
    ),
)

print(
    "upstream:",
    (
        "PASS"
        if upstream_pass
        else "FAIL"
    ),
)

print(
    "team xG envelope:",
    (
        "PASS"
        if envelope_pass
        else "FAIL"
    ),
)

print(
    "network refresh:",
    (
        "NO"
        if network_pass
        else "FAIL"
    ),
)


print()
print(
    "=== KEY PLAYER MEAN DELTAS ==="
)


labels = (
    "Haaland",
    "Palmer",
    "B.Fernandes",
    "Tavernier",
)


for label in labels:

    rows = [
        row
        for row in summary_rows
        if row[
            "label"
        ] == label
    ]

    if not rows:
        continue

    all_deltas = []

    positive = 0
    total = 0

    for row in rows:

        values = key_values[
            (
                row[
                    "gameweek"
                ],
                label,
            )
        ]

        for value in values:

            all_deltas.append(
                value[
                    "delta"
                ]
            )

            positive += (
                value[
                    "delta"
                ]
                > 0.0
            )

            total += 1


    print(
        f"{label:<14} "
        f"mean_delta="
        f"{statistics.mean(all_deltas):+.3f} "
        f"range="
        f"[{min(all_deltas):+.3f}, "
        f"{max(all_deltas):+.3f}] "
        f"positive="
        f"{positive}/{total}"
    )


print()
print(
    "=== CHALLENGER C "
    "STABILITY ==="
)


for gw, values in sorted(
    captain_counts.items()
):

    rendered = " | ".join(
        f"{name}:{count}/"
        f"{len(reports)}"
        for name, count
        in sorted(
            values.items(),
            key=lambda item:
                (
                    -item[1],
                    item[0],
                ),
        )
    )

    print(
        f"GW{gw}: "
        f"{rendered}"
    )


print()
print(
    "report:",
    OUT.relative_to(
        ROOT
    ),
)
