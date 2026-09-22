from pathlib import Path
from io import BytesIO
import json

import pandas as pd

from fpl_engine.current_history import _receipts
from fpl_engine.data.raw_store import RawStore


ROOT = Path(".").resolve()

SEASONS = (
    "2023-24",
    "2024-25",
    "2025-26",
)

raw = RawStore(
    ROOT / "data" / "raw"
)

receipts = _receipts(
    raw.root
)


def strings(value):

    if isinstance(value, dict):

        for item in value.values():
            yield from strings(item)

    elif isinstance(value, list):

        for item in value:
            yield from strings(item)

    elif isinstance(value, str):

        yield value


def load_vaastav(season):

    manifest_path = (
        ROOT
        / "data"
        / "interim"
        / "strict"
        / season
        / "source_manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    candidates = []

    for value in strings(manifest):

        receipt = receipts.get(value)

        if receipt is None:
            continue

        try:

            frame = pd.read_csv(
                BytesIO(
                    raw.read_bytes(
                        receipt
                    )
                )
            )

        except Exception:
            continue

        if {
            "element",
            "fixture",
            "expected_goals",
        }.issubset(
            frame.columns
        ):
            candidates.append(frame)


    if not candidates:

        raise RuntimeError(
            f"{season}: "
            f"Vaastav frame not found"
        )

    candidates.sort(
        key=len,
        reverse=True,
    )

    return candidates[0]


print(
    "=== CAPTAIN-056 "
    "PENALTY DATA AUDIT ==="
)


for season in SEASONS:

    frame = load_vaastav(
        season
    )

    columns = [
        str(column)
        for column in frame.columns
        if any(
            token in str(
                column
            ).casefold()
            for token in (
                "pen",
                "xg",
                "goal",
            )
        )
    ]


    print()
    print(
        "=" * 72
    )

    print(season)

    print(
        "=" * 72
    )

    print(
        "columns:",
        ", ".join(columns)
    )


    for column in columns:

        series = frame[column]

        non_null = int(
            series.notna().sum()
        )

        unique = int(
            series.dropna()
            .nunique()
        )

        print(
            f"{column:<30} "
            f"non_null={non_null:<6} "
            f"unique={unique}"
        )


    haaland = frame[
        frame.get(
            "name",
            pd.Series(
                "",
                index=frame.index,
            )
        )
        .astype(str)
        .str.contains(
            "Haaland",
            case=False,
            na=False,
        )
    ]


    if not haaland.empty:

        print()
        print(
            "Haaland penalty/xG totals:"
        )

        for column in columns:

            numeric = pd.to_numeric(
                haaland[column],
                errors="coerce",
            )

            if numeric.notna().any():

                print(
                    f"  {column:<28} "
                    f"sum={numeric.sum():.3f} "
                    f"max={numeric.max():.3f}"
                )


print()
print(
    "=== CODE PENALTY REFERENCES ==="
)


terms = (
    "SetPieceType.PENALTIES",
    "penalty_role",
    "penalty_award_probability",
    "penalty_conversion_probability",
    "penalties_order",
    "penalty_taker",
)


for path in sorted(
    Path("src/fpl_engine").rglob("*.py")
):

    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()

    hits = []

    for index, line in enumerate(
        lines,
        start=1,
    ):

        if any(
            term in line
            for term in terms
        ):
            hits.append(index)


    if not hits:
        continue


    print()
    print(path)

    shown = set()

    for hit in hits:

        start = max(
            1,
            hit - 4,
        )

        end = min(
            len(lines),
            hit + 6,
        )

        for number in range(
            start,
            end + 1,
        ):

            if number in shown:
                continue

            shown.add(number)

            print(
                f"{number:4}: "
                f"{lines[number - 1]}"
            )
