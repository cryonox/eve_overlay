import pyperclip
import time
from enum import Enum, auto
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List
import asyncio
import aiohttp
from config import C
import cv2
import numpy as np
import utils
from global_hotkeys import register_hotkeys, start_checking_hotkeys
import webbrowser
from loguru import logger
import json
import threading
from cache import CacheManager
from base_api_client import APIClientFactory


class PilotState(Enum):
    CACHE_HIT = auto()
    SEARCHING_ESI = auto()
    SEARCHING_STATS = auto()
    FOUND = auto()
    NOT_FOUND = auto()
    ERROR = auto()


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


class StatsInterface(ABC):
    @abstractmethod
    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        pass

    @abstractmethod
    def get_link(self, char_id: int) -> str:
        pass

    @abstractmethod
    def extract_display_stats(self, stats: Dict) -> Dict:
        pass


class ZKillStatsProvider(StatsInterface):
    def __init__(self):
        self.client = APIClientFactory.create_client('zkill')

    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        return await self.client._get_char_short_stats_with_session(session, char_id)

    def get_link(self, char_id: int) -> str:
        return f"https://zkillboard.com/character/{char_id}/"

    def extract_display_stats(self, stats: Dict) -> Dict:
        if not stats or 'error' in stats:
            return {}
        return {
            'danger': stats.get('dangerRatio', 0),
            'kills': stats.get('shipsDestroyed', 0),
            'losses': stats.get('shipsLost', 0)
        }


class EveKillStatsProvider(StatsInterface):
    def __init__(self):
        self.client = APIClientFactory.create_client('evekill')

    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        return await self.client._get_char_short_stats_with_session(session, char_id)

    def get_link(self, char_id: int) -> str:
        return f"https://eve-kill.com/character/{char_id}"

    def extract_display_stats(self, stats: Dict) -> Dict:
        if not stats or 'error' in stats:
            return {}
        return {
            'danger': stats.get('dangerRatio', 0),
            'kills': stats.get('kills', 0),
            'losses': stats.get('losses', 0)
        }


