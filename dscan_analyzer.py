import dearpygui.dearpygui as dpg
import pyperclip
import webbrowser
import time
from global_hotkeys import register_hotkeys
from overlay import OverlayManager
from config import C, dict2attrdict
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
        
        bg_color_cfg = dscan_cfg.get('bg_color', None)
        bg_color = tuple(bg_color_cfg) if bg_color_cfg else None
        
        self.mgr = OverlayManager(
            WIN_TITLE, C, win_key='dscan_winstate', ui_key='dscan_uistate',
            bg_color=bg_color,
            hotkey_overlay=dscan_cfg.get('hotkey_overlay'),
            hotkey_clickthrough=dscan_cfg.get('hotkey_clickthrough'),
            hotkey_transparent=dscan_cfg.get('hotkey_transparent'),
            on_toggle=self.on_overlay_toggle
        )
        self.last_clip = ""
        self.mode = None
        self.themes = {}
        self._load_ui_scale()
        
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
        self.collapse_state = {"corps": False, "dscan_groups": {"main": True}}
        self.alliance_colors = {}
        self.alliance_ids = {}
        self.corp_ids = {}
    
    def on_overlay_toggle(self):
        if self.mgr.overlay:
            if self.pause_start_time:
                self.paused_time += time.time() - self.pause_start_time
                self.pause_start_time = None
        else:
            if self.result_start_time and not self.pause_start_time:
                self.pause_start_time = time.time()
            self.timeout_expired = False
        self._update_zoom_slider_visibility()
        self.themes.clear()
    
    def _update_bg_color(self):
        dpg.set_viewport_clear_color(self.mgr.colorkey_rgba)

    def _load_ui_scale(self):
        state = C.get('dscan_uistate', {})
        self.ui_scale = float(state.get('scale', 1.0))
    
    def _save_ui_scale(self):
        state = C.get('dscan_uistate', {})
        state['scale'] = self.ui_scale
        C.dscan_uistate = dict2attrdict(state)
        C.write(['dscan_uistate'], 'config.state.yaml')
    
    def _create_scaled_font(self, scale):
        if dpg.does_item_exist("font_registry"):
            return
        with dpg.font_registry(tag="font_registry"):
            with dpg.font(C.dscan.font, self.base_font_size) as self.font:
                dpg.add_font_range(0x25A0, 0x25C0)
        dpg.bind_font(self.font)
    
    def _create_zoom_slider(self):
        self.slider_h = None
        with dpg.group(tag="zoom_container", parent="main"):
            dpg.add_slider_float(
                tag="zoom_slider",
                default_value=self.ui_scale,
                min_value=0.5,
                max_value=2.0,
                width=-1,
                format="",
                callback=self._on_zoom_change
            )
    
    def _on_zoom_change(self, sender, val):
        self.ui_scale = val
        dpg.set_global_font_scale(val)
        self.slider_h = None
        self._save_ui_scale()
        self._auto_resize()
    
    def _auto_resize(self, force=False):
        content_tag = None
        for tag in ("pilot_list", "aggr_content", "dscan_content"):
            if dpg.does_item_exist(tag):
                content_tag = tag
                break
        if not content_tag:
            return
        
        size = dpg.get_item_rect_size(content_tag)
        if not size or size[0] <= 0:
            return
        w = int(size[0]) + 50
        
        if w <= 0:
            return
        cur_w = dpg.get_viewport_width()
        if cur_w != w:
            dpg.set_viewport_width(w)
    
    def _update_zoom_slider_visibility(self):
        if not dpg.does_item_exist("zoom_container"):
            return
        
        if dpg.does_item_exist("zoom_slider") and self.slider_h is None:
            self.slider_h = dpg.get_item_rect_size("zoom_slider")[1]
        
        is_overlay = self.mgr.is_overlay_mode()
        slider_exists = dpg.does_item_exist("zoom_slider")
        spacer_exists = dpg.does_item_exist("zoom_spacer")
        
        if is_overlay and slider_exists and self.slider_h:
            dpg.delete_item("zoom_slider")
            dpg.add_spacer(tag="zoom_spacer", height=self.slider_h, parent="zoom_container")
        elif not is_overlay and spacer_exists:
            dpg.delete_item("zoom_spacer")
            dpg.add_slider_float(
                tag="zoom_slider",
                default_value=self.ui_scale,
                min_value=0.5,
                max_value=2.0,
                width=-1,
                format="",
                callback=self._on_zoom_change,
                parent="zoom_container"
            )

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
        
        self.base_font_size = int(16 * self.mgr.dpi_scale)
        self._create_scaled_font(self.ui_scale)
        
        x, y, w, h = self.mgr.load()
        dpg.create_viewport(title=WIN_TITLE, width=w, height=h, always_on_top=True,
                            clear_color=self.mgr.colorkey_rgba, x_pos=x, y_pos=y)
        dpg.setup_dearpygui()
        
        with dpg.window(tag="main", no_title_bar=True, no_move=True, no_resize=True,
                        no_background=True, no_scrollbar=True):
            with dpg.theme(tag="no_border"):
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
            dpg.bind_item_theme("main", "no_border")
            self._create_zoom_slider()
        
        self._setup_click_handler()
        self._setup_aggr_hotkey()
        
        dpg.set_primary_window("main", True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        self.mgr.apply()
        dpg.set_global_font_scale(self.ui_scale)
        self.mgr.apply_saved_state()
        self._update_zoom_slider_visibility()
    
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
                webbrowser.open(data)
            elif action == "header":
                if url := get_dscan_info_url(self.last_clip):
                    webbrowser.open(url)
            elif action == "alliance":
                webbrowser.open(f"https://zkillboard.com/alliance/{data}/")
            elif action == "corp":
                webbrowser.open(f"https://zkillboard.com/corporation/{data}/")
            elif action == "toggle":
                cur = self._get_collapse_state(data)
                self._set_collapse_state(data, not cur)
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
    
    def _btn_theme(self, color):
        bg = self.mgr.bg_color if self.mgr.text_bg else self.mgr.colorkey
        hover_bg = (80, 80, 80, 255) if self.mgr.text_bg else (60, 60, 60, 255)
        key = f"btn_{color}_{bg}"
        if key not in self.themes:
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                    dpg.add_theme_color(dpg.mvThemeCol_Button, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover_bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, hover_bg)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0, 0.5)
            self.themes[key] = theme
        return self.themes[key]
    
    def _header_theme(self, color=None, is_open=False):
        bg = self.mgr.bg_color if self.mgr.text_bg else self.mgr.colorkey
        hover_bg = (80, 80, 80, 255) if self.mgr.text_bg else (60, 60, 60, 255)
        key = f"hdr_{color}_{bg}_{is_open}"
        if key not in self.themes:
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvButton):
                    if color:
                        dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                    dpg.add_theme_color(dpg.mvThemeCol_Button, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover_bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, hover_bg)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0, 0.5)
            self.themes[key] = theme
        return self.themes[key]

    def add_item(self, label, color, user_data=None, parent=None):
        if parent:
            dpg.add_button(label=label, user_data=user_data, parent=parent)
        else:
            dpg.add_button(label=label, user_data=user_data)
        dpg.bind_item_theme(dpg.last_item(), self._btn_theme(color))
    
    def add_header(self, label, state_key, color=None, indent=0, parent=None):
        is_open = self._get_collapse_state(state_key)
        arrow = "\u25BC " if is_open else "\u25BA "
        prefix = " " * indent
        btn_label = f"{prefix}{arrow}{label}"
        user_data = ("toggle", state_key)
        if parent:
            dpg.add_button(label=btn_label, user_data=user_data, parent=parent)
        else:
            dpg.add_button(label=btn_label, user_data=user_data)
        dpg.bind_item_theme(dpg.last_item(), self._header_theme(color, is_open))
        return is_open
    
    def _get_collapse_state(self, key):
        if isinstance(key, tuple):
            d = self.collapse_state
            for k in key[:-1]:
                d = d.get(k, {})
            return d.get(key[-1], False)
        return self.collapse_state.get(key, False)
    
    def _set_collapse_state(self, key, val):
        if isinstance(key, tuple):
            d = self.collapse_state
            for k in key[:-1]:
                if k not in d:
                    d[k] = {}
                d = d[k]
            d[key[-1]] = val
        else:
            self.collapse_state[key] = val

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
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        
        remaining = self.get_remaining_time()
        if self.mgr.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.mgr.is_overlay_mode():
            return
        
        with dpg.group(tag="pilot_list", parent="main"):
            lbl = f"{len(visible)} | {remaining:.0f}s"
            self.add_item(lbl, (0, 255, 0), ("header", None))
            
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
                    self.add_item(label, self.get_pilot_color(pilot), ("pilot", link) if link else None)

    def render_pilots_aggregated(self, visible):
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        
        remaining = self.get_remaining_time()
        if self.mgr.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.mgr.is_overlay_mode():
            return
        
        alliance_cnt, corps_by_alliance, no_alliance_corps, grp_cnt = self._aggregate_pilots(visible)
        total = len(visible)
        
        sorted_alliances = sorted(alliance_cnt.items(), key=lambda x: (x[0] == "No Alliance", -x[1]))
        
        with dpg.group(tag="aggr_content", parent="main"):
            lbl = f"{total} | {remaining:.0f}s"
            self.add_item(lbl, (0, 255, 0), ("header", None))
            
            if any(grp_cnt.values()):
                with dpg.group(horizontal=True):
                    for grp_name, cnt in grp_cnt.items():
                        if cnt > 0:
                            color = self.group_cfg[grp_name]['color']
                            self.add_item(f"{grp_name}: {cnt}  ", color)
            
            with dpg.group(horizontal=True):
                with dpg.group():
                    self.add_item("Alliances:", (255, 255, 0))
                    
                    for alliance, cnt in sorted_alliances:
                        display = "[No Alliance]" if alliance == "No Alliance" else alliance
                        color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                        alliance_id = self.alliance_ids.get(alliance)
                        self.add_item(f"  {display}: {cnt}", color, ("alliance", alliance_id) if alliance_id else None)
                
                with dpg.group():
                    if self.add_header("Corporations", "corps"):
                        sorted_corps = sorted(corps_by_alliance.items(), key=lambda x: -alliance_cnt.get(x[0], 0))
                        for j, (alliance, corps) in enumerate(sorted_corps):
                            corps = sorted(corps, key=lambda x: -x["count"])
                            display = "[No Alliance]" if alliance == "No Alliance" else alliance
                            color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                            alliance_total = alliance_cnt.get(alliance, 0)
                            if self.add_header(f"{display}: {alliance_total}", alliance, color, indent=2):
                                for c in corps:
                                    corp_id = self.corp_ids.get(c['name'])
                                    self.add_item(f"    {c['name']}: {c['count']}", color, ("corp", corp_id) if corp_id else None)
                        
                        for c in sorted(no_alliance_corps, key=lambda x: -x["count"]):
                            corp_id = self.corp_ids.get(c['name'])
                            self.add_item(f"  {c['name']}: {c['count']}", DEFAULT_ALLIANCE_COLOR, ("corp", corp_id) if corp_id else None)

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
        
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        if dpg.does_item_exist("dscan_content"):
            dpg.delete_item("dscan_content")
        
        remaining = self.get_remaining_time()
        if self.mgr.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        if self.timeout_expired and self.mgr.is_overlay_mode():
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
            lbl = f"{res.total_ships} | {remaining:.0f}s"
            self.add_item(lbl, (0, 255, 0), ("header", None))
            
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_spacer(height=dpg.get_text_size("X")[1])
                    for ship, cnt, diff, _ in ship_list[:30]:
                        self.add_item(f"  {ship}: {cnt}{diff_str(diff)}", diff_color(diff))
                
                with dpg.group():
                    if self.add_header("Categories", ("dscan_groups", "main")):
                        for j, (grp, cnt) in enumerate(sorted_grps):
                            grp_diff = grp_diffs.get(grp, 0)
                            color = diff_color(grp_diff)
                            if self.add_header(f"{grp}: {cnt}{diff_str(grp_diff)}", ("dscan_groups", grp), color, indent=2):
                                for ship, ship_cnt, ship_diff in ships_by_grp.get(grp, []):
                                    self.add_item(f"    {ship}: {ship_cnt}{diff_str(ship_diff)}", diff_color(ship_diff))

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
        self._needs_resize = True
    
    def clear_display(self):
        for tag in ("pilot_list", "aggr_content", "dscan_content"):
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
    
    def reset_timeout(self):
        self.result_start_time = time.time()
        self.paused_time = 0
        self.pause_start_time = None
        self.timeout_expired = False
        if not self.mgr.is_overlay_mode():
            self.pause_start_time = time.time()
    
    def run_loop(self):
        self._needs_resize = False
        while dpg.is_dearpygui_running():
            self.mgr.process_hotkeys()
            self.process_aggr_hotkey()
            self.mgr.check_and_save()
            self.check_clipboard()
            
            if self.mode == 'pilots':
                self.render_pilots()
            elif self.mode == 'dscan':
                self.render_dscan()
            
            dpg.render_dearpygui_frame()
            
            if self._needs_resize:
                self._auto_resize(force=True)
                self._needs_resize = False
            else:
                self._auto_resize()
    
    def start(self):
        self.setup_gui()
        self.run_loop()
        self.mgr.cleanup()
        dpg.destroy_context()

def main():
    DScanAnalyzer().start()

if __name__ == "__main__":
    main()
