import re
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict

PILOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9' -]*[A-Za-z0-9]$")


class PilotState(Enum):
    CACHE_HIT = auto()
    SEARCHING_ESI = auto()
    SEARCHING_STATS = auto()
    FOUND = auto()
    NOT_FOUND = auto()
    ERROR = auto()
    RATE_LIMITED = auto()


@dataclass
class PilotData:
    name: str
    state: PilotState = PilotState.SEARCHING_ESI
    char_id: Optional[int] = None
    corp_id: Optional[int] = None
    alliance_id: Optional[int] = None
    corp_name: Optional[str] = None
    alliance_name: Optional[str] = None
    stats: Optional[Dict] = None
    stats_link: Optional[str] = None
    error_msg: Optional[str] = None
    corp_alliance_resolved: bool = False


@dataclass
class DScanResult:
    ship_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_ships: int = 0

    @property
    def is_empty(self) -> bool:
        return self.total_ships == 0


def get_invalid_pilot_name_reason(name: str) -> Optional[str]:
    if not name:
        return "empty name"
    if len(name) < 3:
        return f"too short ({len(name)} < 3)"
    if len(name) > 37:
        return f"too long ({len(name)} > 37)"
    if not PILOT_NAME_PATTERN.match(name):
        if name[0] in " '-":
            return f"starts with invalid char '{name[0]}'"
        if name[-1] in " '-":
            return f"ends with invalid char '{name[-1]}'"
        return "contains invalid characters"
    return None


def is_valid_pilot_name(name: str) -> bool:
    return get_invalid_pilot_name_reason(name) is None
