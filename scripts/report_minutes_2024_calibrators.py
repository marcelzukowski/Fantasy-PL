from pathlib import Path
import hashlib

from fpl_engine.models.minutes.calibration import (
    load_minutes_calibration,
)


ROOT = Path.cwd()

paths = {
    "V1_FROZEN_2024-25": (
        ROOT
        / "data"
        / "processed"
        / "models"
        / "minutes"
        / "minutes_calibration_2024-25.json"
    ),

    "V1_REPRO_2024-25": (
        ROOT
        / "scratch"
        / "decision"
        / "minutes_calibration_repro_v1_2024-25.json"
    ),

    "V21_2024-25": (
        ROOT
        / "scratch"
        / "decision"
        / "minutes_calibration_v21_2024-25.json"
    ),
}


print()
print(
    "============================================================"
)
print(
    "PRIOR-SEASON CALIBRATORS FOR 2025-26 HOLDOUT"
)
print(
    "============================================================"
)


for name, path in paths.items():

    artifact = load_minutes_calibration(
        path
    )

    digest = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    print()
    print(
        f"{name}"
    )

    print(
        f"  sha256="
        f"{digest}"
    )

    print(
        f"  trained_through="
        f"{artifact.trained_through.isoformat()}"
    )

    print(
        "  appearance="
        f"{tuple(round(x,6) for x in artifact.appearance.x)} "
        f"{tuple(round(y,6) for y in artifact.appearance.y)}"
    )

    print(
        "  start="
        f"{tuple(round(x,6) for x in artifact.start.x)} "
        f"{tuple(round(y,6) for y in artifact.start.y)}"
    )


print()
print(
    "V1_BYTE_EXACT="
    + str(
        paths[
            "V1_FROZEN_2024-25"
        ].read_bytes()
        ==
        paths[
            "V1_REPRO_2024-25"
        ].read_bytes()
    )
)

print()
print(
    "=== END ==="
)
