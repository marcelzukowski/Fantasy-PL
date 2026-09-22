from pathlib import Path

path = Path(
    "scripts/export_minutes_calibration.py"
)

lines = path.read_text(
    encoding="utf-8",
    errors="replace",
).splitlines()

patterns = (
    "MinutesModel",
    "MinutesContext",
    "MinutesCalibrationPoint",
    "fit_minutes_calibration",
    "save_minutes_calibration",
    "calibration_points",
    "season",
    "cutoff",
    "prediction_timestamp",
    "history",
    "argparse",
    "ArgumentParser",
    "add_argument",
)

hits = []

for number, line in enumerate(
    lines,
    start=1,
):

    if any(
        pattern.casefold()
        in line.casefold()
        for pattern in patterns
    ):
        hits.append(
            number
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


# Keep output compact.
print(
    f"path={path}"
)
print(
    f"total_lines={len(lines)}"
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

print()
print(
    "=== END ==="
)
