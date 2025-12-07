import pyperclip
import time
import copy
import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, List
import asyncio
import aiohttp
import requests
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
from zkill import ZKillStatsProvider, calc_danger
import win32gui
import win32api
from evekill import EveKillStatsProvider
from cache_stats import CacheStatsProvider
from esi import ESIResolver

PILOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9' -]*[A-Za-z0-9]$")


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


def get_dscan_info_url(paste_data: str) -> Optional[str]:
    try:
        ts = int(time.time() * 1000)
        resp = requests.post(f"https://dscan.info/?_={ts}", data={"paste": paste_data}, timeout=10)
        if resp.status_code != 200:
            return None
        txt = resp.text.strip()
        if txt.startswith("OK;"):
            return f"https://dscan.info/v/{txt.split(';')[1]}"
        return None
    except Exception as e:
        logger.info(f"dscan.info request failed: {e}")
        return None


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


class DScanAnalyzer:
    def __init__(self):
        self.ignore = set(C.dscan.get('ignore', []))
        self.display_duration = C.dscan.get('timeout', 10)
        self.stats_limit = C.dscan.get('aggregated_mode_threshold', 50)
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
        self.paused_time = 0
        self.pause_start_time = None

        self.groups = []
        self.entity_to_group = {}
        groups_cfg = C.dscan.get('groups', {})
        for grp_name, grp_data in groups_cfg.items():
            entities = grp_data.get('entities', [])
            color = tuple(grp_data.get('color', [255, 255, 255]))
            self.groups.append({'name': grp_name, 'entities': set(entities), 'color': color})
            for entity in entities:
                self.entity_to_group[entity] = {'name': grp_name, 'color': color, 'order': len(self.groups) - 1}

        cache_dir = C.get('cache', 'cache')
        self.cache = CacheManager(cache_dir)
        self.cache.load_cache()
        self.esi = ESIResolver()

        stats_provider = C.dscan.get('stats_provider', 'zkill')
        rate_limit_delay = C.dscan.get('rate_limit_retry_delay', 5)
        providers = {'zkill': lambda: ZKillStatsProvider(rate_limit_delay), 'evekill': lambda: EveKillStatsProvider(rate_limit_delay), 'cache': CacheStatsProvider}
        self.stats_provider = providers.get(stats_provider, providers['zkill'])()

        self.pilots: Dict[str, PilotData] = {}
        self.pending_tasks: Dict[str, asyncio.Task] = {}
        self.is_local = False
        self.is_dscan = False
        self.last_ship_counts = None
        self.previous_ship_counts = None
        self.last_dscan_time = None
        self.aggregated_mode = False
        self._network_thread: Optional[threading.Thread] = None
        self.last_clipboard: Optional[str] = None
        self.header_rect: Optional[tuple] = None
        self.hovered_rect: Optional[str] = None
        self.mouse_pos: tuple = (0, 0)
        self.hover_color = tuple(C.dscan.get('hover_color', [80, 80, 80]))

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

    def get_elapsed_time(self):
        if not self.result_start_time:
            return 0
        elapsed = time.time() - self.result_start_time - self.paused_time
        if self.pause_start_time:
            elapsed -= time.time() - self.pause_start_time
        return elapsed

    def toggle_transparency(self):
        self.transparency_on = not self.transparency_on
        self.should_destroy_window = True
        if self.transparency_on:
            if self.pause_start_time:
                self.paused_time += time.time() - self.pause_start_time
                self.pause_start_time = None
        else:
            if self.result_start_time and not self.pause_start_time:
                self.pause_start_time = time.time()

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
        self.mouse_pos = (x, y)
        if event == cv2.EVENT_MOUSEMOVE:
            self.update_hover_state(x, y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            if self.header_rect and self.last_clipboard:
                hx, hy, hw, hh = self.header_rect
                if hx <= x <= hx + hw and hy <= y <= hy + hh:
                    url = get_dscan_info_url(self.last_clipboard)
                    if url:
                        webbrowser.open(url)
                    return
            for _, (rect, link) in self.char_rects.items():
                rx, ry, rw, rh = rect
                if rx <= x <= rx + rw and ry <= y <= ry + rh and link:
                    webbrowser.open(link)
                    break

    def get_mouse_pos_in_window(self) -> Optional[tuple]:
        try:
            hwnd = win32gui.FindWindow('Main HighGUI class', self.win_name)
            if not hwnd:
                return None
            cx, cy = win32api.GetCursorPos()
            wx, wy, _, _ = win32gui.GetWindowRect(hwnd)
            return (cx - wx, cy - wy)
        except:
            return None

    def update_hover_state_global(self):
        if not self.transparency_on:
            return
        pos = self.get_mouse_pos_in_window()
        if not pos:
            self.hovered_rect = None
            return
        x, y = pos
        self.update_hover_state(x, y)

    def update_hover_state(self, x: int, y: int):
        new_hovered = None
        if self.header_rect and self.last_clipboard:
            hx, hy, hw, hh = self.header_rect
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                new_hovered = '__header__'
        if not new_hovered:
            for name, (rect, link) in self.char_rects.items():
                if link:
                    rx, ry, rw, rh = rect
                    if rx <= x <= rx + rw and ry <= y <= ry + rh:
                        new_hovered = name
                        break
        self.hovered_rect = new_hovered

    def apply_hover_highlight(self, im: np.ndarray) -> np.ndarray:
        if not self.hovered_rect or self.transparency_on:
            return im
        im = im.copy()
        if self.hovered_rect == '__header__' and self.header_rect:
            hx, hy, hw, hh = self.header_rect
            cv2.rectangle(im, (hx - 2, hy - 2), (hx + hw + 2, hy + hh + 2), self.hover_color, 2)
        elif self.hovered_rect in self.char_rects:
            rect, _ = self.char_rects[self.hovered_rect]
            rx, ry, rw, rh = rect
            cv2.rectangle(im, (rx - 2, ry - 2), (rx + rw + 2, ry + rh + 2), self.hover_color, 2)
        return im

    def match_pilot_entity(self, pilot: PilotData, entities: set) -> Optional[str]:
        for attr in ('name', 'corp_name', 'alliance_name'):
            val = getattr(pilot, attr, None)
            if val and val in entities:
                return val
        return None

    def should_ignore_pilot(self, pilot: PilotData) -> bool:
        return self.match_pilot_entity(pilot, self.ignore) is not None

    def get_pilot_group(self, pilot: PilotData) -> Optional[Dict]:
        matched = self.match_pilot_entity(pilot, set(self.entity_to_group.keys()))
        return self.entity_to_group.get(matched) if matched else None

    async def lookup_pilot_async(self, pilot: PilotData, session: aiohttp.ClientSession, skip_stats: bool = False):
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
                pilot.corp_alliance_resolved = True

            pilot.stats_link = self.stats_provider.get_link(pilot.char_id)

            if skip_stats:
                pilot.state = PilotState.FOUND
                return

            pilot.state = PilotState.SEARCHING_STATS
            stats = await self.stats_provider.get_stats(session, pilot.char_id)
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
            elif stats and stats.get('error') == 'not_found':
                pilot.state = PilotState.NOT_FOUND
            elif stats and stats.get('error') == 'rate_limited':
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.RATE_LIMITED
                pilot.error_msg = f"Retry in {int(stats.get('retry_after', 0))}s"
            else:
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.ERROR
                pilot.error_msg = stats.get('error', 'unknown') if stats else 'unknown'

        except Exception as e:
            logger.info(f"Error looking up pilot {pilot.name}: {e}")
            pilot.state = PilotState.ERROR
            pilot.error_msg = str(e)

    def _apply_esi_cache(self, pilot: PilotData) -> bool:
        if pilot.char_id not in self.esi.char_cache:
            return False
        char_info = self.esi.char_cache[pilot.char_id]
        pilot.corp_id = char_info.get('corporation_id')
        pilot.alliance_id = char_info.get('alliance_id')
        pilot.corp_name = self.esi.id_name_cache.get(pilot.corp_id, 'Unknown') if pilot.corp_id else None
        pilot.alliance_name = self.esi.id_name_cache.get(pilot.alliance_id) if pilot.alliance_id else None
        pilot.corp_alliance_resolved = True
        return True

    def _apply_stats_from_cache(self, pilot: PilotData, name: str, stats_cache: dict):
        if pilot.char_id in stats_cache:
            stats = stats_cache[pilot.char_id]
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
                return True
        preloaded = self.cache.get_char_stats(name)
        if preloaded:
            k, l = preloaded['kills'], preloaded['losses']
            pilot.stats = {'kills': k, 'losses': l, 'danger': calc_danger(k, l)}
            pilot.state = PilotState.CACHE_HIT
            return True
        return False

    def process_cache_lookup(self, names: List[str]) -> Dict[str, PilotData]:
        pilots = {}
        stats_cache = self.stats_provider.client.cache
        for name in names:
            info = self.cache.get_char_info(name)
            if info:
                pilot = PilotData(
                    name=name,
                    state=PilotState.CACHE_HIT,
                    char_id=info['char_id'],
                )
                if not self._apply_esi_cache(pilot):
                    pilot.corp_id = info['corp_id']
                    pilot.alliance_id = info['alliance_id']
                    pilot.corp_name = info['corp_name']
                    pilot.alliance_name = info['alliance_name']
                pilot.stats_link = self.stats_provider.get_link(pilot.char_id)
                self._apply_stats_from_cache(pilot, name, stats_cache)
            elif name in self.esi.name_cache:
                char_id = self.esi.name_cache[name]
                pilot = PilotData(name=name, char_id=char_id, state=PilotState.SEARCHING_STATS)
                pilot.stats_link = self.stats_provider.get_link(char_id)
                self._apply_esi_cache(pilot)
                self._apply_stats_from_cache(pilot, name, stats_cache)
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
        self.paused_time = 0
        self.pause_start_time = None

        pilots_needing_esi = [p for p in self.pilots.values() if p.state == PilotState.SEARCHING_ESI]
        pilots_needing_stats = [p for p in self.pilots.values() if p.state in [PilotState.CACHE_HIT, PilotState.SEARCHING_STATS]]
        pilots_needing_corp_resolve = [p for p in self.pilots.values()
                                       if p.corp_id and not p.corp_alliance_resolved]

        skip_stats = len(char_names) > self.stats_limit
        if skip_stats:
            self.aggregated_mode = True
            for p in pilots_needing_stats:
                p.state = PilotState.FOUND

        if pilots_needing_esi or pilots_needing_corp_resolve or (not skip_stats and pilots_needing_stats):
            self._start_network_fetch(pilots_needing_esi, pilots_needing_stats, skip_stats, pilots_needing_corp_resolve)

    def _start_network_fetch(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData],
                              skip_stats: bool, pilots_corp_resolve: List[PilotData] = None):
        if self._network_thread and self._network_thread.is_alive():
            pass

        def run_fetch():
            asyncio.run(self._fetch_network_data(pilots_esi, pilots_stats, skip_stats, pilots_corp_resolve or []))

        self._network_thread = threading.Thread(target=run_fetch, daemon=True)
        self._network_thread.start()

    async def _fetch_network_data(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData],
                                   skip_stats: bool, pilots_corp_resolve: List[PilotData] = None):
        connector = aiohttp.TCPConnector(limit=50)
        async with aiohttp.ClientSession(connector=connector) as session:
            if pilots_esi:
                esi_tasks = [self.lookup_pilot_async(p, session, skip_stats) for p in pilots_esi]
                await asyncio.gather(*esi_tasks, return_exceptions=True)

            if pilots_corp_resolve:
                corp_tasks = [self.resolve_corp_alliance_async(p, session) for p in pilots_corp_resolve
                              if not p.corp_alliance_resolved]
                if corp_tasks:
                    await asyncio.gather(*corp_tasks, return_exceptions=True)

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
            elif stats and stats.get('error') == 'rate_limited':
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.RATE_LIMITED
                pilot.error_msg = f"Retry in {int(stats.get('retry_after', 0))}s"
            else:
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.ERROR
        except Exception as e:
            pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.ERROR
            pilot.error_msg = str(e)

    async def resolve_corp_alliance_async(self, pilot: PilotData, session: aiohttp.ClientSession):
        if pilot.corp_alliance_resolved:
            return
        try:
            char_info = await self.esi.get_char_info(session, pilot.char_id)
            new_corp_id = char_info.get('corporation_id')
            new_alliance_id = char_info.get('alliance_id')

            ids_to_resolve = [i for i in [new_corp_id, new_alliance_id] if i]
            if ids_to_resolve:
                names = await self.esi.resolve_ids_to_names(session, ids_to_resolve)
                pilot.corp_id = new_corp_id
                pilot.alliance_id = new_alliance_id
                pilot.corp_name = names.get(new_corp_id, 'Unknown')
                pilot.alliance_name = names.get(new_alliance_id) if new_alliance_id else None

            pilot.corp_alliance_resolved = True
        except Exception as e:
            logger.info(f"Error resolving corp/alliance for {pilot.name}: {e}")

    async def parse_dscan(self, dscan_data: str):
        try:
            with open('ships.json', 'r') as f:
                ships = json.load(f)

            cur_time = time.time()
            diff_timeout = C.dscan.get('diff_timeout', 60)
            if self.last_dscan_time and cur_time - self.last_dscan_time > diff_timeout:
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
                self.previous_ship_counts = copy.deepcopy(self.last_ship_counts)

            self.result_start_time = time.time()
            self.paused_time = 0
            self.pause_start_time = None
            self.last_dscan_time = cur_time
            self.last_ship_counts = ship_counts
        except Exception as e:
            logger.info(f"Error parsing dscan: {e}")

    def is_dscan_format(self, data: str) -> bool:
        lines = data.strip().split('\n')
        return bool(lines) and any('\t' in line for line in lines[:5])

    def is_valid_dscan(self, data: str) -> bool:
        lines = data.strip().split('\n')
        if not lines:
            logger.debug("Invalid dscan: empty data")
            return False
        for i, line in enumerate(lines):
            if line and line[0] in ' \t':
                logger.debug(f"Invalid dscan: line {i+1} starts with whitespace: '{line[:30]}...'")
                return False
        return True

    def is_valid_pilot_list(self, data: str) -> bool:
        lines = [line.strip() for line in data.strip().split('\n') if line.strip()]
        if not lines:
            logger.debug("Invalid pilot list: empty data")
            return False
        for line in lines:
            reason = get_invalid_pilot_name_reason(line)
            if reason:
                logger.debug(f"Invalid pilot list: '{line[:30]}' - {reason}")
                return False
        return True

    def parse_clipboard(self, clipboard_data: str):
        if self.is_dscan_format(clipboard_data):
            if self.is_valid_dscan(clipboard_data):
                self.is_dscan = True
                self.is_local = False
                asyncio.run(self.parse_dscan(clipboard_data))
            return

        if self.is_valid_pilot_list(clipboard_data):
            self.is_dscan = False
            self.is_local = True
            self.process_local(clipboard_data)

    def create_pilot_display(self) -> Optional[np.ndarray]:
        if not self.pilots:
            return None

        self.char_rects = {}
        display_data = []
        rect_w = C.dscan.get('group_rect_width', 3)

        for name, pilot in self.pilots.items():
            if self.should_ignore_pilot(pilot):
                continue

            entry = {'name': name[:20], 'pilot': pilot, 'link': pilot.stats_link}
            grp = self.get_pilot_group(pilot)
            entry['group'] = grp

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
            elif pilot.state == PilotState.RATE_LIMITED:
                entry['text'] = f"{entry['name']} | Rate limited"
                entry['color'] = (0, 165, 255)
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

        remaining = max(0, self.display_duration - self.get_elapsed_time())
        header = f"{len(display_data)} | {remaining:.0f}s"

        text_lines = [header] + [e['text'] for e in display_data]
        full_text = '\n'.join(text_lines)

        has_groups = any(e.get('group') for e in display_data)
        x_offset = rect_w + 2 if has_groups else 0

        max_w, total_h = utils.get_text_size_withnewline(full_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        im = np.full((total_h + 40, max_w + 40 + x_offset, 3), C.dscan.transparency_color, np.uint8)

        header_x = 10 + x_offset
        header_y = 20
        header_w, header_h = cv2.getTextSize(header, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
        self.header_rect = (header_x, header_y, header_w, header_h)
        y = utils.draw_text_on_image(im, header, (header_x, header_y), color=(0, 255, 0),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        for entry in display_data:
            text_size, _ = cv2.getTextSize(entry['text'], cv2.FONT_HERSHEY_SIMPLEX,
                C.dscan.font_scale, int(C.dscan.font_thickness))
            start_y = y
            y = utils.draw_text_on_image(im, entry['text'], (10 + x_offset, y), color=entry['color'],
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]
            if entry.get('group'):
                cv2.rectangle(im, (4, start_y), (4 + rect_w, y - 2), entry['group']['color'], -1)
            self.char_rects[entry['name']] = ((10 + x_offset, start_y, text_size[0], y - start_y), entry['link'])

        return im

    def create_aggregated_display(self) -> Optional[np.ndarray]:
        if not self.pilots:
            return None

        corp_counts, alliance_counts, group_counts = {}, {}, {grp['name']: 0 for grp in self.groups}
        corp_to_alliance = {}
        for pilot in self.pilots.values():
            corp = pilot.corp_name or 'Unknown'
            corp_counts[corp] = corp_counts.get(corp, 0) + 1
            if pilot.alliance_name:
                alliance_counts[pilot.alliance_name] = alliance_counts.get(pilot.alliance_name, 0) + 1
                corp_to_alliance[corp] = pilot.alliance_name
            grp = self.get_pilot_group(pilot)
            if grp:
                group_counts[grp['name']] += 1

        def get_entity_group(name):
            if name in self.entity_to_group:
                return self.entity_to_group[name]
            alliance = corp_to_alliance.get(name)
            return self.entity_to_group.get(alliance) if alliance else None

        def sort_key(item):
            name, cnt = item
            grp = get_entity_group(name)
            return (0, grp['order'], -cnt) if grp else (1, -cnt, name)

        sorted_alliances = sorted(alliance_counts.items(), key=sort_key)
        sorted_corps = sorted(corp_counts.items(), key=sort_key)

        remaining = max(0, self.display_duration - self.get_elapsed_time())

        total_pilots = len(self.pilots)
        header_parts = [(f"{total_pilots} | {remaining:.0f}s", (0, 255, 0))]
        for grp in self.groups:
            cnt = group_counts.get(grp['name'], 0)
            if cnt > 0:
                header_parts.append((f" {grp['name']}:{cnt}", grp['color']))

        left_lines_data = [("Alliances:", (255, 255, 255))]
        for a, c in sorted_alliances:
            grp = self.entity_to_group.get(a)
            color = grp['color'] if grp else (255, 255, 255)
            left_lines_data.append((f"  {a}: {c}", color))
        if not sorted_alliances:
            left_lines_data.append(("  None", (128, 128, 128)))

        right_lines_data = [("Corporations:", (255, 255, 255))]
        for c, n in sorted_corps:
            grp = get_entity_group(c)
            color = grp['color'] if grp else (255, 255, 255)
            right_lines_data.append((f"  {c}: {n}", color))

        header_text = ''.join(p[0] for p in header_parts)
        left_text = '\n'.join(d[0] for d in left_lines_data)
        right_text = '\n'.join(d[0] for d in right_lines_data)

        header_w, header_h = utils.get_text_size_withnewline(header_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        left_w, left_h = utils.get_text_size_withnewline(left_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        right_w, right_h = utils.get_text_size_withnewline(right_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        content_w = left_w + right_w + 30
        total_w = max(header_w + 20, content_w)
        total_h = header_h + max(left_h, right_h) + 40
        im = np.full((total_h, total_w, 3), C.dscan.transparency_color, np.uint8)

        self.header_rect = (10, 20, header_w, header_h)
        x = 10
        for text, color in header_parts:
            text_w, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
            utils.draw_text_on_image(im, text, (x, 20), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
            x += text_w

        y = 20 + header_h
        for text, color in left_lines_data:
            y = utils.draw_text_on_image(im, text, (10, y), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        y = 20 + header_h
        for text, color in right_lines_data:
            y = utils.draw_text_on_image(im, text, (left_w + 20, y), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

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
            cur_ships = {s for ships in self.last_ship_counts.values() for s in ships}
            for grp, ships in self.previous_ship_counts.items():
                for ship, prev_cnt in ships.items():
                    if ship not in cur_ships:
                        ship_diffs[ship] = -prev_cnt

        ship_list, group_totals, total = [], {}, 0
        for grp, ships in self.last_ship_counts.items():
            grp_total = sum(ships.values())
            group_totals[grp] = grp_total
            total += grp_total
            for ship, cnt in ships.items():
                ship_list.append((ship, cnt, ship_diffs.get(ship, 0)))

        if self.previous_ship_counts:
            cur_ships = {s for ships in self.last_ship_counts.values() for s in ships}
            for grp, ships in self.previous_ship_counts.items():
                for ship, prev_cnt in ships.items():
                    if ship not in cur_ships:
                        ship_list.append((ship, 0, -prev_cnt))

        group_diffs = {}
        if self.previous_ship_counts:
            for grp, cur_total in group_totals.items():
                prev_total = sum(self.previous_ship_counts.get(grp, {}).values())
                if cur_total != prev_total:
                    group_diffs[grp] = cur_total - prev_total
            for grp in self.previous_ship_counts:
                if grp not in group_totals:
                    prev_total = sum(self.previous_ship_counts[grp].values())
                    group_diffs[grp] = -prev_total
                    group_totals[grp] = 0

        ship_list.sort(key=lambda x: (x[1] == 0, -x[1]))
        sorted_groups = sorted(group_totals.items(), key=lambda x: x[1], reverse=True)

        remaining = max(0, self.display_duration - self.get_elapsed_time())
        header = f"{total} | {remaining:.0f}s"

        left_lines = [header]
        for ship, cnt, diff in ship_list:
            diff_str = f" (+{diff})" if diff > 0 else f" ({diff})" if diff < 0 else ""
            left_lines.append(f"{ship}: {cnt}{diff_str}")

        right_data = []
        for grp, cnt in sorted_groups:
            grp_diff = group_diffs.get(grp, 0)
            diff_str = f" (+{grp_diff})" if grp_diff > 0 else f" ({grp_diff})" if grp_diff < 0 else ""
            right_data.append((grp, cnt, grp_diff, f"{grp}: {cnt}{diff_str}"))

        left_text = '\n'.join(left_lines)
        right_text = '\n'.join(["Categories:"] + [d[3] for d in right_data])
        left_w, left_h = utils.get_text_size_withnewline(left_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        right_w, right_h = utils.get_text_size_withnewline(right_text, (20, 20),
            font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        total_w, total_h = left_w + right_w + 30, max(left_h, right_h) + 40
        im = np.full((total_h, total_w, 3), C.dscan.transparency_color, np.uint8)

        header_w, header_h = cv2.getTextSize(header, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
        self.header_rect = (10, 20, header_w, header_h)

        y = 20
        for i, line in enumerate(left_lines):
            if i < 1:
                color = (255, 255, 255)
            elif i - 1 < len(ship_list):
                _, _, diff = ship_list[i - 1]
                color = (0, 255, 0) if diff > 0 else (0, 0, 255) if diff < 0 else (255, 255, 255)
            else:
                color = (255, 255, 255)
            y = utils.draw_text_on_image(im, line, (10, y), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        right_x, right_y = left_w + 20, 20
        right_y = utils.draw_text_on_image(im, "Categories:", (right_x, right_y), color=(255, 255, 255),
            bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]
        for grp, cnt, grp_diff, text in right_data:
            color = (0, 255, 0) if grp_diff > 0 else (0, 0, 255) if grp_diff < 0 else (255, 255, 255)
            right_y = utils.draw_text_on_image(im, text, (right_x, right_y), color=color,
                bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

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
                    utils.tick()
                    self.parse_clipboard(cur_clipboard)
                    self.last_result_total_time = utils.tock()
                    self.last_clipboard = cur_clipboard
                    last_clipboard = cur_clipboard

                if self.result_start_time and self.transparency_on:
                    if self.get_elapsed_time() >= self.display_duration:
                        self.show_status("")
                        self.result_start_time = None
                        self.last_result_im = None
                        self.pilots = {}
                        self.last_ship_counts = None
                        self.is_local = False
                        self.is_dscan = False

                im = None
                if self.result_start_time:
                    if self.is_local:
                        im = self.create_aggregated_display() if self.aggregated_mode else self.create_pilot_display()
                    elif self.is_dscan:
                        im = self.create_dscan_display()

                if im is not None:
                    disp_im = self.apply_hover_highlight(im)
                    cv2.imshow(self.win_name, disp_im)
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
