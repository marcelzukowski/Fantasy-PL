from __future__ import annotations

from pathlib import Path
import ast


ROOT = Path(".").resolve()

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "decision_api_probe.log"
)

SEARCH_ROOTS = (
    ROOT / "src" / "fpl_engine",
    ROOT / "scripts",
)

TOKENS = (
    "autosub",
    "auto_sub",
    "bench_order",
    "bench",
    "captain",
    "vice_captain",
    "vice",
)


print(
    "=== CAPTAIN-068G-C DECISION API PROBE ==="
)


candidates = []


for base in SEARCH_ROOTS:

    if not base.exists():
        continue

    for path in sorted(
        base.rglob("*.py")
    ):

        try:
            text = path.read_text(
                encoding="utf-8-sig"
            )
        except UnicodeDecodeError:
            continue

        lower = text.lower()

        score = sum(
            token in lower
            for token in TOKENS
        )

        if score:

            candidates.append(
                (
                    score,
                    path,
                    text,
                )
            )


#
# Prefer source modules, then scripts with the strongest
# autosub/captain relevance.
#
candidates.sort(
    key=lambda row: (
        -row[0],
        str(row[1]),
    )
)


for score, path, text in candidates[:35]:

    relative = path.relative_to(
        ROOT
    )

    print()
    print(
        "=" * 72
    )

    print(
        relative,
        f"[score={score}]",
    )

    print(
        "=" * 72
    )


    try:
        tree = ast.parse(
            text,
            filename=str(path),
        )
    except SyntaxError as exc:

        print(
            "AST parse failed:",
            exc,
        )

        continue


    interesting = []


    for node in ast.walk(
        tree
    ):

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):

            name = node.name.lower()

            if any(
                token in name
                for token in TOKENS
            ):

                interesting.append(
                    node
                )


    for node in sorted(
        interesting,
        key=lambda value:
            value.lineno,
    ):

        kind = (
            "class"
            if isinstance(
                node,
                ast.ClassDef,
            )
            else "def"
        )

        print(
            f"{node.lineno:04d}: "
            f"{kind} {node.name}"
        )


        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):

            args = [
                arg.arg
                for arg in (
                    node.args.posonlyargs
                    + node.args.args
                )
            ]

            kwonly = [
                arg.arg
                for arg in node.args.kwonlyargs
            ]

            print(
                "      args  :",
                args,
            )

            if kwonly:

                print(
                    "      kwonly:",
                    kwonly,
                )


    #
    # Print small source windows for the most useful terms.
    #
    lines = text.splitlines()

    hit_lines = []


    for number, line in enumerate(
        lines,
        start=1,
    ):

        normalized = line.lower()

        if (
            "autosub" in normalized
            or "bench_order" in normalized
            or "vice_captain" in normalized
            or (
                "captain" in normalized
                and (
                    "def " in normalized
                    or "class " in normalized
                )
            )
        ):

            hit_lines.append(
                number
            )


    shown = set()


    for number in hit_lines[:10]:

        lo = max(
            1,
            number - 4,
        )

        hi = min(
            len(lines),
            number + 10,
        )

        key = (
            lo,
            hi,
        )

        if key in shown:
            continue

        shown.add(
            key
        )

        print()
        print(
            f"--- L{lo}-L{hi} ---"
        )

        for current in range(
            lo,
            hi + 1,
        ):

            print(
                f"{current:04d}: "
                f"{lines[current - 1]}"
            )


print()
print(
    "=== PROBE COMPLETE ==="
)
