from __future__ import annotations

import json
import re
from pathlib import Path

import fpl_engine.current as current_module


ROOT = Path.cwd()

CURRENT_PATH = Path(
    current_module.__file__
)

source = CURRENT_PATH.read_text(
    encoding="utf-8"
)

lines = source.splitlines()


# ============================================================
# 1. SOURCE SNIPPETS
# ============================================================

TOKENS = (
    "MinutesModel(",
    "minutes_model",
    "minutes_calibration",
    "load_minutes_calibration",
    "calibration=",
    "fit_minutes_calibration",
)

hits = []

for index, line in enumerate(
    lines,
    start=1,
):

    if any(
        token.casefold()
        in line.casefold()
        for token in TOKENS
    ):

        hits.append(
            index
        )


ranges = []

for hit in hits:

    start = max(
        1,
        hit - 5,
    )

    end = min(
        len(lines),
        hit + 8,
    )

    if (
        ranges
        and start
        <= ranges[-1][1] + 1
    ):

        ranges[-1] = (
            ranges[-1][0],
            max(
                ranges[-1][1],
                end,
            ),
        )

    else:

        ranges.append(
            (
                start,
                end,
            )
        )


print()
print(
    "============================================"
)
print(
    "CURRENT.PY | MINUTES / CALIBRATION"
)
print(
    "============================================"
)

print(
    f"path={CURRENT_PATH}"
)

for start, end in ranges:

    print()
    print(
        f"--- L{start}-L{end} ---"
    )

    for number in range(
        start,
        end + 1,
    ):

        print(
            f"{number:4}: "
            f"{lines[number - 1]}"
        )


# ============================================================
# Helpers
# ============================================================

def fixed_path(
    report,
):

    text = Path(
        report
    ).read_text(
        encoding="utf-8"
    )

    match = re.search(
        r"^FIXED\s*:\s*(.+)$",
        text,
        flags=re.MULTILINE,
    )

    if not match:

        raise RuntimeError(
            f"FIXED missing: {report}"
        )

    return Path(
        match.group(1).strip()
    )


def load_rows(
    path,
):

    raw = json.loads(
        path.read_text(
            encoding="utf-8"
        )
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
        f"rows unavailable: {path}"
    )


V1 = fixed_path(
    ROOT
    / "scratch"
    / "decision"
    / "captain_xg_ab_report_seed42.txt"
)

V21 = fixed_path(
    ROOT
    / "scratch"
    / "decision"
    / "minutes_v21_replay_report_seed42.txt"
)


# ============================================================
# 2. OUTPUT MODEL METADATA
# ============================================================

print()
print(
    "============================================"
)
print(
    "MINUTES ARTIFACT MODEL METADATA"
)
print(
    "============================================"
)


def player_id_by_name(
    run,
    name,
):

    players = load_rows(
        run
        / "current_players.json"
    )

    matches = [
        str(row["player_id"])
        for row in players
        if row.get(
            "display_name"
        ) == name
    ]

    if len(matches) != 1:

        raise RuntimeError(
            f"{name}: {matches}"
        )

    return matches[0]


def minutes_rows_for(
    run,
    pid,
):

    rows = load_rows(
        run
        / "minutes.json"
    )

    return [
        row
        for row in rows
        if str(
            row.get(
                "player_id"
            )
        ) == pid
    ]


for label, run in (
    (
        "V1",
        V1,
    ),
    (
        "V2.1",
        V21,
    ),
):

    pid = player_id_by_name(
        run,
        "Haaland",
    )

    rows = minutes_rows_for(
        run,
        pid,
    )

    if not rows:

        raise RuntimeError(
            f"{label}: no Haaland rows"
        )

    row = rows[0]

    print()
    print(
        f"[{label}]"
    )

    print(
        f"run={run}"
    )

    for key in (
        "model_version",
        "dataset_version",
        "feature_version",
        "p_appearance",
        "p_start",
        "expected_minutes",
        "prediction_confidence",
        "availability_confidence",
    ):

        if key in row:

            print(
                f"{key:<24} "
                f"{row[key]}"
            )

    print(
        "available metadata keys:"
    )

    print(
        "  "
        + ", ".join(
            sorted(
                key
                for key in row
                if (
                    "model" in key.casefold()
                    or "version" in key.casefold()
                    or "calib" in key.casefold()
                )
            )
        )
    )


# ============================================================
# 3. CALIBRATION FILES / ARTIFACTS AROUND RUN
# ============================================================

print()
print(
    "============================================"
)
print(
    "CALIBRATION-RELATED FILES"
)
print(
    "============================================"
)

roots = (
    ROOT / "data",
    ROOT / "scratch",
)

found = []

for root in roots:

    if not root.exists():
        continue

    for path in root.rglob(
        "*"
    ):

        if not path.is_file():
            continue

        name = (
            path.name.casefold()
        )

        if (
            "minute" in name
            and "calib" in name
        ):

            found.append(
                path
            )


# Keep terminal compact.
for path in found[-20:]:

    try:

        relative = path.relative_to(
            ROOT
        )

    except ValueError:

        relative = path

    print(
        relative
    )


print()
print(
    f"calibration_files_found="
    f"{len(found)}"
)


# ============================================================
# 4. ACTIVE MANIFEST / REFERENCES
# ============================================================

print()
print(
    "============================================"
)
print(
    "CALIBRATION REFERENCES IN JSON"
)
print(
    "============================================"
)

candidate_json = []

for base in (
    V1,
    V21,
):

    for path in base.glob(
        "*.json"
    ):

        if path.stat().st_size > (
            5 * 1024 * 1024
        ):
            continue

        candidate_json.append(
            path
        )


matches = []

for path in candidate_json:

    try:

        text = path.read_text(
            encoding="utf-8"
        )

    except Exception:

        continue

    if (
        "calibr" not in
        text.casefold()
    ):
        continue

    matches.append(
        path
    )


for path in matches:

    print(
        path
    )


print()
print(
    f"run_json_with_calibration="
    f"{len(matches)}"
)

print()
print(
    "=== END ==="
)
