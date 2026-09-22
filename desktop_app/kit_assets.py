from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


class KitAssetRepository:
    """Resolve locally cached official FPL kit assets."""

    def __init__(self, assets_root: Path | None = None):
        root = assets_root or (Path(__file__).resolve().parent / "assets" / "kits")
        manifests = sorted(Path(root).glob("*/kit_manifest.json"), reverse=True)
        self.manifest_path = manifests[0] if manifests else None
        self._payload: Mapping = {}
        if self.manifest_path is not None:
            try:
                value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(value, Mapping):
                    self._payload = value
            except (OSError, json.JSONDecodeError):
                pass

    def path_for(self, team_id, provider_id=None, *, goalkeeper: bool = False) -> Path | None:
        if self.manifest_path is None:
            return None
        teams = self._payload.get("teams", {})
        code_to_id = self._payload.get("team_code_to_id", {})
        element_to_team = self._payload.get("element_to_team_id", {})
        resolved = None
        value = str(team_id) if team_id is not None else ""
        if value in teams:
            resolved = value
        elif value in code_to_id:
            resolved = str(code_to_id[value])
        elif provider_id is not None and str(provider_id) in element_to_team:
            resolved = str(element_to_team[str(provider_id)])
        row = teams.get(resolved, {}) if resolved is not None else {}
        if not isinstance(row, Mapping):
            return None
        name = row.get("goalkeeper_file" if goalkeeper else "file")
        if not name:
            return None
        path = self.manifest_path.parent / str(name)
        return path if path.exists() else None
