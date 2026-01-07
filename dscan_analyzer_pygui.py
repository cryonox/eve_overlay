import dearpygui.dearpygui as dpg
import pyperclip
from overlay import OverlayWindow, WindowManager
from config import C
from services import PilotService, DScanService, PilotState

WIN_TITLE = "dscan_analyzer"

class DScanAnalyzer:
    def __init__(self):
        cache_dir = C.get('cache', 'cache')
        stats_provider = C.dscan.get('stats_provider', 'zkill')
        rate_limit_delay = C.dscan.get('rate_limit_retry_delay', 5)
        stats_limit = C.dscan.get('aggregated_mode_threshold', 50)
        
        self.pilot_svc = PilotService(cache_dir, stats_provider, rate_limit_delay, stats_limit)
        self.dscan_svc = DScanService()
        self.win_mgr = WindowManager(WIN_TITLE, C, cfg_key='dscan_winstate')
        self.overlay = OverlayWindow(WIN_TITLE, on_toggle=lambda e: None)
        self.last_clip = ""
        self.lines = []
        self.mode = None
    
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
            self.setup_theme()
            dpg.add_text("", tag="output")
        
        dpg.set_primary_window("main", True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        self.win_mgr.apply()
    
    def setup_theme(self):
        dpg.bind_item_theme("main", dpg.add_theme(tag="no_border"))
        with dpg.theme_component(dpg.mvAll, parent="no_border"):
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    
    def format_pilot(self, name, pilot):
        state_map = {
            PilotState.SEARCHING_ESI: "Resolving...",
            PilotState.SEARCHING_STATS: "Fetching stats...",
            PilotState.NOT_FOUND: "Not found",
            PilotState.ERROR: pilot.error_msg or "Error",
            PilotState.RATE_LIMITED: "Rate limited",
        }
        
        if pilot.state in state_map:
            return f"{name} | {state_map[pilot.state]}"
        
        if pilot.state in (PilotState.CACHE_HIT, PilotState.FOUND) and pilot.stats:
            d = pilot.stats.get('danger', 0)
            k = pilot.stats.get('kills', 0)
            l = pilot.stats.get('losses', 0)
            return f"{name} | D:{d:.0f} K:{k} L:{l}"
        
        return f"{name} | {pilot.state.name}"
    
    def render_pilots(self):
        pilots = self.pilot_svc.get_pilots()
        self.lines = [f"Pilots: {len(pilots)}"]
        for name, pilot in pilots.items():
            self.lines.append(f"  {self.format_pilot(name, pilot)}")
        self.update_display()
    
    def render_dscan(self):
        res = self.dscan_svc.last_result
        if not res:
            return
        self.lines = [f"DScan: {res.total_ships} ships"]
        for grp, ships in res.ship_counts.items():
            for ship, cnt in ships.items():
                self.lines.append(f"  {ship}: {cnt}")
        self.update_display()
    
    def update_display(self):
        dpg.set_value("output", "\n".join(self.lines))
    
    def check_clipboard(self):
        try:
            clip = pyperclip.paste()
        except:
            return
        
        if clip and clip != self.last_clip:
            self.last_clip = clip
            
            if self.dscan_svc.is_dscan_format(clip):
                if self.dscan_svc.is_valid_dscan(clip):
                    res = self.dscan_svc.parse(clip)
                    if res:
                        self.mode = 'dscan'
                return
            
            if self.pilot_svc.set_pilots(clip):
                self.mode = 'pilots'
    
    def run_loop(self):
        while dpg.is_dearpygui_running():
            self.overlay.process_hotkey()
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
    analyzer = DScanAnalyzer()
    analyzer.start()

if __name__ == "__main__":
    main()
