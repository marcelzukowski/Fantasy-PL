from pathlib import Path
import inspect
import json

import pandas as pd

import fpl_engine.current as current
import fpl_engine.current_history as history


ROOT = Path(".").resolve()

BASE_RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "production_minutes_v2_smoke_seed42_20260912T202455Z"
    / "output"
    / "2026-27"
    / "20260912T100351Z"
)

STRICT = (
    ROOT
    / "data"
    / "interim"
    / "strict"
    / "2025-26"
)


def show_windows(
    path,
    terms,
    radius=7,
):

    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()

    hits = []

    for number, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            term in line
            for term in terms
        ):

            hits.append(
                number
            )

    shown = set()

    for hit in hits:

        start = max(
            1,
            hit - radius,
        )

        end = min(
            len(lines),
            hit + radius,
        )

        block = range(
            start,
            end + 1,
        )

        if all(
            number in shown
            for number in block
        ):
            continue

        print()
        print(
            f"--- {path} "
            f"L{start}-L{end} ---"
        )

        for number in block:

            if number in shown:
                continue

            shown.add(
                number
            )

            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )


print(
    "=== CAPTAIN-061 "
    "CANONICAL HISTORY IDENTITY AUDIT ==="
)

print()

print(
    "load_strict_historical_context:",
    inspect.signature(
        history
        .load_strict_historical_context
    ),
)


print()
print(
    "=== CURRENT_HISTORY IDENTITY PATH ==="
)

show_windows(
    ROOT
    / "src"
    / "fpl_engine"
    / "current_history.py",
    (
        "official_fpl_player_identity_key",
        "player_ids",
        'row["element"]',
        "provider_player",
        "IdentityResolutionError",
    ),
    radius=8,
)


print()
print(
    "=== CURRENT PIPELINE HISTORY CALL ==="
)

show_windows(
    ROOT
    / "src"
    / "fpl_engine"
    / "current.py",
    (
        "load_strict_historical_context",
        "historical.talent",
        "historical.minutes",
        "talent_history",
    ),
    radius=8,
)


print()
print(
    "=== STRICT 2025-26 FILES ==="
)

if STRICT.exists():

    for path in sorted(
        STRICT.rglob("*")
    ):

        if path.is_file():

            print(
                path.relative_to(
                    ROOT
                )
            )

else:

    print(
        "STRICT directory missing"
    )


print()
print(
    "=== STRICT MANIFEST IDENTITY KEYS ==="
)

manifest_path = (
    STRICT
    / "source_manifest.json"
)


def walk(
    value,
    prefix="",
):

    if isinstance(
        value,
        dict,
    ):

        for key, item in (
            value.items()
        ):

            next_prefix = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            lowered = (
                str(key)
                .casefold()
            )

            if any(
                token in lowered
                for token in (
                    "player",
                    "identity",
                    "vaastav",
                    "fplcache",
                    "snapshot",
                    "provider",
                )
            ):

                display = item

                if isinstance(
                    item,
                    (
                        dict,
                        list,
                    ),
                ):

                    display = (
                        f"<{type(item).__name__}>"
                    )

                print(
                    f"{next_prefix}: "
                    f"{display}"
                )

            walk(
                item,
                next_prefix,
            )

    elif isinstance(
        value,
        list,
    ):

        for index, item in enumerate(
            value
        ):

            walk(
                item,
                f"{prefix}[{index}]",
            )


if manifest_path.exists():

    walk(
        json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    )

else:

    print(
        "source_manifest.json missing"
    )


print()
print(
    "=== CURRENT CANONICAL PLAYER "
    "PROVIDER MAP ==="
)

provider_map = (
    BASE_RUN
    / "canonical_parquet"
    / "dim_player_provider_map.parquet"
)

if provider_map.exists():

    frame = pd.read_parquet(
        provider_map
    )

    print(
        "rows:",
        len(frame),
    )

    print(
        "columns:",
        ", ".join(
            map(
                str,
                frame.columns,
            )
        ),
    )

    interesting = [
        column
        for column in frame.columns
        if any(
            token
            in str(
                column
            ).casefold()
            for token in (
                "provider",
                "player",
                "season",
                "scope",
                "external",
            )
        )
    ]

    if interesting:

        print()
        print(
            frame[
                interesting
            ]
            .head(20)
            .to_string(
                index=False
            )
        )

    for column in frame.columns:

        lowered = str(
            column
        ).casefold()

        if any(
            token in lowered
            for token in (
                "provider",
                "season",
                "scope",
            )
        ):

            counts = (
                frame[column]
                .astype(str)
                .value_counts(
                    dropna=False
                )
                .head(20)
            )

            print()
            print(
                f"{column} counts:"
            )

            print(
                counts.to_string()
            )

else:

    print(
        "dim_player_provider_map "
        "not found"
    )


print()
print(
    "=== CURRENT PLAYERS ==="
)

players_path = (
    BASE_RUN
    / "current_players.json"
)

players = json.loads(
    players_path.read_text(
        encoding="utf-8"
    )
)

print(
    "current players:",
    len(players),
)

print(
    "sample:"
)

for row in players[:10]:

    print({
        key: row.get(key)
        for key in (
            "provider_id",
            "player_id",
            "display_name",
            "position",
            "team_id",
        )
        if key in row
    })


print()
print(
    "Audit only. "
    "No production files changed."
)
