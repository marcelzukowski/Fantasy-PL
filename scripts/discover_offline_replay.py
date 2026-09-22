from __future__ import annotations

import inspect
from pathlib import Path

import fpl_engine.current as current


ROOT = Path.cwd()


print()
print("============================================")
print("CURRENT API")
print("============================================")

for name in (
    "CurrentSourceRecord",
    "CurrentSourceData",
    "CurrentDataSource",
    "CurrentPipeline",
    "CurrentRunner",
    "CurrentConfig",
):

    obj = getattr(
        current,
        name,
        None,
    )

    if obj is None:
        continue

    print()
    print(name)

    try:
        print(
            "signature:",
            inspect.signature(obj),
        )
    except Exception:
        pass

    try:
        source = inspect.getsource(obj)

        print(
            source[:6000]
        )

    except Exception:
        pass


print()
print("============================================")
print("MATERIALIZED_SOURCE REFERENCES")
print("============================================")

tokens = (
    "materialized_source",
    "CurrentSourceData(",
    "CurrentSourceRecord(",
    "RawStore(",
    "raw_snapshot_id",
    "payload.bin",
)

for base in (
    ROOT / "src",
    ROOT / "scripts",
):

    if not base.exists():
        continue

    for path in base.rglob("*.py"):

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        lines = text.splitlines()

        hits = [
            i
            for i, line in enumerate(
                lines,
                start=1,
            )
            if any(
                token in line
                for token in tokens
            )
        ]

        if not hits:
            continue

        print()
        print(f"### {path}")

        ranges = []

        for n in hits:

            start = max(
                1,
                n - 7,
            )

            end = min(
                len(lines),
                n + 10,
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

        for start, end in ranges:

            print(
                f"--- L{start}-L{end} ---"
            )

            for n in range(
                start,
                end + 1,
            ):

                print(
                    f"{n:4}: "
                    f"{lines[n-1]}"
                )


print()
print("=== END ===")
