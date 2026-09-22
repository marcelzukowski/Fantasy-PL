from pathlib import Path

import hashlib

import fpl_engine.current as current


root = Path.cwd()

manifest = (
    current._load_active_model_manifest(
        root,
        "2026/27",
    )
)

stack = (
    current._runtime_model_stack(
        manifest
    )
)

version = (
    manifest["active"]["minutes"]
)

calibration = (
    current._minutes_calibration_path(
        root,
        "2025-26",
        version,
    )
)


print(
    "minutes="
    f"{version}"
)

print(
    "runtime="
    f"{type(stack[1]).__name__}"
)

print(
    "calibration="
    f"{calibration}"
)

print(
    "calibration_sha="
    + hashlib.sha256(
        calibration.read_bytes()
    ).hexdigest()
)
