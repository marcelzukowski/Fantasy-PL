from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

from fpl_engine.decision.chip_screen import (
    ExactChipScreenEntry,
)

from fpl_engine.decision.chip_timing import (
    ExactChipTimingConfig,
    ExactChipTimingPolicy,
    future_fixed_squad_chip_opportunities_exact,
)

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)

from fpl_engine.decision.policy_config import (
    load_exact_chip_timing_config,
)


ROOT = Path(".").resolve()

RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v22_real"
)

SCREEN_REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "decision007b"
    / "acceptance.json"
)

REFERENCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068h"
    / "decision_42.json"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "decision007c"
    / "acceptance.json"
)


def load(
    path,
):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


screen_payload = load(
    SCREEN_REPORT
)

reference = load(
    REFERENCE
)


if not screen_payload[
    "gates"
][
    "overall"
]:

    raise RuntimeError(
        "DECISION-007B source screen "
        "did not pass."
    )


if (
    reference[
        "v22_pappearance_adjustments"
    ][
        "saved_squad_rows"
    ]
    != 0
):

    raise RuntimeError(
        "Saved squad contains V22 "
        "appearance raises; raw minute "
        "pAppearance is not an exact bridge."
    )


projection_rows = load(
    RUN
    / "player_projections.json"
)


projections = {
    row.player_id:
        row
    for row
    in adapt_player_projections(
        projection_rows
    )
}


fixture_horizon = load(
    RUN
    / "fixture_horizon.json"
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
    for row
    in fixture_horizon
}


minutes = load(
    RUN
    / "minutes.json"
)


fixture_probabilities = {}


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


    key = (
        str(
            row[
                "player_id"
            ]
        ),
        gameweek,
    )


    fixture_probabilities.setdefault(
        key,
        [],
    ).append(
        float(
            row[
                "p_appearance"
            ]
        )
    )


papp = {}


for key, probabilities in (
    fixture_probabilities.items()
):

    no_appearance = 1.0


    for probability in probabilities:

        no_appearance *= (
            1.0
            - probability
        )


    papp[
        key
    ] = (
        1.0
        - no_appearance
    )


saved = (
    reference[
        "saved_wc_resolution"
    ]
)


current_ids = tuple(
    row[
        "player_id"
    ]
    for row
    in saved
)


positions = {
    row[
        "player_id"
    ]:
        row[
            "position"
        ]
    for row
    in saved
}


def rebuild_entry(
    chip,
):

    row = (
        screen_payload[
            "chips"
        ][
            chip
        ]
    )


    return ExactChipScreenEntry(
        chip=chip,

        baseline_ev=float(
            row[
                "baseline_ev"
            ]
        ),

        chip_ev=float(
            row[
                "chip_ev"
            ]
        ),

        incremental_ev=float(
            row[
                "incremental_ev"
            ]
        ),

        squad_player_ids=(
            frozenset(
                row[
                    "squad_player_ids"
                ]
            )
        ),

        captain_id=str(
            row[
                "captain_id"
            ]
        ),

        vice_id=str(
            row[
                "vice_id"
            ]
        ),

        formation=str(
            row[
                "formation"
            ]
        ),

        candidate_count=int(
            row[
                "candidate_count"
            ]
        ),
    )


screen = SimpleNamespace(
    triple_captain=(
        rebuild_entry(
            "triple_captain"
        )
    ),

    bench_boost=(
        rebuild_entry(
            "bench_boost"
        )
    ),

    free_hit=(
        rebuild_entry(
            "free_hit"
        )
    ),

    wildcard=(
        rebuild_entry(
            "wildcard"
        )
    ),
)


config = (
    load_exact_chip_timing_config(
        ROOT
    )
)


future = (
    future_fixed_squad_chip_opportunities_exact(
        squad_player_ids=(
            current_ids
        ),

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=4,

        evaluation_horizon_gameweeks=(
            config
            .evaluation_horizon_gameweeks
        ),
    )
)


policy = ExactChipTimingPolicy(
    config
)


decision = policy.decide(
    screen=screen,

    future_opportunities=(
        future
    ),

    available_chips=(
        "triple_captain",
        "bench_boost",
        "free_hit",
        "wildcard",
    ),
)


by_chip = {
    row.chip:
        row
    for row
    in decision.evaluations
}


expected_future_gameweeks = list(
    range(
        5,
        min(
            4
            + config
            .evaluation_horizon_gameweeks,
            10,
        ),
    )
)


formula_gate = True


for row in decision.evaluations:

    expected_threshold = (
        config
        .wildcard_minimum_weighted_gain

        if row.chip
        == "wildcard"

        else (
            config
            .free_hit_minimum_single_gameweek_gain

            if row.chip
            == "free_hit"

            else config
            .minimum_incremental_ev
        )
    )


    if abs(
        row.threshold
        - expected_threshold
    ) > 1e-12:

        formula_gate = False


    expected_clears = (
        row.incremental_ev
        >= row.threshold
    )


    if (
        row.clears_threshold
        != expected_clears
    ):

        formula_gate = False


    expected_competitive = (
        row.future_best_incremental_ev
        is None
        or row.incremental_ev
        >= (
            row.future_best_incremental_ev
            - config
            .future_opportunity_tolerance
        )
    )


    if (
        row.competitive_with_future
        != expected_competitive
    ):

        formula_gate = False


    expected_use = (
        row.available
        and expected_clears
        and expected_competitive
    )


    if (
        row.use_now
        != expected_use
    ):

        formula_gate = False


