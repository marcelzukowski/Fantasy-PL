from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sys


ROOT = Path(".").resolve()

BASELINES = {
    42: (
        ROOT
        / "scratch/decision/"
        "production_minutes_v2_smoke_seed42_20260912T202455Z/"
        "output/2026-27/20260912T100351Z"
    ),
    202627: (
        ROOT
        / "scratch/decision/"
        "minutes_v21_fair_seed202627_20260912T200528Z/"
        "output/2026-27/20260912T100611Z"
    ),
    606: (
        ROOT
        / "scratch/decision/"
        "minutes_v21_fair_seed606_20260912T200646Z/"
        "output/2026-27/20260912T100827Z"
    ),
    91991: (
        ROOT
        / "scratch/decision/"
        "minutes_v21_fair_seed91991_20260912T200803Z/"
        "output/2026-27/20260912T101044Z"
    ),
}


UPSTREAM = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
)


def digest(path: Path) -> str:

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


status = True
fingerprints = {}


print(
    "=== CAPTAIN-063R BASELINE PREFLIGHT ==="
)


for seed, path in BASELINES.items():

    print()
    print(
        f"seed={seed}"
    )

    print(
        "path:",
        path.relative_to(
            ROOT
        ),
    )


    required = (
        "run_manifest.json",
        "prediction_context.json",
        "event_projections.json",
        "player_projections.json",
        "canonical_parquet/fact_fpl_snapshot.parquet",
        *UPSTREAM,
    )


    missing = [
        name
        for name in required
        if not (
            path / name
        ).exists()
    ]


    if missing:

        status = False

        print(
            "  required: FAIL"
        )

        for name in missing:

            print(
                "   missing:",
                name,
            )

        continue


    print(
        "  required: PASS"
    )


    manifest = json.loads(
        (
            path
            / "run_manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )


    actual_seed = int(
        manifest[
            "simulation"
        ][
            "base_seed"
        ]
    )


    seed_ok = (
        actual_seed
        == seed
    )

    print(
        "  manifest seed:",
        (
            "PASS"
            if seed_ok
            else (
                f"FAIL actual="
                f"{actual_seed}"
            )
        ),
    )

    status = (
        status
        and seed_ok
    )


    events = json.loads(
        (
            path
            / "event_projections.json"
        ).read_text(
            encoding="utf-8"
        )
    )


    versions = sorted(
        {
            str(
                row.get(
                    "model_version"
                )
            )
            for row in events
        }
    )


    event_ok = (
        versions
        == [
            "event_models_v1"
        ]
    )


    print(
        "  Event V1:",
        (
            "PASS"
            if event_ok
            else (
                "FAIL "
                + repr(
                    versions
                )
            )
        ),
    )

    status = (
        status
        and event_ok
    )


    fingerprints[
        seed
    ] = {
        name: digest(
            path / name
        )
        for name in UPSTREAM
    }


print()
print(
    "=== CROSS-SEED UPSTREAM HASHES ==="
)


reference_seed = 42

reference = fingerprints.get(
    reference_seed
)


if reference is None:

    status = False

    print(
        "Reference seed 42 unavailable."
    )

else:

    for name in UPSTREAM:

        values = {
            seed:
                hashes[
                    name
                ]
            for seed, hashes
            in fingerprints.items()
        }

        unique = set(
            values.values()
        )

        same = (
            len(unique) == 1
            and len(values)
            == len(BASELINES)
        )

        print(
            f"{name:<28} "
            f"{'PASS' if same else 'FAIL'}"
        )

        if not same:

            status = False

            for seed, value in sorted(
                values.items()
            ):

                print(
                    f"  {seed}: "
                    f"{value}"
                )


print()
print(
    "PREFLIGHT:",
    (
        "PASS"
        if status
        else "FAIL"
    ),
)


sys.exit(
    0
    if status
    else 1
)
