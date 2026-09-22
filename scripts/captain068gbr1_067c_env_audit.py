from pathlib import Path
import ast


path = Path(
    "scripts/captain067c_default_runtime_acceptance.py"
)

text = path.read_text(
    encoding="utf-8-sig"
)

tree = ast.parse(
    text,
    filename=str(path),
)


print(
    "=== CAPTAIN-068G-B-R1 067C ENV AUDIT ==="
)

print(
    "file:",
    path,
)


# ============================================================
# 1. Literal references
# ============================================================

terms = (
    "FPL_SIMULATOR_CHALLENGER",
    "simulator",
    "v1",
    "v2",
    "v21",
    "v22",
    "environ",
    "environment",
)


print()
print(
    "=== TEXT REFERENCES ==="
)


lines = text.splitlines()

hits = []


for number, line in enumerate(
    lines,
    start=1,
):

    lower = line.lower()

    if any(
        term.lower()
        in lower
        for term in terms
    ):

        hits.append(
            number
        )


for number in hits:

    lo = max(
        1,
        number - 2,
    )

    hi = min(
        len(lines),
        number + 2,
    )

    print()

    for current in range(
        lo,
        hi + 1,
    ):

        marker = (
            ">"
            if current == number
            else " "
        )

        print(
            f"{marker} {current:04d}: "
            f"{lines[current - 1]}"
        )


# ============================================================
# 2. AST calls / assignments involving environment
# ============================================================

print()
print(
    "=== AST ENV OPERATIONS ==="
)


env_nodes = []


for node in ast.walk(
    tree
):

    source = None

    try:

        source = ast.get_source_segment(
            text,
            node,
        )

    except Exception:

        source = None


    if not source:

        continue


    normalized = source.lower()


    if (
        "fpl_simulator_challenger"
        in normalized
        or "os.environ"
        in normalized
        or "environ["
        in normalized
        or "patch.dict"
        in normalized
        or "setdefault("
        in normalized
    ):

        if isinstance(
            node,
            (
                ast.Assign,
                ast.AnnAssign,
                ast.AugAssign,
                ast.Call,
                ast.With,
                ast.Delete,
            ),
        ):

            env_nodes.append((
                getattr(
                    node,
                    "lineno",
                    -1,
                ),
                type(
                    node
                ).__name__,
                source,
            ))


seen = set()


for line, kind, source in sorted(
    env_nodes,
    key=lambda row:
        row[
            0
        ],
):

    key = (
        line,
        kind,
        source,
    )

    if key in seen:

        continue

    seen.add(
        key
    )

    print()
    print(
        f"L{line} {kind}"
    )
    print(
        source
    )


# ============================================================
# 3. Search specifically for CurrentPredictionPipeline calls
# ============================================================

print()
print(
    "=== PIPELINE RUN CALLS ==="
)


for node in ast.walk(
    tree
):

    if not isinstance(
        node,
        ast.Call,
    ):

        continue


    source = ast.get_source_segment(
        text,
        node,
    )


    if not source:

        continue


    if (
        "CurrentPredictionPipeline"
        in source
        or ".run("
        in source
        and "materialized_source"
        in source
    ):

        print()
        print(
            f"L{node.lineno}"
        )
        print(
            source[:3000]
        )


# ============================================================
# 4. Imports that could replace / monkeypatch current.py
# ============================================================

print()
print(
    "=== PATCH / MONKEYPATCH REFERENCES ==="
)


patch_terms = (
    "patch",
    "monkeypatch",
    "FixtureSimulator",
    "current.",
)


patch_hits = []


for number, line in enumerate(
    lines,
    start=1,
):

    if any(
        term in line
        for term in patch_terms
    ):

        patch_hits.append(
            (
                number,
                line,
            )
        )


for number, line in patch_hits:

    print(
        f"{number:04d}: {line}"
    )


print()
print(
    "=== SUMMARY ==="
)

print(
    "FPL_SIMULATOR_CHALLENGER literal:",
    (
        "YES"
        if "FPL_SIMULATOR_CHALLENGER"
        in text
        else "NO"
    ),
)

print(
    "environment mutation nodes:",
    len(
        env_nodes
    ),
)

print(
    "audit complete"
)
