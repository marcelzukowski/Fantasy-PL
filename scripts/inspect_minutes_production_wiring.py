from pathlib import Path

path = Path(
    "src/fpl_engine/current.py"
)

lines = path.read_text(
    encoding="utf-8"
).splitlines()


patterns = (
    "def _active_model_stack",
    "_active_model_stack(",
    "champion_manifest =",
    'champion_manifest["active"]',
    "baseline_manifest",
)


hits = []

for number, line in enumerate(
    lines,
    start=1,
):

    if any(
        pattern in line
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
        hit + 10,
    )

    if (
        ranges
        and start <= ranges[-1][1] + 1
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
