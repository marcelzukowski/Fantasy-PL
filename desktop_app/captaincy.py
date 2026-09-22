"""Display-only captaincy summary from a validated Recommended XI."""

from __future__ import annotations

from typing import Mapping


def format_captaincy_summary(*, preview, players: Mapping[str, object], fixtures,
                              first_gameweek: int, recommendation: Mapping[str, object]) -> str:
    """Render only existing decision, player and fixture-projection fields."""
    def player_name(player_id: str) -> str:
        player = players[str(player_id)]
        return str(getattr(player, "display_name", player_id))

    def fixture_lines(role: str, player_id: str) -> list[str]:
        player = players[str(player_id)]
        entries = fixtures.entries_for(player, first_gameweek, count=1)
        if not entries:
            return []
        entry = entries[0]
        lines = [f"{role} fixture: {entry.label}"]
        if entry.expected_points is not None:
            lines.append(f"{role} expected points: {entry.expected_points:.2f}")
        if entry.percentage is not None:
            lines.append(f"{role} p_5_plus: {entry.percentage}%")
        return lines

    captain_id = str(preview.captain_id)
    vice_id = str(preview.vice_captain_id)
    lines = [f"Captain: {player_name(captain_id)}", f"Vice-captain: {player_name(vice_id)}"]
    lines.extend(fixture_lines("Captain", captain_id))
    lines.extend(fixture_lines("Vice-captain", vice_id))
    for key, label in (("captain_reason", "Reason"), ("captaincy_reason", "Reason"), ("captaincy_margin", "Captaincy margin")):
        value = recommendation.get(key)
        if value is not None:
            lines.append(f"{label}: {value}")
            break
    return "\n".join(lines)
