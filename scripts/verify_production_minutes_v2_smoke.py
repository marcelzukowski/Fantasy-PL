from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path.cwd()

EXPECTED_CALIBRATION_SHA = (
    "363dc095df15e777178cf8f58c6976fad"
    "7012c870cce30245d119fec96c7f68b"
)


PRODUCTION_REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_report_seed42.txt"
)

FAIR_REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "minutes_v21_fair_report_seed42.txt"
)


def fixed_run(
    report: Path,
) -> Path:

    if not report.exists():
        raise RuntimeError(
            f"report missing: {report}"
        )

    text = report.read_text(
        encoding="utf-8"
    )

    match = re.search(
        r"^FIXED\s*:\s*(.+)$",
        text,
        flags=re.MULTILINE,
    )

    if not match:
        raise RuntimeError(
            f"FIXED path missing: "
            f"{report}"
        )

    path = Path(
        match.group(1).strip()
    )

    if not path.exists():
        raise RuntimeError(
            f"run directory missing: "
            f"{path}"
        )

    return path


def sha256(
    path: Path,
) -> str:

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def load_json(
    path: Path,
):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def rows(
    path: Path,
):

    raw = load_json(
        path
    )

    if isinstance(
        raw,
        list,
    ):
        return raw

    for key in (
        "rows",
        "data",
        "records",
        "minutes",
        "fixtures",
        "projections",
    ):

        value = raw.get(
            key
        )

        if isinstance(
            value,
            list,
        ):
            return value

    raise RuntimeError(
        f"Cannot resolve row list: "
        f"{path}"
    )


production = fixed_run(
    PRODUCTION_REPORT
)

fair = fixed_run(
    FAIR_REPORT
)


# ============================================================
# RUN MANIFEST
# ============================================================

manifest = load_json(
    production
    / "run_manifest.json"
)


active = manifest.get(
    "active_models"
)

if not isinstance(
    active,
    dict,
):
    raise RuntimeError(
        "run_manifest.active_models missing"
    )


minutes_version = active.get(
    "minutes"
)


artifact = (
    manifest
    .get(
        "model_artifacts",
        {},
    )
    .get(
        "minutes_calibration",
        {},
    )
)


artifact_model = artifact.get(
    "model_version"
)

artifact_sha = str(
    artifact.get(
        "sha256",
        "",
    )
).casefold()

artifact_path = str(
    artifact.get(
        "path",
        "",
    )
)


# ============================================================
# MINUTES ARTIFACT
# ============================================================

minute_rows = rows(
    production
    / "minutes.json"
)


versions = {
    str(
        row.get(
            "model_version"
        )
    )
    for row in minute_rows
}


# ============================================================
# FAIR vs PRODUCTION EQUALITY
# ============================================================

prod_minutes_sha = sha256(
    production
    / "minutes.json"
)

fair_minutes_sha = sha256(
    fair
    / "minutes.json"
)


prod_projection_sha = sha256(
    production
    / "player_projections.json"
)

fair_projection_sha = sha256(
    fair
    / "player_projections.json"
)


# ============================================================
# HAALAND GW4
# ============================================================

players = rows(
    production
    / "current_players.json"
)


haaland_matches = [
    row
    for row in players
    if row.get(
        "display_name"
    ) == "Haaland"
]


if len(
    haaland_matches
) != 1:

    raise RuntimeError(
        "Could not uniquely resolve Haaland"
    )


haaland_id = str(
    haaland_matches[0][
        "player_id"
    ]
)


fixtures = {
    str(
        row["fixture_id"]
    ): row
    for row in rows(
        production
        / "fixture_horizon.json"
    )
}


def fixture_gw(
    fixture,
):

    for key in (
        "target_gameweek",
        "gameweek",
        "event",
    ):

        value = fixture.get(
            key
        )

        if value is not None:
            return int(
                value
            )

    raise RuntimeError(
        "fixture gameweek missing"
    )


haaland_gw4 = []

for row in minute_rows:

    if str(
        row.get(
            "player_id"
        )
    ) != haaland_id:

        continue

    fixture = fixtures.get(
        str(
            row.get(
                "fixture_id"
            )
        )
    )

    if (
        fixture is not None
        and fixture_gw(
            fixture
        ) == 4
    ):

        haaland_gw4.append(
            row
        )


if len(
    haaland_gw4
) != 1:

    raise RuntimeError(
        "Expected exactly one "
        "Haaland GW4 minutes row"
    )


haaland = (
    haaland_gw4[0]
)


# ============================================================
# HARD ASSERTIONS
# ============================================================

checks = {
    "active_minutes_v2": (
        minutes_version
        == "minutes_hurdle_v2"
    ),

    "artifact_owned_by_v2": (
        artifact_model
        == "minutes_hurdle_v2"
    ),

    "artifact_sha_correct": (
        artifact_sha
        == EXPECTED_CALIBRATION_SHA
    ),

    "artifact_path_v21": (
        artifact_path.endswith(
            "minutes_calibration_v21_2025-26.json"
        )
    ),

    "all_minutes_rows_v2": (
        versions
        == {
            "minutes_hurdle_v2"
        }
    ),

    "minutes_exact_vs_fair": (
        prod_minutes_sha
        == fair_minutes_sha
    ),

    "projections_exact_vs_fair": (
        prod_projection_sha
        == fair_projection_sha
    ),
}


print()
print(
    "============================================================"
)
print(
    "CAPTAIN-034 | PRODUCTION MINUTES V2 SMOKE"
)
print(
    "============================================================"
)

print(
    f"production_run="
    f"{production}"
)

print()

print(
    f"active minutes       : "
    f"{minutes_version}"
)

print(
    f"artifact model       : "
    f"{artifact_model}"
)

print(
    f"artifact path        : "
    f"{artifact_path}"
)

print(
    f"artifact sha         : "
    f"{artifact_sha}"
)

print(
    f"minutes versions     : "
    f"{sorted(versions)}"
)


print()
print(
    "=== HAALAND GW4 ==="
)

print(
    "p_appearance         : "
    f"{float(haaland['p_appearance']):.6f}"
)

print(
    "p_start              : "
    f"{float(haaland['p_start']):.6f}"
)

print(
    "expected_minutes     : "
    f"{float(haaland['expected_minutes']):.6f}"
)


print()
print(
    "=== FAIR REPLAY EQUALITY ==="
)

print(
    f"minutes SHA prod     : "
    f"{prod_minutes_sha}"
)

print(
    f"minutes SHA fair     : "
    f"{fair_minutes_sha}"
)

print(
    f"projection SHA prod  : "
    f"{prod_projection_sha}"
)

print(
    f"projection SHA fair  : "
    f"{fair_projection_sha}"
)


print()
print(
    "=== CHECKS ==="
)

for name, passed in (
    checks.items()
):

    print(
        f"{name:<28} "
        f"{'PASS' if passed else 'FAIL'}"
    )


failed = [
    name
    for name, passed
    in checks.items()
    if not passed
]


print()
print(
    "============================================================"
)

if failed:

    print(
        "SMOKE RESULT: FAIL"
    )

    print(
        "failed="
        + ", ".join(
            failed
        )
    )

    raise RuntimeError(
        "Production Minutes V2 "
        "smoke validation failed"
    )

else:

    print(
        "SMOKE RESULT: PASS"
    )

print(
    "============================================================"
)
