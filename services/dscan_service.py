import json
import copy
import time
import requests
from pathlib import Path
from typing import Optional, Dict
from loguru import logger

from .models import DScanResult


def get_dscan_info_url(paste_data: str) -> Optional[str]:
    try:
        ts = int(time.time() * 1000)
        resp = requests.post(
            f"https://dscan.info/?_={ts}", data={"paste": paste_data}, timeout=10)
        if resp.status_code != 200:
            return None
        txt = resp.text.strip()
        return f"https://dscan.info/v/{txt.split(';')[1]}" if txt.startswith("OK;") else None
    except Exception as e:
        logger.info(f"dscan.info request failed: {e}")
        return None


class DScanService:
    def __init__(self, ships_file: str = 'ships.json'):
        self.ships = self._load_ships(ships_file)
        self.last_res: Optional[DScanResult] = None
        self.prev_res: Optional[DScanResult] = None
        self.last_parse_time: Optional[float] = None

    def _load_ships(self, ships_file: str) -> Dict:
        try:
            path = Path(ships_file)
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load ships.json: {e}")
        return {}

    def is_dscan_format(self, data: str) -> bool:
        lines = data.strip().split('\n')
        return bool(lines) and any('\t' in line for line in lines[:5])

    def is_valid_dscan(self, data: str) -> bool:
        lines = data.strip().split('\n')
        if not lines:
            return False
        for i, line in enumerate(lines):
            if line and line[0] in ' \t':
                logger.debug(
                    f"Invalid dscan: line {i+1} starts with whitespace")
                return False
        return True

    def parse(self, dscan_data: str, diff_timeout: float = 60.0) -> Optional[DScanResult]:
        if not self.ships:
            logger.warning("No ship data loaded")
            return None

        cur_time = time.time()
        if self.last_parse_time and cur_time - self.last_parse_time > diff_timeout:
            self.last_res = None
            self.prev_res = None

        lines = dscan_data.strip().split('\n')
        ship_counts: Dict[str, Dict[str, int]] = {}
        total = 0

        for line in lines:
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            ship_name = parts[2].strip().split(' - ')[0].strip()
            if ship_name not in self.ships:
                continue
            grp = self.ships[ship_name]['group_name']
            if grp not in ship_counts:
                ship_counts[grp] = {}
            ship_counts[grp][ship_name] = ship_counts[grp].get(
                ship_name, 0) + 1
            total += 1

        if not ship_counts:
            return None

        if self.last_res is not None:
            self.prev_res = copy.deepcopy(self.last_res)

        self.last_parse_time = cur_time
        self.last_res = DScanResult(ship_counts=ship_counts, total_ships=total)
        return self.last_res

    def get_ship_diffs(self) -> Dict[str, int]:
        if not self.last_res or not self.prev_res:
            return {}

        diffs = {}
        cur_counts, prev_counts = self.last_res.ship_counts, self.prev_res.ship_counts

        for grp, ships in cur_counts.items():
            for ship, cnt in ships.items():
                prev = prev_counts.get(grp, {}).get(ship, 0)
                if cnt != prev:
                    diffs[ship] = cnt - prev

        cur_ships = {s for ships in cur_counts.values() for s in ships}
        for grp, ships in prev_counts.items():
            for ship, prev_cnt in ships.items():
                if ship not in cur_ships:
                    diffs[ship] = -prev_cnt

        return diffs

    def get_group_totals(self) -> Dict[str, int]:
        if not self.last_res:
            return {}
        return {grp: sum(ships.values()) for grp, ships in self.last_res.ship_counts.items()}

    def get_group_diffs(self) -> Dict[str, int]:
        if not self.last_res or not self.prev_res:
            return {}

        diffs = {}
        cur_totals = self.get_group_totals()
        prev_totals = {grp: sum(ships.values())
                       for grp, ships in self.prev_res.ship_counts.items()}

        for grp, cur_total in cur_totals.items():
            prev_total = prev_totals.get(grp, 0)
            if cur_total != prev_total:
                diffs[grp] = cur_total - prev_total

        for grp in prev_totals:
            if grp not in cur_totals:
                diffs[grp] = -prev_totals[grp]

        return diffs

    def reset(self):
        self.last_res = None
        self.prev_res = None
        self.last_parse_time = None

    @property
    def last_result(self):
        return self.last_res

    @property
    def previous_result(self):
        return self.prev_res
