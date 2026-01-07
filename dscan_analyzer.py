import pyperclip
import time
from typing import Optional, Dict
from config import C
import cv2
import numpy as np
import utils
from global_hotkeys import register_hotkeys, start_checking_hotkeys
import webbrowser
from loguru import logger
import win32gui
import win32api
from pilot_color_classifier import PilotColorClassifier

# Import from services
from services import PilotService, DScanService, PilotData, PilotState
from services.dscan_service import get_dscan_info_url


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
            self.groups.append(
                {'name': grp_name, 'entities': set(entities), 'color': color})
            for entity in entities:
                self.entity_to_group[entity] = {
                    'name': grp_name, 'color': color, 'order': len(self.groups) - 1}

        # Initialize services
        cache_dir = C.get('cache', 'cache')
        stats_provider = C.dscan.get('stats_provider', 'zkill')
        rate_limit_delay = C.dscan.get('rate_limit_retry_delay', 5)
        diff_timeout = C.dscan.get('diff_timeout', 60)

        self.pilot_service = PilotService(
            cache_dir, stats_provider, rate_limit_delay)
        self.dscan_service = DScanService()
        self.diff_timeout = diff_timeout

        pilot_colors_cfg = C.dscan.get('pilot_colors', {})
        self.pilot_classifier = PilotColorClassifier(
            pilot_colors_cfg) if pilot_colors_cfg else PilotColorClassifier.create_default()

        self.pilots: Dict[str, PilotData] = {}
        self.is_local = False
        self.is_dscan = False
        self.aggregated_mode = False
        self.last_clipboard: Optional[str] = None
        self.header_rect: Optional[tuple] = None
        self.hovered_rect: Optional[str] = None
        self.mouse_pos: tuple = (0, 0)
        self.hover_color = tuple(C.dscan.get('hover_color', [80, 80, 80]))

        cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        if self.transparency_on:
            utils.win_transparent(
                'Main HighGUI class', self.win_name, self.transparency, (64, 64, 64))

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
        self.pilot_service.clear_caches()
        logger.info("Caches cleared")

    def handle_transparency(self):
        if self.should_destroy_window:
            cv2.destroyWindow(self.win_name)
            cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
            cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
            cv2.setMouseCallback(self.win_name, self.mouse_callback)
            if self.transparency_on:
                cv2.setWindowProperty(
                    self.win_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
                utils.win_transparent(
                    'Main HighGUI class', self.win_name, self.transparency, (64, 64, 64))
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
            cv2.rectangle(im, (hx - 2, hy - 2), (hx + hw + 2,
                          hy + hh + 2), self.hover_color, 2)
        elif self.hovered_rect in self.char_rects:
            rect, _ = self.char_rects[self.hovered_rect]
            rx, ry, rw, rh = rect
            cv2.rectangle(im, (rx - 2, ry - 2), (rx + rw + 2,
                          ry + rh + 2), self.hover_color, 2)
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
        matched = self.match_pilot_entity(
            pilot, set(self.entity_to_group.keys()))
        return self.entity_to_group.get(matched) if matched else None

    def process_local(self, clipboard_data: str):
        """Process clipboard data as pilot list using PilotService."""
        char_names = self.pilot_service.parse_pilot_list(clipboard_data)
        if not char_names:
            self.show_status("")
            return

        self.pilots = self.pilot_service.lookup_from_cache(char_names)
        self.result_start_time = time.time()
        self.paused_time = 0
        self.pause_start_time = None

        skip_stats = len(char_names) > self.stats_limit
        if skip_stats:
            self.aggregated_mode = True

        self.pilot_service.fetch_missing_data(self.pilots, skip_stats)

    def parse_dscan(self, dscan_data: str):
        """Parse dscan data using DScanService."""
        result = self.dscan_service.parse(dscan_data, self.diff_timeout)
        if result is None or result.is_empty:
            self.show_status("No ships found")
            return

        self.result_start_time = time.time()
        self.paused_time = 0
        self.pause_start_time = None

    def parse_clipboard(self, clipboard_data: str):
        if self.dscan_service.is_dscan_format(clipboard_data):
            if self.dscan_service.is_valid_dscan(clipboard_data):
                self.is_dscan = True
                self.is_local = False
                self.parse_dscan(clipboard_data)
            return

        if self.pilot_service.parse_pilot_list(clipboard_data):
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

            entry = {'name': name[:20], 'pilot': pilot,
                     'link': pilot.stats_link}
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
                    d, k, l = pilot.stats.get('danger', 0), pilot.stats.get(
                        'kills', 0), pilot.stats.get('losses', 0)
                    entry['text'] = f"{entry['name']} | D:{d:.0f} K:{k} L:{l}"
                    entry['color'] = self.pilot_classifier.get_color(
                        pilot.stats)
                    entry['kills'] = k
                else:
                    entry['text'] = f"{entry['name']} | [Cached]"
                    entry['color'] = (200, 200, 200)
                    entry['kills'] = -1
            else:
                entry['text'] = f"{entry['name']} | Unknown"
                entry['color'] = (128, 128, 128)
                entry['kills'] = -2

            display_data.append(entry)

        display_data.sort(key=lambda x: x.get('kills', -2), reverse=True)

        remaining = max(0, self.display_duration - self.get_elapsed_time())
        header = f"{len(display_data)} | {remaining:.0f}s"

        text_lines = [header] + [e['text'] for e in display_data]
        full_text = '\n'.join(text_lines)

        has_groups = any(e.get('group') for e in display_data)
        x_offset = rect_w + 2 if has_groups else 0

        max_w, total_h = utils.get_text_size_withnewline(full_text, (20, 20),
                                                         font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        im = np.full((total_h + 40, max_w + 40 + x_offset, 3),
                     C.dscan.transparency_color, np.uint8)

        header_x = 10 + x_offset
        header_y = 20
        header_w, header_h = cv2.getTextSize(
            header, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
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
                cv2.rectangle(im, (4, start_y), (4 + rect_w, y - 2),
                              entry['group']['color'], -1)
            self.char_rects[entry['name']] = (
                (10 + x_offset, start_y, text_size[0], y - start_y), entry['link'])

        return im

    def create_aggregated_display(self) -> Optional[np.ndarray]:
        if not self.pilots:
            return None

        corp_counts, alliance_counts, group_counts = {}, {}, {
            grp['name']: 0 for grp in self.groups}
        corp_to_alliance = {}
        for pilot in self.pilots.values():
            corp = pilot.corp_name or 'Unknown'
            corp_counts[corp] = corp_counts.get(corp, 0) + 1
            if pilot.alliance_name:
                alliance_counts[pilot.alliance_name] = alliance_counts.get(
                    pilot.alliance_name, 0) + 1
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
        im = np.full((total_h, total_w, 3),
                     C.dscan.transparency_color, np.uint8)

        self.header_rect = (10, 20, header_w, header_h)
        x = 10
        for text, color in header_parts:
            text_w, _ = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
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
        if not self.dscan_service.last_result:
            return None

        ship_diffs = self.dscan_service.get_ship_diffs()
        group_totals = self.dscan_service.get_group_totals()
        group_diffs = self.dscan_service.get_group_diffs()
        total = self.dscan_service.last_result.total_ships

        ship_list = []
        for grp, ships in self.dscan_service.last_result.ship_counts.items():
            for ship, cnt in ships.items():
                ship_list.append((ship, cnt, ship_diffs.get(ship, 0)))

        # Add ships that disappeared
        if self.dscan_service.previous_result:
            cur_ships = {s for ships in self.dscan_service.last_result.ship_counts.values()
                         for s in ships}
            for grp, ships in self.dscan_service.previous_result.ship_counts.items():
                for ship, prev_cnt in ships.items():
                    if ship not in cur_ships:
                        ship_list.append((ship, 0, -prev_cnt))

        # Add groups that disappeared
        if self.dscan_service.previous_result:
            for grp in self.dscan_service.previous_result.ship_counts:
                if grp not in group_totals:
                    group_totals[grp] = 0

        ship_list.sort(key=lambda x: (x[1] == 0, -x[1]))
        sorted_groups = sorted(group_totals.items(),
                               key=lambda x: x[1], reverse=True)

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
        im = np.full((total_h, total_w, 3),
                     C.dscan.transparency_color, np.uint8)

        header_w, header_h = cv2.getTextSize(
            header, cv2.FONT_HERSHEY_SIMPLEX, C.dscan.font_scale, int(C.dscan.font_thickness))[0]
        self.header_rect = (10, 20, header_w, header_h)

        y = 20
        for i, line in enumerate(left_lines):
            if i < 1:
                color = (255, 255, 255)
            elif i - 1 < len(ship_list):
                _, _, diff = ship_list[i - 1]
                color = (0, 255, 0) if diff > 0 else (
                    0, 0, 255) if diff < 0 else (255, 255, 255)
            else:
                color = (255, 255, 255)
            y = utils.draw_text_on_image(im, line, (10, y), color=color,
                                         bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]

        right_x, right_y = left_w + 20, 20
        right_y = utils.draw_text_on_image(im, "Categories:", (right_x, right_y), color=(255, 255, 255),
                                           bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)[3]
        for grp, cnt, grp_diff, text in right_data:
            color = (0, 255, 0) if grp_diff > 0 else (
                0, 0, 255) if grp_diff < 0 else (255, 255, 255)
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
                        self.dscan_service.reset()
                        self.is_local = False
                        self.is_dscan = False

                im = None
                if self.result_start_time:
                    if self.is_local:
                        im = self.create_aggregated_display(
                        ) if self.aggregated_mode else self.create_pilot_display()
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
