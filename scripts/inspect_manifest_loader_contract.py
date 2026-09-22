from pathlib import Path

import fpl_engine.current as current


path = Path(
    current.__file__
)

lines = path.read_text(
    encoding="utf-8"
).splitlines()


print()
print(
    "=== CURRENT.PY L945-L1015 ==="
)

for n in range(
    945,
    1016,
):
    print(
        f"{n:4}: {lines[n - 1]}"
    )


print()
print(
    "=== MANIFEST-LIKE JSON FILES ==="
)

root = Path.cwd()

for base in (
    root / "data" / "processed",
    root / "config",
):

    if not base.exists():
        continue

    for file in sorted(
        base.rglob("*.json")
    ):

        name = file.name.casefold()

        if (
            "manifest" in name
            or "champion" in name
            or "model" in name
        ):

            try:
                rel = file.relative_to(
                    root
                )
            except ValueError:
                rel = file

            print(rel)


print()
print(
    "=== END ==="
)
