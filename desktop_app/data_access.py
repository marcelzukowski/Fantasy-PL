from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import json
import os

from .state import (
    DesktopSquadState,
    default_chip_state,
)


class DesktopDataError(
    RuntimeError
):
    pass


@dataclass(
    frozen=True
)
class PlayerRecord:

    player_id: str

    display_name: str

    position: str

    team_id: str | None

    current_price: int | None

    provider_id: str | None = None


def _json(
    path: Path,
):

    try:

        return json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:

        raise DesktopDataError(
            f"Could not read {path}"
        ) from exc


def resolve_player_source(
    root: Path,
) -> Path:

    explicit = os.environ.get(
        "FPL_DESKTOP_PLAYER_SOURCE"
    )


    if explicit:

        path = Path(
            explicit
        )


        if path.is_dir():

            path = (
                path
                / "current_players.json"
            )


        if path.exists():

            return path


        raise DesktopDataError(
            "FPL_DESKTOP_PLAYER_SOURCE "
            f"does not exist: {path}"
        )


    preferred = (
        root
        / "scratch"
        / "decision"
        / "captain068g"
        / "integrated_replay"
        / "v22_real"
        / "current_players.json"
    )


    if preferred.exists():

        return preferred


    candidates = []


    for search_root in (
        root
        / "scratch",

        root
        / "data"
        / "processed",
    ):

        if search_root.exists():

            candidates.extend(
                search_root.rglob(
                    "current_players.json"
                )
            )


    if not candidates:

        raise DesktopDataError(
            "No current_players.json "
            "artifact found."
        )


    return max(
        candidates,
        key=lambda path:
            path.stat().st_mtime,
    )


def load_players(
    path: Path,
):

    payload = _json(
        path
    )


    if not isinstance(
        payload,
        list,
    ):

        raise DesktopDataError(
            "current_players.json "
            "must contain a list."
        )


    players = {}


    for row in payload:

        if not isinstance(
            row,
            Mapping,
        ):

            continue


        provider = row.get(
            "provider_payload",
            {},
        )


        if not isinstance(
            provider,
            Mapping,
        ):

            provider = {}


        player_id = str(
            row[
                "player_id"
            ]
        )


        display_name = (
            row.get(
                "display_name"
            )
            or row.get(
                "name"
            )
            or provider.get(
                "web_name"
            )
            or player_id
        )


        position = str(
            row.get(
                "position",
                "",
            )
        ).upper()


        if position not in {
            "GK",
            "DEF",
            "MID",
            "FWD",
        }:

            continue


        team_id = (
            row.get(
                "team_id"
            )
            or row.get(
                "provider_team_id"
            )
            or provider.get(
                "team"
            )
        )


        price = row.get(
            "current_price"
        )


        if price is None:

            price = provider.get(
                "now_cost"
            )


        provider_id = row.get(
            "provider_id"
        )


        if provider_id is None:

            provider_id = provider.get(
                "id"
            )


        players[
            player_id
        ] = PlayerRecord(
            player_id=player_id,

            display_name=str(
                display_name
            ),

            position=position,

            team_id=(
                None
                if team_id is None
                else str(
                    team_id
                )
            ),

            current_price=(
                None
                if price is None
                else int(
                    price
                )
            ),

            provider_id=(
                None
                if provider_id is None
                else str(
                    provider_id
                )
            ),
        )


    if not players:

        raise DesktopDataError(
            "Player pool is empty."
        )


    return players


def bootstrap_saved_wc(
    root: Path,
) -> DesktopSquadState:

    path = (
        root
        / "scratch"
        / "decision"
        / "captain068h"
        / "decision_42.json"
    )


    if not path.exists():

        return DesktopSquadState()


    payload = _json(
        path
    )


    rows = payload.get(
        "saved_wc_resolution",
        [],
    )


    ids = [
        str(
            row[
                "player_id"
            ]
        )
        for row
        in rows
        if isinstance(
            row,
            Mapping,
        )
        and row.get(
            "player_id"
        )
    ]


    if len(
        ids
    ) != 15:

        return DesktopSquadState()


    chips = default_chip_state()

    chips[
        "wildcard_h1"
    ] = True


    return DesktopSquadState(
        season="2026/27",

        gameweek=5,

        bank_tenths=1,

        free_transfers=1,

        player_ids=ids,

        chips_used=chips,

        source=str(
            path.relative_to(
                root
            )
        ),
    )
