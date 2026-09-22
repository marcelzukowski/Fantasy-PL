from __future__ import annotations

from pathlib import Path

import yaml


src = Path(
    "config/v1_champions.yaml"
)

dst = Path(
    "config/v2_champions.yaml"
)


payload = yaml.safe_load(
    src.read_text(
        encoding="utf-8"
    )
)


if not isinstance(
    payload,
    dict,
):
    raise RuntimeError(
        "v1_champions.yaml is not a mapping"
    )


active = payload.get(
    "active"
)

if not isinstance(
    active,
    dict,
):
    raise RuntimeError(
        "manifest.active is missing"
    )


current = active.get(
    "minutes"
)

if (
    current
    != "minutes_hurdle_v1"
):
    raise RuntimeError(
        "Expected V1 Minutes in source "
        f"manifest, got: {current!r}"
    )


active["minutes"] = (
    "minutes_hurdle_v2"
)


dst.write_text(
    yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
    ),
    encoding="utf-8",
)


# Verify the written file through YAML again.
roundtrip = yaml.safe_load(
    dst.read_text(
        encoding="utf-8"
    )
)

assert (
    roundtrip["active"]["minutes"]
    == "minutes_hurdle_v2"
)

assert (
    roundtrip["season"]
    == payload["season"]
)


print(
    f"created {dst}"
)

print(
    "season="
    f"{roundtrip['season']}"
)

print(
    "minutes="
    f"{roundtrip['active']['minutes']}"
)
