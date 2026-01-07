import dearpygui.dearpygui as dpg
import pyperclip
import webbrowser
import time
from global_hotkeys import register_hotkeys
from overlay import OverlayWindow, WindowManager
from config import C
from services import PilotService, DScanService, PilotState
from services.dscan_service import get_dscan_info_url
from pilot_color_classifier import PilotColorClassifier

def bgr_to_rgb(color):
    return (color[2], color[1], color[0])

WIN_TITLE = "dscan_analyzer"
TAG_W = 4
DEFAULT_ALLIANCE_COLOR = (200, 200, 200)
DIFF_POSITIVE_COLOR = (0, 255, 0)
DIFF_NEGATIVE_COLOR = (255, 80, 80)
DIFF_NEUTRAL_COLOR = (200, 200, 200)

STATE_COLORS = {
    PilotState.SEARCHING_ESI: (255, 255, 0),
    PilotState.SEARCHING_STATS: (255, 255, 0),
    PilotState.NOT_FOUND: (128, 128, 128),
    PilotState.ERROR: (255, 0, 0),
    PilotState.RATE_LIMITED: (255, 165, 0),
}

STATE_LABELS = {
    PilotState.SEARCHING_ESI: "Resolving...",
    PilotState.SEARCHING_STATS: "Fetching stats...",
    PilotState.NOT_FOUND: "Not found",
    PilotState.RATE_LIMITED: "Rate limited",
}

