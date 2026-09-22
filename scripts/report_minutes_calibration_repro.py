import hashlib
import json
from pathlib import Path

from fpl_engine.models.minutes.calibration import (
    load_minutes_calibration,
)


ROOT = Path.cwd()

paths = {
    "FROZEN_V1": (
        ROOT
        / "data"
        / "processed"
        / "models"
        / "minutes"
        / "minutes_calibration_2025-26.json"
    ),
    "REPRO_V1": (
        ROOT
        / "scratch"
        / "decision"
        / "minutes_calibration_repro_v1_2025-26.json"
    ),
    "V2.1": (
        ROOT
        / "scratch"
        / "decision"
        / "minutes_calibration_v21_2025-26.json"
    ),
}


print()
print(
    "============================================================"
)
print(
    "MINUTES CALIBRATION REPRODUCTION"
)
print(
    "============================================================"
)


for name, path in paths.items():

    artifact = (
        load_minutes_calibration(
            path
        )
    )

    digest = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    print()
    print(
        f"[{name}]"
    )

    print(
        f"sha256={digest}"
    )

    print(
        "trained_through="
        f"{artifact.trained_through.isoformat()}"
    )

    for field in (
        "appearance",
        "start",
        "sixty_plus",
        "seventy_five_plus",
        "ninety",
    ):

        item = getattr(
            artifact,
            field,
        )

        print(
            f"{field:<20}"
            f"x={tuple(round(v, 6) for v in item.x)} "
            f"y={tuple(round(v, 6) for v in item.y)}"
        )


frozen = paths[
    "FROZEN_V1"
].read_bytes()

repro = paths[
    "REPRO_V1"
].read_bytes()

v21_artifact = (
    load_minutes_calibration(
        paths["V2.1"]
    )
)

print()
print(
    "============================================================"
)

print(
    "V1_BYTE_EXACT="
    f"{frozen == repro}"
)

print(
    "V21_PRE_DEADLINE_SAFE="
    f"{v21_artifact.trained_through.isoformat()}"
)

print(
    "============================================================"
)
