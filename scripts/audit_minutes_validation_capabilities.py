from __future__ import annotations

import ast
import inspect
from pathlib import Path


ROOT = Path("src/fpl_engine/models/minutes")

print()
print("============================================")
print("MINUTES MODULES")
print("============================================")

for path in sorted(ROOT.rglob("*.py")):
    print(path)


print()
print("============================================")
print("FUNCTION / CLASS MAP")
print("============================================")

for path in sorted(ROOT.rglob("*.py")):

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    tree = ast.parse(text)

    interesting = []

    for node in tree.body:

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
                for token in (
                    "calibr",
                    "valid",
                    "walk",
                    "backtest",
                    "score",
                    "metric",
                    "minute",
                )
            ):

                interesting.append(
                    (
                        node.name,
                        node.lineno,
                        getattr(
                            node,
                            "end_lineno",
                            None,
                        ),
                    )
                )

    if not interesting:
        continue

    print()
    print(path)

    for name, start, end in interesting:
        print(
            f"  {name:<38} "
            f"L{start}-{end}"
        )


print()
print("============================================")
print("IMPORTABLE SIGNATURES")
print("============================================")

modules = (
    "fpl_engine.models.minutes.calibration",
    "fpl_engine.models.minutes.validation",
)

for module_name in modules:

    try:
        module = __import__(
            module_name,
            fromlist=["*"],
        )
    except Exception as exc:
        print(
            module_name,
            "IMPORT ERROR:",
            type(exc).__name__,
        )
        continue

    print()
    print(module_name)

    for name in sorted(
        dir(module)
    ):

        if name.startswith("_"):
            continue

        obj = getattr(
            module,
            name,
        )

        if not callable(obj):
            continue

        lowered = name.lower()

        if not any(
            token in lowered
            for token in (
                "calibr",
                "valid",
                "walk",
                "backtest",
                "score",
                "metric",
            )
        ):
            continue

        try:
            signature = inspect.signature(
                obj
            )
        except Exception:
            continue

        print(
            f"  {name}{signature}"
        )


print()
print("=== END ===")
