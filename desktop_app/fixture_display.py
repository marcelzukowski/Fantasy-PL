from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FixtureBadgeData:
    gameweek: int
    opponent: str
    venue: str
    difficulty: int | None
    p_5_plus: float | None
    expected_points: float | None

    @property
    def percentage(self) -> int | None:
        if self.p_5_plus is None:
            return None
        value = float(self.p_5_plus)
        if 0.0 <= value <= 1.0:
            value *= 100.0
        return round(max(0.0, min(100.0, value)))

    @property
    def label(self) -> str:
        score = "--" if self.percentage is None else f"{self.percentage}%"
        return f"{self.opponent} {score}"

    @property
    def tooltip(self) -> str:
        score = "--" if self.percentage is None else f"{self.percentage}%"
        points = "--" if self.expected_points is None else f"{self.expected_points:.2f}"
        fdr = "--" if self.difficulty is None else str(self.difficulty)
        return (
            f"GW{self.gameweek} {self.opponent} ({self.venue})\n"
            f"Chance of 5+ FPL points: {score}\n"
            f"Expected points: {points}\n"
            f"FPL FDR: {fdr}"
        )


class FixtureDisplayRepository:
    """Read display-only fixture data from one immutable prediction bundle."""

    def __init__(self, player_source: Path):
        self.run_dir = Path(player_source).resolve().parent
        self._fixtures = self._read_list("fixture_horizon.json")
        self._projections = self._read_list("player_projections.json")
        self._projection_by_player = {
            str(row.get("player_id")): row
            for row in self._projections
            if isinstance(row, Mapping) and row.get("player_id") is not None
        }
        self._team_names = self._load_team_names()

    def _read_list(self, name: str) -> list[Mapping[str, Any]]:
        path = self.run_dir / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, Mapping)]

    def _load_team_names(self) -> dict[str, str]:
        kit_root = Path(__file__).resolve().parent / "assets" / "kits"
        manifests = sorted(kit_root.glob("*/kit_manifest.json"), reverse=True)
        if not manifests:
            return {}
        try:
            payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        teams = payload.get("teams", {})
        if not isinstance(teams, Mapping):
            return {}
        return {
            str(team_id): str(row.get("short_name") or team_id)
            for team_id, row in teams.items()
            if isinstance(row, Mapping)
        }

    def entries_for(self, player: Any, first_gameweek: int, count: int = 3) -> list[FixtureBadgeData]:
        player_id = str(player.player_id)
        team_id = str(player.team_id) if player.team_id is not None else None
        projection = self._projection_by_player.get(player_id, {})
        gameweeks = projection.get("gameweeks", []) if isinstance(projection, Mapping) else []
        projection_by_gw = {
            int(row["target_gameweek"]): row
            for row in gameweeks
            if isinstance(row, Mapping) and row.get("target_gameweek") is not None
        }

        result: list[FixtureBadgeData] = []
        for gameweek in range(int(first_gameweek), int(first_gameweek) + int(count)):
            matching = [
                row for row in self._fixtures
                if int(row.get("target_gameweek", -1)) == gameweek
                and team_id in {str(row.get("home_team_id")), str(row.get("away_team_id"))}
            ]
            projected = projection_by_gw.get(gameweek, {})
            if not matching:
                result.append(FixtureBadgeData(
                    gameweek=gameweek,
                    opponent="BGW",
                    venue="-",
                    difficulty=None,
                    p_5_plus=_optional_float(projected.get("p_5_plus")),
                    expected_points=_optional_float(projected.get("expected_points")),
                ))
                continue

            fixture = matching[0]
            is_home = str(fixture.get("home_team_id")) == team_id
            provider_payload = fixture.get("provider_payload", {})
            if not isinstance(provider_payload, Mapping):
                provider_payload = {}
            opponent_id = fixture.get("away_provider_team_id" if is_home else "home_provider_team_id")
            difficulty = provider_payload.get("team_h_difficulty" if is_home else "team_a_difficulty")
            result.append(FixtureBadgeData(
                gameweek=gameweek,
                opponent=self._team_names.get(str(opponent_id), str(opponent_id or "--")),
                venue="H" if is_home else "A",
                difficulty=_optional_int(difficulty),
                p_5_plus=_optional_float(projected.get("p_5_plus")),
                expected_points=_optional_float(projected.get("expected_points")),
            ))
        return result


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
