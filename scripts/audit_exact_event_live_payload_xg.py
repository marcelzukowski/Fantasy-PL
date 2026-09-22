from __future__ import annotations

import gzip
import json
from pathlib import Path


ROOT = Path.cwd()

BASE = (
    ROOT
    / "data"
    / "raw"
    / "official_fpl_api"
    / "event_live"
    / "2026-09-12"
)

SNAPSHOTS = {
    1: "a0b4cb27e9232592d83d9b60866812ae90fbcf7c2af54c072e62308907ebb360",
    2: "e3a1a0515cdcda2252045cad6f2e6f0071e2e69dac30c06e2e872a67e9ba927a",
    3: "6ffbb3a538496b38cea1e43ba1aacd8f892f69710fb413018fa7936422507a65",
}


def decode_file(path: Path):

    raw = path.read_bytes()

    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return None

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_elements(value):

    found = []

    if isinstance(value, dict):

        elements = value.get("elements")

        if isinstance(elements, list):
            found.append(elements)

        for child in value.values():
            found.extend(
                find_elements(child)
            )

    elif isinstance(value, list):

        for child in value:
            found.extend(
                find_elements(child)
            )

    return found


print()
print(
    "============================================"
)
print(
    "PRE-DEADLINE EVENT-LIVE PAYLOADS"
)
print(
    "============================================"
)


for gw, snapshot_id in SNAPSHOTS.items():

    directory = (
        BASE
        / snapshot_id
    )

    print()
    print(
        "--------------------------------------------"
    )
    print(
        f"GW{gw}"
    )
    print(
        "--------------------------------------------"
    )

    print(
        "directory:",
        directory,
    )

    print(
        "exists:",
        directory.exists(),
    )

    if not directory.exists():
        continue

    files = [
        path
        for path in directory.rglob("*")
        if path.is_file()
    ]

    print(
        "files:",
        len(files),
    )

    for path in files:

        rel = path.relative_to(
            directory
        )

        print(
            f"  {rel} "
            f"({path.stat().st_size} bytes)"
        )

    payload_candidates = []

    for path in files:

        text = decode_file(
            path
        )

        if text is None:
            continue

        count = text.count(
            '"expected_goals"'
        )

        has_elements = (
            '"elements"'
            in text
        )

        if (
            count > 0
            or has_elements
        ):

            payload_candidates.append(
                (
                    path,
                    text,
                    count,
                    has_elements,
                )
            )

    print()
    print(
        "payload candidates:",
        len(payload_candidates),
    )

    for (
        path,
        text,
        xg_count,
        has_elements,
    ) in payload_candidates:

        print()
        print(
            "FILE:",
            path.name,
        )

        print(
            "  expected_goals occurrences:",
            xg_count,
        )

        print(
            "  contains elements:",
            has_elements,
        )

        try:

            raw = json.loads(
                text
            )

        except Exception as exc:

            print(
                "  JSON parse:",
                type(exc).__name__,
            )

            continue

        element_sets = find_elements(
            raw
        )

        print(
            "  element sets:",
            len(element_sets),
        )

        if not element_sets:
            continue

        # Usually exactly one event-live elements list.
        elements = max(
            element_sets,
            key=len,
        )

        stats_rows = []

        for item in elements:

            if not isinstance(
                item,
                dict,
            ):
                continue

            stats = item.get(
                "stats"
            )

            if isinstance(
                stats,
                dict,
            ):

                stats_rows.append(
                    stats
                )

        with_field = [
            stats
            for stats in stats_rows
            if "expected_goals"
            in stats
        ]

        non_null = [
            stats.get(
                "expected_goals"
            )
            for stats in with_field
            if stats.get(
                "expected_goals"
            ) is not None
        ]

        print(
            "  players with stats:",
            len(stats_rows),
        )

        print(
            "  stats with expected_goals:",
            len(with_field),
        )

        print(
            "  non-null expected_goals:",
            len(non_null),
        )

        print(
            "  sample values:",
            non_null[:10],
        )


print()
print(
    "=== END ==="
)
