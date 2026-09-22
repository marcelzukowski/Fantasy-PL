"""Read-only ranked transfer targets from a canonical production bundle."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

from .data_access import DesktopDataError, PlayerRecord, load_players
from .fixture_display import FixtureDisplayRepository


TARGET_RANK_METRIC = "weighted_ev_next_6"
POSITIONS = ("ALL", "GK", "DEF", "MID", "FWD")


class TransferTargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransferTarget:
    rank_metric: float
    player_id: str
    player: str
    position: str
    club: str
    price_tenths: int | None
    next_fixture: str | None
    gameweek_expected_points: float | None
    p_5_plus: float | None
    expected_minutes: float | None
    ev_next_3: float | None
    ev_next_6: float | None
    team_id: str | None = None
    fixtures: tuple[str, ...] = ()


def _object(path: Path, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransferTargetError(f"The production {label} is unreadable.") from exc
    if not isinstance(payload, Mapping):
        raise TransferTargetError(f"The production {label} is invalid.")
    return payload


def _number(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _club_labels(current_players: Iterable[Mapping[str, object]], fixtures: FixtureDisplayRepository) -> dict[str, str]:
    labels: dict[str, str] = {}
    team_names = getattr(fixtures, "_team_names", {})
    for row in current_players:
        player_id = row.get("player_id")
        if player_id is None:
            continue
        provider_team_id = row.get("provider_team_id")
        if provider_team_id is None:
            provider = row.get("provider_payload")
            if isinstance(provider, Mapping):
                provider_team_id = provider.get("team")
        if provider_team_id is not None:
            labels[str(player_id)] = str(team_names.get(str(provider_team_id), provider_team_id))
    return labels


def load_transfer_targets(
    bundle_path: Path,
    *,
    owned_player_ids: Iterable[str],
    include_owned: bool = False,
) -> tuple[TransferTarget, ...]:
    """Load every eligible unowned target, deterministically ranked by V2's existing weighted 6-GW EV."""
    bundle_path = Path(bundle_path)
    bundle = _object(bundle_path, "projection bundle")
    current_gameweek = _integer(bundle.get("current_gameweek"))
    rows = bundle.get("candidate_pool")
    projections = bundle.get("projections")
    if current_gameweek is None or not isinstance(rows, list) or not isinstance(projections, list):
        raise TransferTargetError("The production projection bundle lacks target data.")
    try:
        current_raw = json.loads((bundle_path.parent / "current_players.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransferTargetError("The production player data is unreadable.") from exc
    if not isinstance(current_raw, list):
        raise TransferTargetError("The production player data is invalid.")
    try:
        players = load_players(bundle_path.parent / "current_players.json")
    except DesktopDataError as exc:
        raise TransferTargetError("The production player data is invalid.") from exc
    fixtures = FixtureDisplayRepository(bundle_path.parent / "current_players.json")
    clubs = _club_labels((row for row in current_raw if isinstance(row, Mapping)), fixtures)
    projections_by_id = {
        str(row.get("player_id")): row
        for row in projections
        if isinstance(row, Mapping) and row.get("player_id") is not None
    }
    raw_by_id = {
        str(row.get("player_id")): row
        for row in current_raw
        if isinstance(row, Mapping) and row.get("player_id") is not None
    }
    owned = {str(player_id) for player_id in owned_player_ids}
    targets: list[TransferTarget] = []
    for candidate in rows:
        if not isinstance(candidate, Mapping) or candidate.get("player_id") is None:
            continue
        player_id = str(candidate["player_id"])
        if player_id in owned and not include_owned:
            continue
        record: PlayerRecord | None = players.get(player_id)
        projection = projections_by_id.get(player_id)
        raw = raw_by_id.get(player_id, {})
        provider = raw.get("provider_payload") if isinstance(raw, Mapping) else None
        if not isinstance(provider, Mapping):
            provider = {}
        if record is None or projection is None or provider.get("can_select") is False or provider.get("removed") is True:
            continue
        metric = _number(projection.get(TARGET_RANK_METRIC))
        if metric is None:
            continue
        gameweek = next(
            (
                row for row in projection.get("gameweeks", ())
                if isinstance(row, Mapping) and _integer(row.get("target_gameweek")) == current_gameweek
            ),
            None,
        )
        fixture_entries = fixtures.entries_for(record, current_gameweek, count=6)
        fixture_labels = tuple(
            f"{entry.opponent} {entry.venue}"
            for entry in fixture_entries
        )
        fixture_label = fixture_labels[0] if fixture_labels else None
        targets.append(TransferTarget(
            rank_metric=metric,
            player_id=player_id,
            player=record.display_name,
            position=record.position,
            club=clubs.get(player_id, str(candidate.get("club_id") or record.team_id or "—")),
            price_tenths=_integer(candidate.get("current_price")) if candidate.get("current_price") is not None else record.current_price,
            next_fixture=fixture_label,
            gameweek_expected_points=_number(gameweek.get("expected_points")) if isinstance(gameweek, Mapping) else None,
            p_5_plus=_number(gameweek.get("p_5_plus")) if isinstance(gameweek, Mapping) else None,
            expected_minutes=_number(gameweek.get("expected_minutes")) if isinstance(gameweek, Mapping) else None,
            ev_next_3=_number(projection.get("ev_next_3")),
            ev_next_6=_number(projection.get("ev_next_6")),
            team_id=record.team_id,
            fixtures=fixture_labels,
        ))
    return tuple(sorted(targets, key=lambda row: (-row.rank_metric, -(row.ev_next_6 or 0.0), row.player.casefold(), row.player_id)))


def filter_transfer_targets(
    targets: Iterable[TransferTarget],
    *,
    position: str = "ALL",
    query: str = "",
    limit: int = 10,
) -> tuple[TransferTarget, ...]:
    selected = str(position).upper()
    if selected not in POSITIONS:
        raise TransferTargetError("position must be ALL, GK, DEF, MID or FWD")
    if limit < 1:
        raise TransferTargetError("limit must be positive")
    needle = str(query).strip().casefold()
    rows = tuple(
        target for target in targets
        if (selected == "ALL" or target.position == selected)
        and (not needle or needle in target.player.casefold() or needle in target.club.casefold())
    )
    return rows[:limit]


def affordability_status(
    target: TransferTarget,
    *,
    owned_player_ids: Iterable[str],
    bank_tenths: int,
    selling_prices_tenths: Mapping[str, int],
    players_by_id: Mapping[str, PlayerRecord],
) -> str:
    """Return an informational one-transfer affordability state.

    It tests whether the target can replace at least one same-position owned
    player using the real selling price and bank while retaining the club cap.
    It does not make a recommendation or construct a transfer plan.
    """
    owned = tuple(str(player_id) for player_id in owned_player_ids)
    if target.player_id in owned:
        return "OWNED"
    if target.price_tenths is None or target.team_id is None:
        return "NEEDS FUNDING"
    team_counts = Counter(
        player.team_id for player_id in owned
        if (player := players_by_id.get(player_id)) is not None
    )
    for player_id in owned:
        outgoing = players_by_id.get(player_id)
        sale_price = selling_prices_tenths.get(player_id)
        if outgoing is None or outgoing.position != target.position or type(sale_price) is not int:
            continue
        after_target_count = team_counts[target.team_id] + 1 - int(outgoing.team_id == target.team_id)
        if after_target_count <= 3 and bank_tenths + sale_price >= target.price_tenths:
            return "AFFORDABLE"
    return "NEEDS FUNDING"


def alternative_transfer_targets(
    targets: Iterable[TransferTarget],
    *,
    outgoing_position: str | None,
    primary_in_ids: Iterable[str] = (),
    limit: int = 2,
) -> tuple[TransferTarget, ...]:
    """Return same-position alternatives from the existing ranked target list."""
    if limit < 1:
        raise TransferTargetError("limit must be positive")
    position = str(outgoing_position or "").upper()
    if position not in POSITIONS[1:]:
        return ()
    primary = {str(player_id) for player_id in primary_in_ids}
    return tuple(
        target for target in targets
        if target.position == position and target.player_id not in primary
    )[:limit]


def format_transfer_targets(
    targets: Iterable[TransferTarget],
    *,
    selected_in_ids: Iterable[str] = (),
) -> str:
    selected = {str(player_id) for player_id in selected_in_ids}
    rows = tuple(targets)
    if not rows:
        return "No eligible targets in this position."

    def money(value: int | None) -> str:
        return "—" if value is None else f"£{value / 10:.1f}m"

    def value(number: float | None, suffix: str = "") -> str:
        return "—" if number is None else f"{number:.2f}{suffix}"

    lines = []
    for index, target in enumerate(rows, 1):
        marker = " ★ IN" if target.player_id in selected else ""
        probability = "—" if target.p_5_plus is None else f"{target.p_5_plus * 100:.0f}%"
        lines.append(f"{index}. {target.player}{marker} · {target.position} · {target.club} · {money(target.price_tenths)}")
        lines.append(
            f"   {' | '.join(target.fixtures) if target.fixtures else target.next_fixture or 'Fixture —'} · GW {value(target.gameweek_expected_points)} pts · "
            f"p_5_plus {probability} · {value(target.expected_minutes, 'm')}"
        )
        lines.append(f"   3GW {value(target.ev_next_3)} · 6GW {value(target.ev_next_6)}")
    return "\n".join(lines)
