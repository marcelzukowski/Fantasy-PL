from __future__ import annotations

from pathlib import Path
import ast


ROOT = Path(".").resolve()

SOURCE = (
    ROOT
    / "scripts"
    / "run_strict_model_backtest_sim_v21_512.py"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068f"
    / "harness_probe.log"
)


if not SOURCE.exists():
    raise RuntimeError(
        f"Missing historical harness: {SOURCE}"
    )


text = SOURCE.read_text(
    encoding="utf-8"
)

lines = text.splitlines()

tree = ast.parse(
    text,
    filename=str(SOURCE),
)


print(
    "=== CAPTAIN-068F-A "
    "HISTORICAL HARNESS PROBE ==="
)

print(
    "source:",
    SOURCE.relative_to(ROOT),
)

print(
    "lines:",
    len(lines),
)


print()
print(
    "=== FUNCTIONS ==="
)


for node in ast.walk(tree):

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):

        if (
            node.name
            in {
                "run",
                "main",
                "_minutes_score",
            }
            or "snapshot"
            in node.name.lower()
            or "history"
            in node.name.lower()
        ):

            print(
                f"{node.lineno:04d}: "
                f"{node.name}"
            )


print()
print(
    "=== IMPORT CHECK ==="
)


for token in (
    "HurdleTimeDecayMinutesModel",
    "MinutesModel",
    "fit_minutes_calibration",
):

    print(
        f"{token}:",
        (
            "YES"
            if token in text
            else "NO"
        ),
    )


MARKERS = (
    "current_states =",
    "element_by_team",
    "eligible_calibration",
    "calibration =",
    "for state in current_states.itertuples()",
    "fixture_key =",
    "is_current =",
    "canonical_team",
    "position =",
    "actual_minutes =",
    "raw_minutes =",
    "calibrated_minutes =",
    "minute_model.predict",
    "minutes_scores[",
    "calibration_points.append",
    "player_inputs[side].append",
)


matches = []


for number, line in enumerate(
    lines,
    start=1,
):

    for marker in MARKERS:

        if marker in line:

            matches.append(
                (
                    number,
                    marker,
                )
            )


print()
print(
    "=== MARKER INDEX ==="
)


for number, marker in matches:

    print(
        f"{number:04d}: {marker}"
    )


#
# Merge nearby source windows so output stays readable.
#
ranges = []


for number, _ in matches:

    lo = max(
        1,
        number - 8,
    )

    hi = min(
        len(lines),
        number + 10,
    )


    if (
        ranges
        and lo
        <= ranges[-1][1] + 3
    ):

        ranges[-1] = (
            ranges[-1][0],
            max(
                ranges[-1][1],
                hi,
            ),
        )

    else:

        ranges.append(
            (
                lo,
                hi,
            )
        )


print()
print(
    "=== RELEVANT SOURCE WINDOWS ==="
)


for lo, hi in ranges:

    print()
    print(
        f"--- L{lo}-L{hi} ---"
    )

    for number in range(
        lo,
        hi + 1,
    ):

        print(
            f"{number:04d}: "
            f"{lines[number - 1]}"
        )


#
# Also inspect run() signature precisely.
#
run_nodes = [
    node
    for node in tree.body
    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    )
    and node.name == "run"
]


print()
print(
    "=== RUN SIGNATURE ==="
)


if len(run_nodes) == 1:

    node = run_nodes[0]

    args = [
        arg.arg
        for arg in node.args.args
    ]

    kwonly = [
        arg.arg
        for arg in node.args.kwonlyargs
    ]

    print(
        "args:",
        args,
    )

    print(
        "kwonly:",
        kwonly,
    )

    print(
        "start line:",
        node.lineno,
    )

    print(
        "end line:",
        node.end_lineno,
    )

else:

    print(
        "run definitions:",
        len(run_nodes),
    )


print()
print(
    "=== PROBE GATE ==="
)


required = {
    "current_states =",
    "element_by_team",
    "eligible_calibration",
    "raw_minutes =",
    "calibrated_minutes =",
    "actual_minutes =",
}


found = {
    marker
    for _, marker in matches
}


missing = sorted(
    required
    - found
)


gate = (
    not missing
    and len(run_nodes) == 1
)


print(
    "required markers:",
    (
        "PASS"
        if not missing
        else "FAIL"
    ),
)

if missing:

    print(
        "missing:",
        missing,
    )


print(
    "single run():",
    (
        "PASS"
        if len(run_nodes) == 1
        else "FAIL"
    ),
)

print(
    "HARNESS PROBE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)


if not gate:
    raise RuntimeError(
        "CAPTAIN-068F-A harness "
        "probe failed."
    )
