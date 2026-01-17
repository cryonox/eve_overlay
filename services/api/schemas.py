from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List


class EventType(str, Enum):
    INITIAL = "initial"
    UPDATE = "update"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class PilotUpdate:
    name: str
    state: str
    char_id: Optional[int] = None
    corp_id: Optional[int] = None
    alliance_id: Optional[int] = None
    corp_name: Optional[str] = None
    alliance_name: Optional[str] = None
    stats: Optional[Dict] = None
    stats_link: Optional[str] = None
    error_msg: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class StreamEvent:
    type: EventType
    pilots: Optional[Dict[str, dict]] = None
    updated: Optional[List[str]] = None
    error: Optional[str] = None

    def to_dict(self):
        d = {"type": self.type.value}
        if self.pilots is not None:
            d["pilots"] = self.pilots
        if self.updated is not None:
            d["updated"] = self.updated
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class DScanRequest:
    data: str
    diff_timeout: float = 60.0


@dataclass 
class DScanResponse:
    ship_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_ships: int = 0
    group_totals: Dict[str, int] = field(default_factory=dict)
    ship_diffs: Dict[str, int] = field(default_factory=dict)
    group_diffs: Dict[str, int] = field(default_factory=dict)
    dscan_url: Optional[str] = None
