"""CONTEXT-001 canonical tactical role taxonomy."""

from enum import StrEnum


class TacticalRole(StrEnum):
    GOALKEEPER = "goalkeeper"
    CENTRE_BACK = "centre_back"
    WIDE_CENTRE_BACK = "wide_centre_back"
    DEFENSIVE_FULLBACK = "defensive_fullback"
    ATTACKING_FULLBACK = "attacking_fullback"
    WINGBACK = "wingback"
    DEFENSIVE_MIDFIELDER = "defensive_midfielder"
    CENTRAL_MIDFIELDER = "central_midfielder"
    BOX_TO_BOX_MIDFIELDER = "box_to_box_midfielder"
    ATTACKING_MIDFIELDER = "attacking_midfielder"
    WINGER = "winger"
    INSIDE_FORWARD = "inside_forward"
    WIDE_PLAYMAKER = "wide_playmaker"
    SECOND_STRIKER = "second_striker"
    CENTRE_FORWARD = "centre_forward"
    TARGET_FORWARD = "target_forward"
    MOBILE_STRIKER = "mobile_striker"
    FALSE_NINE = "false_nine"
    UNKNOWN = "unknown"


TACTICAL_ROLE_TAXONOMY_VERSION = "tactical_roles_v1"


def validate_fpl_position(position: str) -> str:
    value = position.upper()
    if value not in {"GK", "DEF", "MID", "FWD"}:
        raise ValueError("fpl_position must be GK, DEF, MID or FWD")
    return value
