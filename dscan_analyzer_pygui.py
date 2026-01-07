import dearpygui.dearpygui as dpg
import pyperclip
import webbrowser
import time
from global_hotkeys import register_hotkeys
from overlay import OverlayWindow, WindowManager
from config import C
from services import PilotService, DScanService, PilotState
from pilot_color_classifier import PilotColorClassifier

def bgr_to_rgb(color):
    return (color[2], color[1], color[0])

WIN_TITLE = "dscan_analyzer"
TAG_W = 4
DEFAULT_ALLIANCE_COLOR = (200, 200, 200)

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
        self.lines = []
        self.mode = None
        self.pilot_themes = {}
        self.pilot_links = {}
        self.rendered_cnt = 0
        
        self.timeout_duration = dscan_cfg.get('timeout', 10)
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
        
        self.aggr_mode = False
        self.aggr_mode_manual = None
        self.aggr_threshold = dscan_cfg.get('aggregated_mode_threshold', 50)
        self.aggr_hotkey = dscan_cfg.get('hotkey_mode', 'alt+shift+m')
        self.aggr_toggle_requested = False
        self.aggr_collapse_state = {"corps": False}
        self.alliance_colors = {}
    
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
            dpg.add_text("", tag="output")
        
        self._setup_aggr_hotkey()
        
        dpg.set_primary_window("main", True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        self.win_mgr.apply()
    
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
    
    def create_pilot_theme(self, color):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvSelectable):
                dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (80, 80, 80, 150))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (80, 80, 80, 150))
        return theme
    
    def on_pilot_click(self, sender, app_data, user_data):
        dpg.set_value(sender, False)
        if link := self.pilot_links.get(sender):
            webbrowser.open(link)
    
    def get_pilot_tag_color(self, pilot):
        return next(
            (self.groups[v] for attr in ('name', 'corp_name', 'alliance_name') 
             if (v := getattr(pilot, attr, None)) and v in self.groups),
            None
        )
    
    def get_pilot_color(self, pilot):
        if pilot.state in STATE_COLORS:
            return STATE_COLORS[pilot.state]
        if pilot.state in (PilotState.CACHE_HIT, PilotState.FOUND) and pilot.stats:
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
    
    def draw_pilot_row(self, parent, name, pilot, idx):
        row_h = dpg.get_text_size(name)[1]
        tag_color = self.get_pilot_tag_color(pilot)
        label = self.format_pilot(name, pilot)
        row_tag, sel_tag, draw_tag, rect_tag = f"row_{idx}", f"pilot_{idx}", f"draw_{idx}", f"rect_{idx}"
        
        rect_fill = tag_color or (0, 0, 0, 0)
        
        if dpg.does_item_exist(row_tag):
            dpg.configure_item(sel_tag, label=label)
            dpg.configure_item(rect_tag, color=rect_fill, fill=rect_fill)
        else:
            with dpg.group(horizontal=True, parent=parent, tag=row_tag):
                with dpg.drawlist(width=TAG_W, height=row_h, tag=draw_tag):
                    dpg.draw_rectangle([0, 0], [TAG_W, row_h], fill=rect_fill, color=rect_fill, tag=rect_tag)
                dpg.add_spacer(width=4)
                dpg.add_selectable(label=label, tag=sel_tag, callback=self.on_pilot_click)
        
        self.pilot_links[sel_tag] = pilot.stats_link
        text_color = self.get_pilot_color(pilot)
        if text_color not in self.pilot_themes:
            self.pilot_themes[text_color] = self.create_pilot_theme(text_color)
        dpg.bind_item_theme(sel_tag, self.pilot_themes[text_color])
    
    def render_pilots(self):
        pilots = self.pilot_svc.get_pilots()
        visible = [(n, p) for n, p in pilots.items() 
                   if p.state != PilotState.NOT_FOUND or p.char_id is not None]
        
        pilot_cnt = len(visible)
        auto_aggr = pilot_cnt > self.aggr_threshold
        self.aggr_mode = self.aggr_mode_manual if self.aggr_mode_manual is not None else auto_aggr
        
        if self.aggr_mode:
            self.render_pilots_aggregated(visible)
        else:
            self.render_pilots_normal(visible)
    
    def render_pilots_normal(self, visible):
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        
        if not dpg.does_item_exist("pilot_list"):
            dpg.add_group(tag="pilot_list", parent="main")
            dpg.add_text("", tag="pilot_header", parent="pilot_list", color=(0, 255, 0))
        
        remaining = self.get_remaining_time()
        
        if self.overlay.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        
        if self.timeout_expired and self.overlay.is_overlay_mode():
            dpg.configure_item("pilot_header", default_value="")
            for i in range(self.rendered_cnt):
                if dpg.does_item_exist(f"row_{i}"):
                    dpg.delete_item(f"row_{i}")
            self.rendered_cnt = 0
            return
        
        dpg.configure_item("pilot_header", default_value=f"{len(visible)} | {remaining:.0f}s")
        
        for i in range(len(visible), self.rendered_cnt):
            if dpg.does_item_exist(f"row_{i}"):
                dpg.delete_item(f"row_{i}")
        
        for i, (name, pilot) in enumerate(visible):
            self.draw_pilot_row("pilot_list", name, pilot, i)
        
        self.rendered_cnt = len(visible)
    
    def render_pilots_aggregated(self, visible):
        if dpg.does_item_exist("pilot_list"):
            dpg.delete_item("pilot_list")
        self.rendered_cnt = 0
        
        self._save_aggr_collapse_state()
        
        if dpg.does_item_exist("aggr_content"):
            dpg.delete_item("aggr_content")
        
        remaining = self.get_remaining_time()
        if self.overlay.is_overlay_mode() and remaining <= 0:
            self.timeout_expired = True
        
        if self.timeout_expired and self.overlay.is_overlay_mode():
            return
        
        alliance_counts, corps_by_alliance, no_alliance_corps = self._aggregate_pilots(visible)
        
        header_theme = self._create_header_theme()
        
        with dpg.group(tag="aggr_content", parent="main"):
            total = len(visible)
            dpg.add_text(f"Total: {total} | {remaining:.0f}s", tag="aggr_header")
            dpg.bind_item_theme("aggr_header", self._get_text_theme((0, 255, 0)))
            dpg.add_separator()
            
            with dpg.group(horizontal=True):
                with dpg.group(tag="aggr_left_col", width=200):
                    dpg.add_text("Alliances:", tag="aggr_alliance_label")
                    dpg.bind_item_theme("aggr_alliance_label", self._get_text_theme((255, 255, 0)))
                    
                    sorted_alliances = sorted(alliance_counts.items(), key=lambda x: -x[1])
                    for i, (alliance, cnt) in enumerate(sorted_alliances):
                        color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                        tag = f"aggr_alliance_{i}"
                        dpg.add_text(f"  {alliance}: {cnt}", tag=tag)
                        dpg.bind_item_theme(tag, self._get_text_theme(color))
                
                with dpg.group(tag="aggr_right_col"):
                    is_open = self.aggr_collapse_state.get("corps", False)
                    with dpg.collapsing_header(label="Corporations", default_open=is_open, tag="aggr_corp_header"):
                        dpg.bind_item_theme("aggr_corp_header", header_theme)
                        
                        sorted_alliance_corps = sorted(corps_by_alliance.items(), key=lambda x: -alliance_counts.get(x[0], 0))
                        for j, (alliance, corps) in enumerate(sorted_alliance_corps):
                            corps = sorted(corps, key=lambda x: -x["count"])
                            color = self.alliance_colors.get(alliance, DEFAULT_ALLIANCE_COLOR)
                            alliance_open = self.aggr_collapse_state.get(alliance, False)
                            alliance_total = alliance_counts.get(alliance, 0)
                            tag = f"aggr_alliance_corps_{j}"
                            with dpg.collapsing_header(label=f"{alliance}: {alliance_total}", default_open=alliance_open, tag=tag, indent=10):
                                dpg.bind_item_theme(tag, self._create_colored_header_theme(color))
                                for k, c in enumerate(corps):
                                    ctag = f"aggr_corp_{j}_{k}"
                                    dpg.add_text(f"  {c['name']}: {c['count']}", tag=ctag)
                                    dpg.bind_item_theme(ctag, self._get_text_theme(color))
                        
                        if no_alliance_corps:
                            for k, c in enumerate(sorted(no_alliance_corps, key=lambda x: -x["count"])):
                                ctag = f"aggr_corp_none_{k}"
                                dpg.add_text(f"  {c['name']}: {c['count']}", tag=ctag)
                                dpg.bind_item_theme(ctag, self._get_text_theme(DEFAULT_ALLIANCE_COLOR))
    
    def _aggregate_pilots(self, visible):
        alliance_counts = {}
        corp_counts = {}
        pilot_alliances = {}
        
        for name, pilot in visible:
            alliance = pilot.alliance_name or "No Alliance"
            corp = pilot.corp_name or "Unknown Corp"
            
            alliance_counts[alliance] = alliance_counts.get(alliance, 0) + 1
            corp_counts[corp] = corp_counts.get(corp, 0) + 1
            pilot_alliances[corp] = alliance
            
            if alliance not in self.alliance_colors and pilot.alliance_name:
                color = self.groups.get(pilot.alliance_name)
                if not color:
                    color = self.get_pilot_color(pilot)
                if color and color != (200, 200, 200):
                    self.alliance_colors[alliance] = color
        
        corps_by_alliance = {}
        no_alliance_corps = []
        
        for corp, cnt in corp_counts.items():
            alliance = pilot_alliances.get(corp, "No Alliance")
            corp_data = {"name": corp, "count": cnt}
            if alliance and alliance != "No Alliance":
                corps_by_alliance.setdefault(alliance, []).append(corp_data)
            else:
                no_alliance_corps.append(corp_data)
        
        return alliance_counts, corps_by_alliance, no_alliance_corps
    
    def _save_aggr_collapse_state(self):
        if dpg.does_item_exist("aggr_corp_header"):
            self.aggr_collapse_state["corps"] = dpg.get_value("aggr_corp_header")
        for i in range(100):
            tag = f"aggr_alliance_corps_{i}"
            if dpg.does_item_exist(tag):
                label = dpg.get_item_label(tag)
                alliance = label.rsplit(":", 1)[0] if ":" in label else label
                self.aggr_collapse_state[alliance] = dpg.get_value(tag)
    
    def _create_header_theme(self):
        if not dpg.does_item_exist("aggr_header_theme"):
            bg = tuple(self.overlay.colorkey)
            with dpg.theme(tag="aggr_header_theme"):
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Header, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, bg)
        return "aggr_header_theme"
    
    def _create_colored_header_theme(self, color):
        key = f"aggr_header_theme_{color}"
        if key not in self.pilot_themes:
            bg = tuple(self.overlay.colorkey)
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvCollapsingHeader):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                    dpg.add_theme_color(dpg.mvThemeCol_Header, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, bg)
            self.pilot_themes[key] = theme
        return self.pilot_themes[key]
    
    def _get_text_theme(self, color):
        if color not in self.pilot_themes:
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvText):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, color)
            self.pilot_themes[color] = theme
        return self.pilot_themes[color]
    
    def render_dscan(self):
        if not (res := self.dscan_svc.last_result):
            return
        lines = [f"DScan: {res.total_ships} ships"]
        lines.extend(f"  {ship}: {cnt}" for grp, ships in res.ship_counts.items() for ship, cnt in ships.items())
        dpg.set_value("output", "\n".join(lines))
    
    def check_clipboard(self):
        try:
            clip = pyperclip.paste()
        except:
            return
        
        if not clip or clip == self.last_clip:
            return
        
        self.last_clip = clip
        
        if self.dscan_svc.is_dscan_format(clip) and self.dscan_svc.is_valid_dscan(clip) and self.dscan_svc.parse(clip):
            self.mode = 'dscan'
            self.reset_timeout()
        elif self.pilot_svc.set_pilots(clip):
            self.mode = 'pilots'
            self.reset_timeout()
    
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
