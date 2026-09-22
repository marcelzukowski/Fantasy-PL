"""Explicit source support audit for every active 2026/27 BPS component."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class BpsSupportEntry:
    component: str
    source: str | None
    historical_availability: bool
    current_availability: bool
    supported: bool
    treatment: str


@dataclass(frozen=True)
class BpsSupportMatrix:
    season: str
    entries: tuple[BpsSupportEntry, ...]

    @property
    def completeness(self) -> float:
        return sum(row.supported for row in self.entries) / len(self.entries) if self.entries else 0.0


_SUPPORT: Mapping[str, tuple[str | None, bool, bool, str]] = {
    "appearance.minutes_1_to_60": ("Official FPL/Vaastav minutes", True, True, "modelled"),
    "appearance.over_60_minutes": ("Official FPL/Vaastav minutes", True, True, "modelled"),
    "goals.penalty_goal": ("Official FPL goal totals + probabilistic penalty prior", False, True, "partially modelled; identity unavailable historically"),
    "goals.non_penalty_goal": ("Official FPL goal totals", False, True, "goal total modelled; penalty split uncertain"),
    "assists": ("Official FPL/Vaastav assists and xA", True, True, "modelled probabilistically"),
    "clean_sheet": ("fixture goals + minutes", True, True, "modelled"),
    "goalkeeper.save": ("Official FPL saves", True, True, "modelled"),
    "goalkeeper.save_from_inside_box": (None, False, False, "unmodelled/NULL"),
    "goalkeeper.save_from_big_chance": (None, False, False, "unmodelled/NULL"),
    "goalkeeper.penalty_save": ("Official FPL aggregate", True, True, "prior; sparse-event uncertainty"),
    "attacking_actions.shot_on_target": ("API-Football current only", False, True, "current-only when supplied"),
    "attacking_actions.chance_created": ("API-Football current only", False, True, "current-only when supplied"),
    "attacking_actions.big_chance_created": (None, False, False, "unmodelled/NULL"),
    "defensive_actions.clearances_blocks_interceptions": ("API-Football current only", False, True, "current-only when supplied"),
    "defensive_actions.recoveries": (None, False, False, "unmodelled/NULL"),
    "defensive_actions.successful_tackle": ("API-Football current only", False, True, "current-only when supplied"),
    "negative_actions.yellow_card": ("Official FPL/Vaastav", True, True, "modelled"),
    "negative_actions.red_card": ("Official FPL/Vaastav", True, True, "modelled"),
}


def load_bps_support_matrix(project_root: Path) -> BpsSupportMatrix:
    path = Path(project_root) / "docs" / "03_SIMULATION" / "scoring_rules.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    bps = payload["bps"]
    groups = (
        "appearance", "goals", "assists", "clean_sheet", "goalkeeper",
        "attacking_actions", "defensive_actions", "passing", "negative_actions",
    )
    components: list[str] = []
    for group in groups:
        value = bps.get(group, {})
        if group in {"assists", "clean_sheet"}:
            components.append(group)
        elif isinstance(value, dict):
            components.extend(f"{group}.{name}" for name in value if name != "notes")
    entries = []
    for component in components:
        source, historical, current, treatment = _SUPPORT.get(
            component, (None, False, False, "unmodelled/NULL"),
        )
        supported = treatment.startswith("modelled")
        entries.append(BpsSupportEntry(
            component, source, historical, current, supported, treatment,
        ))
    return BpsSupportMatrix(str(payload["season"]), tuple(entries))

