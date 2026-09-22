from pathlib import Path
import json

import fpl_engine.current as current


manifest = current._load_active_model_manifest(
    Path.cwd(),
    "2026/27",
)

print(
    json.dumps(
        {
            "status": manifest.get("status"),
            "active": manifest.get("active"),
        },
        indent=2,
        ensure_ascii=False,
    )
)
