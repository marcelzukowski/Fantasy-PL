from __future__ import annotations

import json
from pathlib import Path


ROOT = Path.cwd()

RUN_ID = "20260912T100351Z"

RUN_PATH = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / RUN_ID
)

PROVENANCE = (
    RUN_PATH
    / "source_provenance.json"
)

FRESHNESS = (
    RUN_PATH
    / "source_freshness.json"
)

RAW_ROOT = (
    ROOT
    / "data"
    / "raw"
)


def flatten(
    value,
    prefix="",
    out=None,
):

    if out is None:
        out = {}

    if isinstance(value, dict):

        for key, child in value.items():

            path = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            flatten(
                child,
                path,
                out,
            )

    elif isinstance(value, list):

        for i, child in enumerate(
            value
        ):

            flatten(
                child,
                f"{prefix}[{i}]",
                out,
            )

    else:

        out[prefix] = value

    return out


print()
print(
    "============================================"
)
print(
    "RUN"
)
print(
    "============================================"
)

print(
    "run_id:",
    RUN_ID,
)

print(
    "provenance exists:",
    PROVENANCE.exists(),
)

print(
    "freshness exists:",
    FRESHNESS.exists(),
)


# ============================================================
# PROVENANCE
# ============================================================

provenance = json.loads(
    PROVENANCE.read_text(
        encoding="utf-8"
    )
)

flat = flatten(
    provenance
)

print()
print(
    "============================================"
)
print(
    "EVENT-LIVE PROVENANCE"
)
print(
    "============================================"
)


event_lines = []

for key, value in flat.items():

    text = (
        f"{key}={value}"
    )

    if (
        "event_live" in text.casefold()
        or "raw_snapshot" in key.casefold()
        or "snapshot_timestamp"
        in key.casefold()
    ):

        event_lines.append(
            text
        )


for line in event_lines:

    print(line)


# ============================================================
# COLLECT RAW SNAPSHOT IDS
# ============================================================

snapshot_ids = set()

for key, value in flat.items():

    if (
        "raw_snapshot_id"
        in key.casefold()
        and value
    ):

        snapshot_ids.add(
            str(value)
        )


print()
print(
    "============================================"
)
print(
    "RAW SNAPSHOT IDS"
)
print(
    "============================================"
)

for value in sorted(
    snapshot_ids
):

    print(value)


# ============================================================
# LOCATE RAW FILES
# ============================================================

print()
print(
    "============================================"
)
print(
    "RAW FILE MATCHES"
)
print(
    "============================================"
)


candidate_files = []

for path in RAW_ROOT.rglob("*"):

    if (
        not path.is_file()
        or path.suffix.lower()
        not in {
            ".json",
            ".jsonl",
            ".ndjson",
        }
    ):
        continue

    try:

        if path.stat().st_size > 20_000_000:
            continue

        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    except Exception:

        continue

    matched = (
        any(
            snapshot_id in text
            for snapshot_id
            in snapshot_ids
        )
        or (
            "event_live" in text
            and RUN_ID[:8]
            in text
        )
    )

    if matched:

        candidate_files.append(
            path
        )


for path in candidate_files[:50]:

    print(path)


print()
print(
    "candidate files:",
    len(
        candidate_files
    ),
)


# ============================================================
# INSPECT FILES FOR EVENT-LIVE + expected_goals
# ============================================================

print()
print(
    "============================================"
)
print(
    "EVENT-LIVE EXPECTED_GOALS CHECK"
)
print(
    "============================================"
)


for path in candidate_files:

    try:

        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    except Exception:

        continue

    low = text.casefold()

    if "event_live" not in low:
        continue

    has_xg = (
        '"expected_goals"'
        in text
    )

    count_xg = (
        text.count(
            '"expected_goals"'
        )
    )

    print()
    print(
        path
    )

    print(
        "  expected_goals field:",
        has_xg,
    )

    print(
        "  occurrences:",
        count_xg,
    )

    # Small context around first occurrence.
    if has_xg:

        index = text.find(
            '"expected_goals"'
        )

        start = max(
            0,
            index - 180,
        )

        end = min(
            len(text),
            index + 300,
        )

        print(
            "  sample:"
        )

        print(
            "  ",
            text[
                start:end
            ].replace(
                "\n",
                " ",
            )[:480]
        )


print()
print(
    "=== END ==="
)