class ESIResolver:
    def __init__(self):
        self.char_cache = {}
        self.name_cache = {}

    async def resolve_names_to_ids(self, session: aiohttp.ClientSession, names: List[str]) -> Dict[str, int]:
        uncached = [n for n in names if n not in self.name_cache]
        if not uncached:
            return {n: self.name_cache[n] for n in names if n in self.name_cache}

        res = {}
        for i in range(0, len(uncached), 500):
            chunk = uncached[i:i+500]
            url = "https://esi.evetech.net/latest/universe/ids/"
            try:
                async with session.post(url, json=chunk, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        for char in data.get('characters', []):
                            self.name_cache[char['name']] = char['id']
                            res[char['name']] = char['id']
            except Exception as e:
                logger.info(f"ESI name resolution error: {e}")

        for n in names:
            if n in self.name_cache and n not in res:
                res[n] = self.name_cache[n]
        return res

    async def get_char_info(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        if char_id in self.char_cache:
            return self.char_cache[char_id]

        url = f"https://esi.evetech.net/latest/characters/{char_id}/"
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    info = {
                        'corporation_id': data.get('corporation_id'),
                        'alliance_id': data.get('alliance_id')
                    }
                    self.char_cache[char_id] = info
                    return info
        except Exception as e:
            logger.info(f"ESI char info error for {char_id}: {e}")
        return {}

    async def resolve_ids_to_names(self, session: aiohttp.ClientSession, ids: List[int]) -> Dict[int, str]:
        if not ids:
            return {}

        ids = list(set(i for i in ids if i and i != 0))
        res = {}

        for i in range(0, len(ids), 1000):
            chunk = ids[i:i+1000]
            url = "https://esi.evetech.net/latest/universe/names/"
            try:
                async with session.post(url, json=chunk, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        for item in data:
                            res[item['id']] = item['name']
            except Exception as e:
                logger.info(f"ESI id resolution error: {e}")

        return res


class DScanAnalyzer:
    def __init__(self):
        self.ignore_alliances = C.dscan.get('ignore_alliances', [])
        self.ignore_corps = C.dscan.get('ignore_corps', [])
        self.display_duration = C.dscan.get('timeout', 10)
        self.stats_limit = C.dscan.get('zkill_limit', 50)
        self.win_name = "D-Scan Analysis"
        self.transparency_on = C.dscan.get('transparency_on', True)
        self.transparency = C.dscan.get('transparency', 180)
        self.bg_color = C.dscan.get('bg_color', [25, 25, 25])
        self.should_destroy_window = False
        self.last_im = None
        self.last_result_im = None
        self.char_rects = {}
        self.result_start_time = None
        self.last_result_total_time = None

        self.cache = CacheManager()
        self.cache.load_cache()
        self.esi = ESIResolver()

        stats_provider = C.dscan.get('stats_provider', 'zkill')
        self.stats_provider = ZKillStatsProvider() if stats_provider == 'zkill' else EveKillStatsProvider()

        self.pilots: Dict[str, PilotData] = {}
        self.pending_tasks: Dict[str, asyncio.Task] = {}
        self.is_local = False
        self.is_dscan = False
        self.last_ship_counts = None
        self.previous_ship_counts = None
        self.last_dscan_time = None
        self.aggregated_mode = False
        self._network_thread: Optional[threading.Thread] = None

        cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        if self.transparency_on:
            utils.win_transparent('Main HighGUI class', self.win_name, self.transparency, (64, 64, 64))

        hotkey_transparency = C.dscan.get('hotkey_transparency', 'alt+shift+f')
        hotkey_mode = C.dscan.get('hotkey_mode', 'alt+shift+m')
        hotkey_clear_cache = C.dscan.get('hotkey_clear_cache', 'alt+shift+e')
        bindings = [
            [hotkey_transparency.split('+'), None, self.toggle_transparency],
            [hotkey_mode.split('+'), None, self.toggle_mode],
            [hotkey_clear_cache.split('+'), None, self.clear_cache]
        ]
        register_hotkeys(bindings)
        start_checking_hotkeys()
        self.show_status("")

    def toggle_transparency(self):
        self.transparency_on = not self.transparency_on
        self.should_destroy_window = True

    def toggle_mode(self):
        self.aggregated_mode = not self.aggregated_mode

    def clear_cache(self):
        self.stats_provider.client.clear_cache()
        self.esi = ESIResolver()
        logger.info("Caches cleared")

    def handle_transparency(self):
        if self.should_destroy_window:
            cv2.destroyWindow(self.win_name)
            cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
            cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
            cv2.setMouseCallback(self.win_name, self.mouse_callback)
            if self.transparency_on:
                cv2.setWindowProperty(self.win_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
                utils.win_transparent('Main HighGUI class', self.win_name, self.transparency, (64, 64, 64))
            self.should_destroy_window = False
            im = self.last_result_im if self.last_result_im is not None else self.last_im
            if im is not None:
                cv2.imshow(self.win_name, im)
                cv2.waitKey(1)

    def show_status(self, msg):
        if msg == "":
            im = np.full((50, 50, 3), C.dscan.transparency_color, np.uint8)
        else:
            im = utils.draw_text_withnewline(msg, (10, 10), color=(255, 255, 255),
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        self.last_im = im
        cv2.imshow(self.win_name, im)
        cv2.waitKey(1)

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            for char_name, (rect, link) in self.char_rects.items():
                rx, ry, rw, rh = rect
                if rx <= x <= rx + rw and ry - rh <= y <= ry and link:
                    webbrowser.open(link)
                    break

    def should_ignore_pilot(self, pilot: PilotData) -> bool:
        return (pilot.corp_name in self.ignore_corps or
                pilot.alliance_name in self.ignore_alliances if pilot.alliance_name else False)

    async def lookup_pilot_async(self, pilot: PilotData, session: aiohttp.ClientSession):
        try:
            if pilot.char_id is None:
                name_map = await self.esi.resolve_names_to_ids(session, [pilot.name])
                if pilot.name not in name_map:
                    pilot.state = PilotState.NOT_FOUND
                    return
                pilot.char_id = name_map[pilot.name]

            if pilot.corp_id is None:
                char_info = await self.esi.get_char_info(session, pilot.char_id)
                pilot.corp_id = char_info.get('corporation_id')
                pilot.alliance_id = char_info.get('alliance_id')

                ids_to_resolve = [i for i in [pilot.corp_id, pilot.alliance_id] if i]
                if ids_to_resolve:
                    names = await self.esi.resolve_ids_to_names(session, ids_to_resolve)
                    pilot.corp_name = names.get(pilot.corp_id, 'Unknown')
                    pilot.alliance_name = names.get(pilot.alliance_id) if pilot.alliance_id else None

            pilot.state = PilotState.SEARCHING_STATS
            pilot.stats_link = self.stats_provider.get_link(pilot.char_id)

            stats = await self.stats_provider.get_stats(session, pilot.char_id)
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
            elif stats and stats.get('error') == 'not_found':
                pilot.state = PilotState.NOT_FOUND
            else:
                pilot.state = PilotState.ERROR
                pilot.error_msg = stats.get('error', 'unknown') if stats else 'unknown'

        except Exception as e:
            logger.info(f"Error looking up pilot {pilot.name}: {e}")
            pilot.state = PilotState.ERROR
            pilot.error_msg = str(e)

    def process_cache_lookup(self, names: List[str]) -> Dict[str, PilotData]:
        pilots = {}
        for name in names:
            info = self.cache.get_char_info(name)
            if info:
                pilot = PilotData(
                    name=name,
                    state=PilotState.CACHE_HIT,
                    char_id=info['char_id'],
                    corp_id=info['corp_id'],
                    alliance_id=info['alliance_id'],
                    corp_name=info['corp_name'],
                    alliance_name=info['alliance_name']
                )
                pilot.stats_link = self.stats_provider.get_link(pilot.char_id)
            else:
                pilot = PilotData(name=name, state=PilotState.SEARCHING_ESI)
            pilots[name] = pilot
        return pilots

    def process_local(self, clipboard_data: str):
        lines = clipboard_data.strip().split('\n')
        char_names = [line.strip() for line in lines if line.strip()]

        if not char_names:
            self.show_status("")
            return

        self.pilots = self.process_cache_lookup(char_names)
        self.result_start_time = time.time()

        pilots_needing_esi = [p for p in self.pilots.values() if p.state == PilotState.SEARCHING_ESI]
        pilots_needing_stats = [p for p in self.pilots.values() if p.state == PilotState.CACHE_HIT]

        skip_stats = len(char_names) > self.stats_limit
        if skip_stats:
            self.aggregated_mode = True
            for p in pilots_needing_stats:
                p.state = PilotState.FOUND

        if pilots_needing_esi or (not skip_stats and pilots_needing_stats):
            self._start_network_fetch(pilots_needing_esi, pilots_needing_stats, skip_stats)

    def _start_network_fetch(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData], skip_stats: bool):
        if self._network_thread and self._network_thread.is_alive():
            pass

        def run_fetch():
            asyncio.run(self._fetch_network_data(pilots_esi, pilots_stats, skip_stats))

        self._network_thread = threading.Thread(target=run_fetch, daemon=True)
        self._network_thread.start()

    async def _fetch_network_data(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData], skip_stats: bool):
        connector = aiohttp.TCPConnector(limit=50)
        async with aiohttp.ClientSession(connector=connector) as session:
            if pilots_esi:
                esi_tasks = [self.lookup_pilot_async(p, session) for p in pilots_esi]
                await asyncio.gather(*esi_tasks, return_exceptions=True)

            if not skip_stats and pilots_stats:
                stats_tasks = []
                for p in pilots_stats:
                    p.state = PilotState.SEARCHING_STATS
                    stats_tasks.append(self.fetch_stats_for_pilot(p, session))
                await asyncio.gather(*stats_tasks, return_exceptions=True)

    async def fetch_stats_for_pilot(self, pilot: PilotData, session: aiohttp.ClientSession):
        try:
            stats = await self.stats_provider.get_stats(session, pilot.char_id)
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
            elif stats and stats.get('error') == 'not_found':
                pilot.state = PilotState.NOT_FOUND
            else:
                pilot.state = PilotState.ERROR
        except Exception as e:
            pilot.state = PilotState.ERROR
            pilot.error_msg = str(e)


    async def parse_dscan(self, dscan_data: str):
        try:
            with open('ships.json', 'r') as f:
                ships = json.load(f)

            cur_time = time.time()
            if self.last_dscan_time and cur_time - self.last_dscan_time > 60:
                self.last_ship_counts = None
                self.previous_ship_counts = None

            lines = dscan_data.strip().split('\n')
            ship_counts = {}

            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 3:
                    ship_name = parts[2].strip()
                    if ' - ' in ship_name:
                        ship_name = ship_name.split(' - ')[0].strip()
                    if ship_name not in ships:
                        continue
                    group_name = ships[ship_name]['group_name']
                    if group_name not in ship_counts:
                        ship_counts[group_name] = {}
                    ship_counts[group_name][ship_name] = ship_counts[group_name].get(ship_name, 0) + 1

            if not ship_counts:
                self.show_status("No ships found")
                return

            if self.last_ship_counts is not None:
                self.previous_ship_counts = self.last_ship_counts

            self.result_start_time = time.time()
            self.last_dscan_time = cur_time
            self.last_ship_counts = ship_counts
        except Exception as e:
            logger.info(f"Error parsing dscan: {e}")

    def parse_clipboard(self, clipboard_data: str):
        lines = clipboard_data.strip().split('\n')
        is_dscan = any('\t' in line for line in lines[:5])
        self.is_dscan = is_dscan
        self.is_local = not is_dscan

        if is_dscan:
            self.last_ship_counts = None
            self.previous_ship_counts = None
            asyncio.run(self.parse_dscan(clipboard_data))
        else:
            self.process_local(clipboard_data)

    def create_pilot_display(self) -> Optional[np.ndarray]:
        if not self.pilots:
            return None

        self.char_rects = {}
        display_data = []

        for name, pilot in self.pilots.items():
            if self.should_ignore_pilot(pilot):
                continue

            entry = {'name': name[:20], 'pilot': pilot, 'link': pilot.stats_link}

            if pilot.state == PilotState.SEARCHING_ESI:
                entry['text'] = f"{entry['name']} | Resolving..."
                entry['color'] = (255, 255, 0)
            elif pilot.state == PilotState.SEARCHING_STATS:
                entry['text'] = f"{entry['name']} | Fetching stats..."
                entry['color'] = (255, 255, 0)
            elif pilot.state == PilotState.NOT_FOUND:
                entry['text'] = f"{entry['name']} | Not found"
                entry['color'] = (128, 128, 128)
            elif pilot.state == PilotState.ERROR:
                entry['text'] = f"{entry['name']} | Error"
                entry['color'] = (0, 0, 255)
            elif pilot.state in [PilotState.CACHE_HIT, PilotState.FOUND]:
                if pilot.stats:
                    d, k, l = pilot.stats.get('danger', 0), pilot.stats.get('kills', 0), pilot.stats.get('losses', 0)
                    entry['text'] = f"{entry['name']} | D:{d:.0f} K:{k} L:{l}"
                    entry['color'] = (0, 0, 255) if d >= 80 else (0, 255, 255) if d > 0 else (255, 255, 255)
                    entry['danger'] = d
                else:
                    entry['text'] = f"{entry['name']} | [Cached]"
                    entry['color'] = (200, 200, 200)
                    entry['danger'] = -1
            else:
                entry['text'] = f"{entry['name']} | Unknown"
                entry['color'] = (128, 128, 128)
                entry['danger'] = -2

            display_data.append(entry)

        display_data.sort(key=lambda x: x.get('danger', -2), reverse=True)

        remaining = max(0, self.display_duration - (time.time() - self.result_start_time)) if self.result_start_time else self.display_duration
        header = f"Pilots: {len(display_data)} | Timeout: {remaining:.0f}s"
        if self.last_result_total_time:
            header = f"Pilots: {len(display_data)} | Time: {self.last_result_total_time/1000:.2f}s | Timeout: {remaining:.0f}s"

        text_lines = [header] + [e['text'] for e in display_data]
        full_text = '\n'.join(text_lines)

        max_w, total_h = utils.get_text_size_withnewline(full_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        im = np.full((total_h + 40, max_w + 40, 3), C.dscan.transparency_color, np.uint8)

        y = 20
        y = utils.draw_text_on_image(im, header, (10, y), color=(0, 255, 0),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        for entry in display_data:
            text_size, _ = cv2.getTextSize(entry['text'], cv2.FONT_HERSHEY_SIMPLEX,
                C.dscan.font_scale, int(C.dscan.font_thickness))
            self.char_rects[entry['name']] = ((10, y, text_size[0], text_size[1]), entry['link'])
            y = utils.draw_text_on_image(im, entry['text'], (10, y), color=entry['color'],
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        return im

    def create_aggregated_display(self) -> Optional[np.ndarray]:
        if not self.pilots:
            return None

        corp_counts, alliance_counts = {}, {}
        for pilot in self.pilots.values():
            if self.should_ignore_pilot(pilot):
                continue
            corp = pilot.corp_name or 'Unknown'
            corp_counts[corp] = corp_counts.get(corp, 0) + 1
            if pilot.alliance_name:
                alliance_counts[pilot.alliance_name] = alliance_counts.get(pilot.alliance_name, 0) + 1

        remaining = max(0, self.display_duration - (time.time() - self.result_start_time)) if self.result_start_time else self.display_duration
        header = f"Aggregated | Pilots: {len(self.pilots)} | Timeout: {remaining:.0f}s"

        left_lines = [header, "", "Alliances:"]
        left_lines += [f"  {a}: {c}" for a, c in sorted(alliance_counts.items(), key=lambda x: x[1], reverse=True)] or ["  None"]

        right_lines = ["", "", "Corporations:"]
        right_lines += [f"  {c}: {n}" for c, n in sorted(corp_counts.items(), key=lambda x: x[1], reverse=True)]

        left_text, right_text = '\n'.join(left_lines), '\n'.join(right_lines)
        left_w, left_h = utils.get_text_size_withnewline(left_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        right_w, right_h = utils.get_text_size_withnewline(right_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        total_w, total_h = left_w + right_w + 60, max(left_h, right_h) + 40
        im = np.full((total_h, total_w, 3), C.dscan.transparency_color, np.uint8)

        utils.draw_text_on_image(im, left_text, (10, 20), color=(255, 255, 255),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        utils.draw_text_on_image(im, right_text, (left_w + 40, 20), color=(255, 255, 255),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        return im

    def create_dscan_display(self) -> Optional[np.ndarray]:
        if self.last_ship_counts is None:
            return None

        ship_diffs = {}
        if self.previous_ship_counts:
            for grp, ships in self.last_ship_counts.items():
                for ship, cnt in ships.items():
                    prev = self.previous_ship_counts.get(grp, {}).get(ship, 0)
                    if cnt != prev:
                        ship_diffs[ship] = cnt - prev

        ship_list, group_totals, total = [], {}, 0
        for grp, ships in self.last_ship_counts.items():
            grp_total = sum(ships.values())
            group_totals[grp] = grp_total
            total += grp_total
            for ship, cnt in ships.items():
                ship_list.append((ship, cnt, ship_diffs.get(ship, 0)))

        ship_list.sort(key=lambda x: (x[1] == 0, -x[1]))
        sorted_groups = sorted(group_totals.items(), key=lambda x: x[1], reverse=True)

        remaining = max(0, self.display_duration - (time.time() - self.result_start_time)) if self.result_start_time else self.display_duration
        header = f"D-Scan | Ships: {total} | Timeout: {remaining:.0f}s"

        left_lines = [header, ""]
        for ship, cnt, diff in ship_list:
            diff_str = f" (+{diff})" if diff > 0 else f" ({diff})" if diff < 0 else ""
            left_lines.append(f"{ship}: {cnt}{diff_str}")

        right_lines = ["Categories:", ""] + [f"{g}: {c}" for g, c in sorted_groups]

        left_text, right_text = '\n'.join(left_lines), '\n'.join(right_lines)
        left_w, left_h = utils.get_text_size_withnewline(left_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        right_w, right_h = utils.get_text_size_withnewline(right_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        total_w, total_h = left_w + right_w + 60, max(left_h, right_h) + 40
        im = np.full((total_h, total_w, 3), C.dscan.transparency_color, np.uint8)

        y = 20
        for i, line in enumerate(left_lines):
            if i < 2:
                color = (255, 255, 255)
            elif i - 2 < len(ship_list):
                _, _, diff = ship_list[i - 2]
                color = (0, 255, 0) if diff > 0 else (0, 0, 255) if diff < 0 else (255, 255, 255)
            else:
                color = (255, 255, 255)
            y = utils.draw_text_on_image(im, line, (10, y), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        utils.draw_text_on_image(im, right_text, (left_w + 40, 20), color=(255, 255, 255),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        return im

    def get_clipboard_data(self) -> Optional[str]:
        try:
            return pyperclip.paste()
        except Exception as e:
            logger.info(f"Clipboard error: {e}")
            return None

    def start(self):
        logger.info("Press Ctrl+C to exit")
        last_clipboard = ""

        try:
            while True:
                cur_clipboard = self.get_clipboard_data()
                if cur_clipboard and cur_clipboard != last_clipboard:
                    self.show_status("Working...")
                    utils.tick()
                    self.parse_clipboard(cur_clipboard)
                    self.last_result_total_time = utils.tock()
                    last_clipboard = cur_clipboard

                if self.result_start_time and time.time() - self.result_start_time >= self.display_duration:
                    self.show_status("")
                    self.result_start_time = None
                    self.last_result_im = None
                    self.pilots = {}
                    self.last_ship_counts = None

                im = None
                if self.is_local:
                    im = self.create_aggregated_display() if self.aggregated_mode else self.create_pilot_display()
                elif self.is_dscan:
                    im = self.create_dscan_display()

                if im is not None:
                    cv2.imshow(self.win_name, im)
                self.last_result_im = im
                cv2.waitKey(100)
                self.handle_transparency()

        except KeyboardInterrupt:
            logger.info("Exiting...")
            cv2.destroyAllWindows()


def main():
    analyzer = DScanAnalyzer()
    analyzer.start()


if __name__ == "__main__":
    main()
