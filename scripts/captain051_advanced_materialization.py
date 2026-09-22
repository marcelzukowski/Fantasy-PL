from pathlib import Path


FILES = (
    Path(
        "src/fpl_engine/features/"
        "advanced_event_data.py"
    ),
    Path(
        "scripts/"
        "build_advanced_development_report.py"
    ),
)


TERMS = (
    "def development_feature_matrix",
    "TemporalEventRecord(",
    "AvailabilityMatrix",
    "availability",
    "provider",
    "processed",
    "interim",
    "manifest",
)


for path in FILES:

    print()
    print("=" * 80)
    print(path)
    print("=" * 80)

    lines = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()

    hits = []

    for i, line in enumerate(
        lines,
        start=1,
    ):
        if any(
            term in line
            for term in TERMS
        ):
            hits.append(i)

    shown = set()

    for hit in hits:

        start = max(
            1,
            hit - 10,
        )

        end = min(
            len(lines),
            hit + 20,
        )

        for n in range(
            start,
            end + 1,
        ):

            if n in shown:
                continue

            shown.add(n)

            print(
                f"{n:4}: "
                f"{lines[n - 1]}"
            )


print()
print(
    "=== ADVANCED ARTIFACTS ==="
)

roots = (
    Path("data/processed/advanced"),
    Path("data/interim/advanced"),
    Path("data/interim/strict"),
)

for root in roots:

    print()
    print(root)

    if not root.exists():

        print("  MISSING")
        continue

    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
    ]

    print(
        "  files:",
        len(files),
    )

    for path in files[:40]:

        print(
            " ",
            path.relative_to(
                Path(".")
            )
        )

    if len(files) > 40:

        print(
            f"  ... +{len(files) - 40}"
        )