class DScanAnalyzer:
    def __init__(self):
        cache_dir = C.get('cache', 'cache')
        dscan_cfg = C.dscan
        
        self.pilot_svc = PilotService(
            cache_dir, 
            dscan_cfg.get('stats_provider', 'zkill'),
            dscan_cfg.get('rate_limit_retry_delay', 5),
            dscan_cfg.get('aggregated_mode_threshold', 50)
        )
        self.dscan_svc = DScanService()
        self.win_mgr = WindowManager(WIN_TITLE, C, cfg_key='dscan_winstate')
        self.overlay = OverlayWindow(WIN_TITLE, on_toggle=self.on_overlay_toggle)
        self.last_clip = ""
        self.mode = None
        self.themes = {}
        
        self.timeout_duration = dscan_cfg.get('timeout', 10)
        self.diff_timeout = dscan_cfg.get('diff_timeout', 60)
        self.result_start_time = None
        self.paused_time = 0
        self.pause_start_time = None
        self.timeout_expired = False
        
        pilot_colors_cfg = dscan_cfg.get('pilot_colors', {})
        self.pilot_classifier = PilotColorClassifier(pilot_colors_cfg) if pilot_colors_cfg else PilotColorClassifier.create_default()
        
        self.groups = {
            entity: bgr_to_rgb(tuple(grp.get('color', [255, 255, 255])))
            for grp in dscan_cfg.get('groups', {}).values()
            for entity in grp.get('entities', [])
        }
        
        self.group_cfg = {
            name: {
                'entities': set(grp.get('entities', [])),
                'color': bgr_to_rgb(tuple(grp.get('color', [255, 255, 255])))
            }
            for name, grp in dscan_cfg.get('groups', {}).items()
        }
        
        self.ignore_list = set(dscan_cfg.get('ignore', []))
        
        self.aggr_mode = False
        self.aggr_mode_manual = None
        self.aggr_threshold = dscan_cfg.get('aggregated_mode_threshold', 50)
        self.aggr_hotkey = dscan_cfg.get('hotkey_mode', 'alt+shift+m')
        self.aggr_toggle_requested = False
        self.collapse_state = {"corps": False, "dscan_groups": {}}
        self.alliance_colors = {}
        self.alliance_ids = {}
        self.corp_ids = {}
    
    def on_overlay_toggle(self, enabled):
        if enabled:
            if self.pause_start_time:
                self.paused_time += time.time() - self.pause_start_time
                self.pause_start_time = None
        else:
            if self.result_start_time and not self.pause_start_time:
                self.pause_start_time = time.time()
            self.timeout_expired = False

    def get_elapsed_time(self):
        if not self.result_start_time:
            return 0
        elapsed = time.time() - self.result_start_time - self.paused_time
        if self.pause_start_time:
            elapsed -= time.time() - self.pause_start_time
        return elapsed
    
    def get_remaining_time(self):
        return max(0, self.timeout_duration - self.get_elapsed_time())
    
    def setup_gui(self):
        dpg.create_context()
        
        with dpg.font_registry():
            self.font = dpg.add_font(C.dscan.font, int(16 * self.win_mgr.dpi_scale))
        dpg.bind_font(self.font)
        
        win_x, win_y, win_w, win_h = self.win_mgr.load()
        dpg.create_viewport(title=WIN_TITLE, width=win_w, height=win_h, always_on_top=True,
                            clear_color=self.overlay.colorkey_rgba, x_pos=win_x, y_pos=win_y)
        dpg.setup_dearpygui()
        
        with dpg.window(tag="main", no_title_bar=True, no_move=True, no_resize=True,
                        no_background=True, no_scrollbar=True):
            with dpg.theme(tag="no_border"):
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
            dpg.bind_item_theme("main", "no_border")
        
        self._setup_click_handler()
        self._setup_aggr_hotkey()
        
        dpg.set_primary_window("main", True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        self.win_mgr.apply()
    
    def _setup_click_handler(self):
        with dpg.handler_registry(tag="global_click"):
            dpg.add_mouse_click_handler(button=dpg.mvMouseButton_Left, callback=self._on_global_click)
    
    def _on_global_click(self, sender, app_data):
        for tag in dpg.get_all_items():
            if not dpg.does_item_exist(tag):
                continue
            try:
                if not dpg.is_item_hovered(tag):
                    continue
            except:
                continue
            user_data = dpg.get_item_user_data(tag)
            if not user_data:
                continue
            action, data = user_data
            if action == "pilot":
                dpg.set_value(tag, False)
                webbrowser.open(data)
            elif action == "header":
                dpg.set_value(tag, False)
                if url := get_dscan_info_url(self.last_clip):
                    webbrowser.open(url)
            elif action == "alliance":
                dpg.set_value(tag, False)
                webbrowser.open(f"https://zkillboard.com/alliance/{data}/")
            elif action == "corp":
                dpg.set_value(tag, False)
                webbrowser.open(f"https://zkillboard.com/corporation/{data}/")
            break

    def _setup_aggr_hotkey(self):
        bindings = [[self.aggr_hotkey, None, self._request_aggr_toggle, True]]
        register_hotkeys(bindings)
    
    def _request_aggr_toggle(self):
        self.aggr_toggle_requested = True
    
    def process_aggr_hotkey(self):
        if not self.aggr_toggle_requested:
            return False
        self.aggr_toggle_requested = False
        self.aggr_mode_manual = not self.aggr_mode if self.aggr_mode_manual is None else not self.aggr_mode_manual
        return True
    
    def _get_theme(self, key, component, colors):
        if key not in self.themes:
            with dpg.theme() as theme:
                with dpg.theme_component(component):
                    for col_type, col_val in colors:
                        dpg.add_theme_color(col_type, col_val)
            self.themes[key] = theme
        return self.themes[key]
    
    def _text_theme(self, color):
        return self._get_theme(color, dpg.mvText, [(dpg.mvThemeCol_Text, color)])
    
    def _selectable_theme(self, color, hover=False):
        key = f"sel_{color}_{hover}"
        bg = tuple(self.overlay.colorkey)
        hover_bg = (80, 80, 80, 150) if hover else bg
        return self._get_theme(key, dpg.mvSelectable, [
            (dpg.mvThemeCol_Text, color),
            (dpg.mvThemeCol_Header, bg),
            (dpg.mvThemeCol_HeaderHovered, hover_bg),
            (dpg.mvThemeCol_HeaderActive, hover_bg),
        ])
    
    def _header_theme(self, color=None):
        key = f"hdr_{color}"
        bg = tuple(self.overlay.colorkey)
        colors = [(dpg.mvThemeCol_Header, bg), (dpg.mvThemeCol_HeaderHovered, bg), (dpg.mvThemeCol_HeaderActive, bg)]
        if color:
            colors.insert(0, (dpg.mvThemeCol_Text, color))
        return self._get_theme(key, dpg.mvCollapsingHeader, colors)

    def get_pilot_tag_color(self, pilot):
        return next(
            (self.groups[v] for attr in ('name', 'corp_name', 'alliance_name') 
             if (v := getattr(pilot, attr, None)) and v in self.groups),
            None
        )
    
    def get_pilot_color(self, pilot):
        if pilot.state in STATE_COLORS:
            return STATE_COLORS[pilot.state]
        if pilot.state in (PilotState.CACHE_HIT, PilotState.FOUND):
            return bgr_to_rgb(self.pilot_classifier.get_color(pilot.stats))
        return (200, 200, 200)
    
    def format_pilot(self, name, pilot):
        if pilot.state == PilotState.ERROR:
            return f"{name} | {pilot.error_msg or 'Error'}"
        if pilot.state in STATE_LABELS:
            return f"{name} | {STATE_LABELS[pilot.state]}"
        if pilot.state in (PilotState.CACHE_HIT, PilotState.FOUND) and pilot.stats:
            s = pilot.stats
            return f"{name} | D:{s.get('danger', 0):.0f} K:{s.get('kills', 0)} L:{s.get('losses', 0)}"
        return f"{name} | {pilot.state.name}"
    
    def _is_ignored(self, pilot):
        return (pilot.name in self.ignore_list or 
                pilot.corp_name in self.ignore_list or 
                pilot.alliance_name in self.ignore_list)
    
    def _save_collapse_state(self):
        if dpg.does_item_exist("aggr_corp_header"):
            self.collapse_state["corps"] = dpg.get_value("aggr_corp_header")
        for i in range(100):
            tag = f"aggr_alliance_corps_{i}"
            if dpg.does_item_exist(tag):
                label = dpg.get_item_label(tag)
                alliance = label.rsplit(":", 1)[0] if ":" in label else label
                self.collapse_state[alliance] = dpg.get_value(tag)
        if dpg.does_item_exist("dscan_groups_header"):
            if "dscan_groups" not in self.collapse_state:
                self.collapse_state["dscan_groups"] = {}
            self.collapse_state["dscan_groups"]["main"] = dpg.get_value("dscan_groups_header")
        for j in range(50):
            tag = f"dscan_grp_{j}"
            if dpg.does_item_exist(tag):
                label = dpg.get_item_label(tag)
                grp = label.rsplit(":", 1)[0].strip() if ":" in label else label
                grp = grp.split("(")[0].strip() if "(" in grp else grp
                if "dscan_groups" not in self.collapse_state:
                    self.collapse_state["dscan_groups"] = {}
                self.collapse_state["dscan_groups"][grp] = dpg.get_value(tag)

    def render_pilots(self):
        if dpg.does_item_exist("dscan_content"):
            dpg.delete_item("dscan_content")
        
        pilots = self.pilot_svc.get_pilots()
        visible = [(n, p) for n, p in pilots.items() 
                   if p.state != PilotState.NOT_FOUND or p.char_id is not None]
        
        pilot_cnt = len(visible)
        auto_aggr = pilot_cnt > self.aggr_threshold
        self.aggr_mode = self.aggr_mode_manual if self.aggr_mode_manual is not None else auto_aggr
        
        if self.aggr_mode:
            self.render_pilots_aggregated(visible)
        else:
            visible = [(n, p) for n, p in visible if not self._is_ignored(p)]
            self.render_pilots_normal(visible)
    
    def render_pilots_normal(self, visible):
        self._save_collapse_state()
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        
        remaining = self.get_remaining_time()
        if self.overlay.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.overlay.is_overlay_mode():
            return
        
        with dpg.group(tag="pilot_list", parent="main"):
            dpg.add_selectable(label=f"{len(visible)} | {remaining:.0f}s", user_data=("header", None))
            dpg.bind_item_theme(dpg.last_item(), self._selectable_theme((0, 255, 0), hover=True))
            
            for i, (name, pilot) in enumerate(visible):
                row_h = dpg.get_text_size(name)[1]
                tag_color = self.get_pilot_tag_color(pilot)
                label = self.format_pilot(name, pilot)
                rect_fill = tag_color or (0, 0, 0, 0)
                
                with dpg.group(horizontal=True):
                    with dpg.drawlist(width=TAG_W, height=row_h):
                        dpg.draw_rectangle([0, 0], [TAG_W, row_h], fill=rect_fill, color=rect_fill)
                    dpg.add_spacer(width=4)
                    link = pilot.stats_link
                    dpg.add_selectable(label=label, user_data=("pilot", link) if link else None)
                    dpg.bind_item_theme(dpg.last_item(), self._selectable_theme(self.get_pilot_color(pilot), hover=True))

    def render_pilots_aggregated(self, visible):
        self._save_collapse_state()
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        
        remaining = self.get_remaining_time()
        if self.overlay.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.overlay.is_overlay_mode():
            return
        
        alliance_cnt, corps_by_alliance, no_alliance_corps, grp_cnt = self._aggregate_pilots(visible)
        total = len(visible)
        
        with dpg.group(tag="aggr_content", parent="main"):
            dpg.add_selectable(label=f"{total} | {remaining:.0f}s", user_data=("header", None))
            dpg.bind_item_theme(dpg.last_item(), self._selectable_theme((0, 255, 0), hover=True))
            
            if any(grp_cnt.values()):
                with dpg.group(horizontal=True):
                    for grp_name, cnt in grp_cnt.items():
                        if cnt > 0:
                            color = self.group_cfg[grp_name]['color']
                            dpg.add_text(f"{grp_name}: {cnt}  ")
                            dpg.bind_item_theme(dpg.last_item(), self._text_theme(color))
            
            
            sorted_alliances = sorted(alliance_cnt.items(), key=lambda x: (x[0] == "No Alliance", -x[1]))
            alliance_labels = [f"  {'[No Alliance]' if a == 'No Alliance' else a}: {c}" for a, c in sorted_alliances]
            max_w = max((dpg.get_text_size(lbl)[0] for lbl in alliance_labels), default=100) + 20
            
            with dpg.group(horizontal=True):
                with dpg.group(width=max_w):
                    dpg.add_text("Alliances:")
                    dpg.bind_item_theme(dpg.last_item(), self._text_theme((255, 255, 0)))
                    
                    for alliance, cnt in sorted_alliances:
                        display = "[No Alliance]" if alliance == "No Alliance" else alliance
                        color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                        alliance_id = self.alliance_ids.get(alliance)
                        if alliance_id:
                            dpg.add_selectable(label=f"  {display}: {cnt}", user_data=("alliance", alliance_id))
                            dpg.bind_item_theme(dpg.last_item(), self._selectable_theme(color, hover=True))
                        else:
                            dpg.add_text(f"  {display}: {cnt}")
                            dpg.bind_item_theme(dpg.last_item(), self._text_theme(color))
                
                with dpg.group():
                    is_open = self.collapse_state.get("corps", False)
                    with dpg.collapsing_header(label="Corporations", default_open=is_open, tag="aggr_corp_header"):
                        dpg.bind_item_theme(dpg.last_item(), self._header_theme())
                        
                        sorted_corps = sorted(corps_by_alliance.items(), key=lambda x: -alliance_cnt.get(x[0], 0))
                        for j, (alliance, corps) in enumerate(sorted_corps):
                            corps = sorted(corps, key=lambda x: -x["count"])
                            display = "[No Alliance]" if alliance == "No Alliance" else alliance
                            color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                            alliance_open = self.collapse_state.get(alliance, False)
                            alliance_total = alliance_cnt.get(alliance, 0)
                            with dpg.collapsing_header(label=f"{display}: {alliance_total}", default_open=alliance_open, tag=f"aggr_alliance_corps_{j}", indent=10):
                                dpg.bind_item_theme(dpg.last_item(), self._header_theme(color))
                                for c in corps:
                                    corp_id = self.corp_ids.get(c['name'])
                                    if corp_id:
                                        dpg.add_selectable(label=f"  {c['name']}: {c['count']}", user_data=("corp", corp_id))
                                        dpg.bind_item_theme(dpg.last_item(), self._selectable_theme(color, hover=True))
                                    else:
                                        dpg.add_text(f"  {c['name']}: {c['count']}")
                                        dpg.bind_item_theme(dpg.last_item(), self._text_theme(color))
                        
                        for c in sorted(no_alliance_corps, key=lambda x: -x["count"]):
                            corp_id = self.corp_ids.get(c['name'])
                            if corp_id:
                                dpg.add_selectable(label=f"  {c['name']}: {c['count']}", user_data=("corp", corp_id))
                                dpg.bind_item_theme(dpg.last_item(), self._selectable_theme(DEFAULT_ALLIANCE_COLOR, hover=True))
                            else:
                                dpg.add_text(f"  {c['name']}: {c['count']}")
                                dpg.bind_item_theme(dpg.last_item(), self._text_theme(DEFAULT_ALLIANCE_COLOR))

    def _aggregate_pilots(self, visible):
        alliance_cnt = {}
        corp_cnt = {}
        pilot_alliances = {}
        grp_cnt = {name: 0 for name in self.group_cfg}
        
        for name, pilot in visible:
            alliance = pilot.alliance_name or "No Alliance"
            corp = pilot.corp_name or "Unknown Corp"
            
            alliance_cnt[alliance] = alliance_cnt.get(alliance, 0) + 1
            corp_cnt[corp] = corp_cnt.get(corp, 0) + 1
            pilot_alliances[corp] = alliance
            
            if pilot.alliance_id and pilot.alliance_name:
                self.alliance_ids[pilot.alliance_name] = pilot.alliance_id
            if pilot.corp_id and pilot.corp_name:
                self.corp_ids[pilot.corp_name] = pilot.corp_id
            
            if alliance not in self.alliance_colors and pilot.alliance_name:
                if color := self.groups.get(pilot.alliance_name):
                    self.alliance_colors[alliance] = color
            
            for grp_name, grp_data in self.group_cfg.items():
                if (pilot.name in grp_data['entities'] or 
                    pilot.corp_name in grp_data['entities'] or 
                    pilot.alliance_name in grp_data['entities']):
                    grp_cnt[grp_name] += 1
                    break
        
        corps_by_alliance = {}
        no_alliance_corps = []
        
        for corp, cnt in corp_cnt.items():
            alliance = pilot_alliances.get(corp, "No Alliance")
            corp_data = {"name": corp, "count": cnt}
            if alliance and alliance != "No Alliance":
                corps_by_alliance.setdefault(alliance, []).append(corp_data)
            else:
                no_alliance_corps.append(corp_data)
        
        return alliance_cnt, corps_by_alliance, no_alliance_corps, grp_cnt

    def render_dscan(self):
        res = self.dscan_svc.last_result
        if not res:
            return
        
        self._save_collapse_state()
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        if dpg.does_item_exist("dscan_content"):
            dpg.delete_item("dscan_content")
        
        remaining = self.get_remaining_time()
        if self.overlay.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.overlay.is_overlay_mode():
            return
        
        ship_diffs = self.dscan_svc.get_ship_diffs()
        grp_totals = self.dscan_svc.get_group_totals()
        grp_diffs = self.dscan_svc.get_group_diffs()
        
        ship_list = []
        for grp, ships in res.ship_counts.items():
            for ship, cnt in ships.items():
                ship_list.append((ship, cnt, ship_diffs.get(ship, 0), grp))
        
        if self.dscan_svc.previous_result:
            cur_ships = {s for ships in res.ship_counts.values() for s in ships}
            for grp, ships in self.dscan_svc.previous_result.ship_counts.items():
                for ship, prev_cnt in ships.items():
                    if ship not in cur_ships:
                        ship_list.append((ship, 0, -prev_cnt, grp))
            for grp in self.dscan_svc.previous_result.ship_counts:
                if grp not in grp_totals:
                    grp_totals[grp] = 0
        
        ship_list.sort(key=lambda x: (x[1] == 0, -x[1]))
        sorted_grps = sorted(grp_totals.items(), key=lambda x: -x[1])
        
        ships_by_grp = {}
        for ship, cnt, diff, grp in ship_list:
            ships_by_grp.setdefault(grp, []).append((ship, cnt, diff))
        
        def diff_color(d):
            return DIFF_POSITIVE_COLOR if d > 0 else DIFF_NEGATIVE_COLOR if d < 0 else DIFF_NEUTRAL_COLOR
        
        def diff_str(d):
            return f" (+{d})" if d > 0 else f" ({d})" if d < 0 else ""
        
        with dpg.group(tag="dscan_content", parent="main"):
            dpg.add_selectable(label=f"{res.total_ships} | {remaining:.0f}s", user_data=("header", None))
            dpg.bind_item_theme(dpg.last_item(), self._selectable_theme((0, 255, 0), hover=True))
            
            with dpg.group(horizontal=True):
                with dpg.group(width=200):
                    dpg.add_spacer(height=dpg.get_text_size("X")[1])
                    for ship, cnt, diff, _ in ship_list[:30]:
                        dpg.add_text(f"  {ship}: {cnt}{diff_str(diff)}")
                        dpg.bind_item_theme(dpg.last_item(), self._text_theme(diff_color(diff)))
                
                with dpg.group():
                    is_open = self.collapse_state.get("dscan_groups", {}).get("main", True)
                    with dpg.collapsing_header(label="Categories", default_open=is_open, tag="dscan_groups_header"):
                        dpg.bind_item_theme(dpg.last_item(), self._header_theme())
                        
                        for j, (grp, cnt) in enumerate(sorted_grps):
                            grp_diff = grp_diffs.get(grp, 0)
                            color = diff_color(grp_diff)
                            grp_open = self.collapse_state.get("dscan_groups", {}).get(grp, False)
                            with dpg.collapsing_header(label=f"{grp}: {cnt}{diff_str(grp_diff)}", default_open=grp_open, tag=f"dscan_grp_{j}", indent=10):
                                dpg.bind_item_theme(dpg.last_item(), self._header_theme(color))
                                for ship, ship_cnt, ship_diff in ships_by_grp.get(grp, []):
                                    dpg.add_text(f"  {ship}: {ship_cnt}{diff_str(ship_diff)}")
                                    dpg.bind_item_theme(dpg.last_item(), self._text_theme(diff_color(ship_diff)))

    def check_clipboard(self):
        try:
            clip = pyperclip.paste()
        except:
            return
        
        if not clip or clip == self.last_clip:
            return
        
        self.last_clip = clip
        
        if self.dscan_svc.is_dscan_format(clip) and self.dscan_svc.is_valid_dscan(clip) and self.dscan_svc.parse(clip, self.diff_timeout):
            self.set_mode('dscan')
        elif self.pilot_svc.set_pilots(clip):
            self.set_mode('pilots')
    
    def set_mode(self, new_mode):
        if self.mode != new_mode:
            self.clear_display()
        self.mode = new_mode
        self.reset_timeout()
    
    def clear_display(self):
        for tag in ("pilot_list", "aggr_content", "dscan_content"):
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
    
    def reset_timeout(self):
        self.result_start_time = time.time()
        self.paused_time = 0
        self.pause_start_time = None
        self.timeout_expired = False
        if not self.overlay.is_overlay_mode():
            self.pause_start_time = time.time()
    
    def run_loop(self):
        while dpg.is_dearpygui_running():
            self.overlay.process_hotkey()
            self.process_aggr_hotkey()
            self.win_mgr.check_and_save()
            self.check_clipboard()
            
            if self.mode == 'pilots':
                self.render_pilots()
            elif self.mode == 'dscan':
                self.render_dscan()
            
            dpg.render_dearpygui_frame()
    
    def start(self):
        self.setup_gui()
        self.run_loop()
        self.overlay.cleanup()
        dpg.destroy_context()

def main():
    DScanAnalyzer().start()

if __name__ == "__main__":
    main()
