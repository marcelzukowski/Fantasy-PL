from pathlib import Path
import json

import fpl_engine.current as current


root = Path.cwd()

path = Path(
    current.__file__
)

lines = path.read_text(
    encoding="utf-8"
).splitlines()


print()
print(
    "=== CURRENT.PY L1015-L1035 ==="
)

for n in range(
    1015,
    1036,
):
    print(
        f"{n:4}: {lines[n - 1]}"
    )


print()
print(
    "=== ACTIVE MANIFEST 2026-27 ==="
)

manifest = (
    current._load_active_model_manifest(
        root,
        "2026-27",
    )
)

print(
    json.dumps(
        {
            "status": manifest.get(
                "status"
            ),
            "active": manifest.get(
                "active"
            ),
        },
        indent=2,
        ensure_ascii=False,
    )
)


print()
print(
    "=== END ==="
)