eligible = [
    row
    for row
    in decision.evaluations
    if row.use_now
]


expected_chosen = (
    max(
        eligible,
        key=lambda row: (
            row.incremental_ev,
            row.chip,
        ),
    ).chip

    if eligible
    else None
)


gates = {
    "source_007b_pass":
        (
            screen_payload[
                "gates"
            ][
                "overall"
            ]
            is True
        ),

    "future_tc_gameweeks":
        (
            [
                row.gameweek
                for row
                in future[
                    "triple_captain"
                ]
            ]
            == expected_future_gameweeks
        ),

    "future_bb_gameweeks":
        (
            [
                row.gameweek
                for row
                in future[
                    "bench_boost"
                ]
            ]
            == expected_future_gameweeks
        ),

    "fh_future_not_invented":
        (
            by_chip[
                "free_hit"
            ]
            .future_best_incremental_ev
            is None
        ),

    "wc_future_not_invented":
        (
            by_chip[
                "wildcard"
            ]
            .future_best_incremental_ev
            is None
        ),

    "threshold_and_future_formula":
        formula_gate,

    "chosen_chip_formula":
        (
            decision.chosen_chip
            == expected_chosen
        ),
}


gate = all(
    gates.values()
)


def serialize_opportunities(
    rows,
):

    return [
        {
            "gameweek":
                row.gameweek,

            "baseline_ev":
                row.baseline_ev,

            "chip_ev":
                row.chip_ev,

            "incremental_ev":
                row.incremental_ev,
        }
        for row
        in rows
    ]


payload = {
    "status":
        "DECISION_007C_EXACT_CHIP_TIMING",

    "network_refresh":
        False,

    "new_simulation":
        False,

    "realized_GW4_outcomes_used":
        False,

    "screen_source":
        (
            "DECISION-007B accepted "
            "offline snapshot"
        ),

    "policy_version":
        policy.VERSION,

    "config": {
        "evaluation_horizon_gameweeks":
            config
            .evaluation_horizon_gameweeks,

        "minimum_incremental_ev":
            config
            .minimum_incremental_ev,

        "future_opportunity_tolerance":
            config
            .future_opportunity_tolerance,

        "wildcard_minimum_weighted_gain":
            config
            .wildcard_minimum_weighted_gain,

        "free_hit_minimum_single_gameweek_gain":
            config
            .free_hit_minimum_single_gameweek_gain,
    },

    "future_opportunities": {
        "triple_captain":
            serialize_opportunities(
                future[
                    "triple_captain"
                ]
            ),

        "bench_boost":
            serialize_opportunities(
                future[
                    "bench_boost"
                ]
            ),
    },

    "evaluations": [
        {
            "chip":
                row.chip,

            "available":
                row.available,

            "incremental_ev":
                row.incremental_ev,

            "threshold":
                row.threshold,

            "future_best_incremental_ev":
                row
                .future_best_incremental_ev,

            "clears_threshold":
                row.clears_threshold,

            "competitive_with_future":
                row.competitive_with_future,

            "use_now":
                row.use_now,

            "reason":
                row.reason,
        }
        for row
        in decision.evaluations
    ],

    "chosen_chip":
        decision.chosen_chip,

    "gates": {
        **gates,
        "overall":
            gate,
    },
}


REPORT.write_text(
    json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== DECISION-007C EXACT CHIP TIMING ==="
)

print(
    "network refresh: NO"
)

print(
    "new simulation: NO"
)

print(
    "GW4 outcomes used: NO"
)


print()
print(
    "policy:",
    policy.VERSION,
)

print(
    "evaluation horizon:",
    config
    .evaluation_horizon_gameweeks,
)

print(
    "generic threshold:",
    config
    .minimum_incremental_ev,
)

print(
    "future tolerance:",
    config
    .future_opportunity_tolerance,
)

print(
    "FH threshold:",
    config
    .free_hit_minimum_single_gameweek_gain,
)

print(
    "WC threshold:",
    config
    .wildcard_minimum_weighted_gain,
)


print()
print(
    "=== FUTURE EXACT OPPORTUNITIES ==="
)


for chip in (
    "triple_captain",
    "bench_boost",
):

    print()
    print(
        chip
    )


    for row in future[
        chip
    ]:

        print(
            f"  GW{row.gameweek}: "
            f"{row.incremental_ev:+.3f}"
        )


print()
print(
    "=== TIMING EVALUATIONS ==="
)


for row in decision.evaluations:

    future_text = (
        "-"
        if row
        .future_best_incremental_ev
        is None
        else (
            f"{row.future_best_incremental_ev:+.3f}"
        )
    )


    print()
    print(
        row.chip
    )

    print(
        "  now delta :",
        f"{row.incremental_ev:+.3f}",
    )

    print(
        "  threshold :",
        f"{row.threshold:.3f}",
    )

    print(
        "  future max:",
        future_text,
    )

    print(
        "  available :",
        row.available,
    )

    print(
        "  threshold :",
        (
            "PASS"
            if row.clears_threshold
            else "FAIL"
        ),
    )

    print(
        "  competitive:",
        (
            "PASS"
            if row
            .competitive_with_future
            else "FAIL"
        ),
    )

    print(
        "  use now   :",
        row.use_now,
    )


print()
print(
    "chosen chip:",
    decision.chosen_chip,
)


print()
print(
    "=== GATES ==="
)


for name, value in payload[
    "gates"
].items():

    print(
        f"{name:<32}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "DECISION-007C GATE:",
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
        "DECISION-007C acceptance failed"
    )
