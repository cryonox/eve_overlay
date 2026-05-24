"""DPS meter overlay window (a supervisor-controlled child process).

Passively reads each running client's EVE game log to compute outgoing/incoming
DPS and mining activity (via LogReader). Columns are Out | In | Mining | Name.
Two threshold inputs at the top (incoming-DPS and mining-idle) drive cell colors
and short audio alarms. EVE clients are auto-discovered by window title; the
supervisor's tray can ignore individual chars (pushed via control.json).
"""
import os
import sys
import time

import dearpygui.dearpygui as dpg
import win32gui

import ipc
from config import C
from overlay import OverlayManager
from log_reader import LogReader, scan_log_directory, find_eve_logs_dir
from loguru import logger

try:
    import winsound
except ImportError:
    winsound = None

WIN_TITLE = "dps_meter"

COL_OUT = (0, 255, 0, 255)      # outgoing dps  - green
COL_IN = (255, 0, 0, 255)       # incoming dps  - red
COL_MINE_BASE = (100, 200, 255, 255)
COL_MINE_IDLE = (100, 100, 100, 255)   # never mined - grey
COL_MINE_OK = (100, 200, 255, 255)     # actively mining - blue
COL_MINE_STALL = (255, 0, 0, 255)      # stalled past threshold - red
COL_NAME = (200, 200, 200, 255)


def scan_eve_chars():
    """Return the names of every logged-in EVE client (title 'EVE - Name')."""
    names = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title.startswith("EVE - "):
            name = title[len("EVE - "):].strip()
            if name and name not in names:
                names.append(name)
        return True

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception:
        logger.exception("scan_eve_chars failed")
    return sorted(names)


def _resource(rel):
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


class DpsMeter:
    def __init__(self):
        dps_cfg = C.get('dps', {})
        bg_color = dps_cfg.get('bg_color', [25, 25, 25])
        transparency = dps_cfg.get('transparency', 180)

        self.mgr = OverlayManager(
            WIN_TITLE, C, state_file='config.state.dps.yaml',
            win_key='dps_winstate', ui_key='dps_uistate',
            bg_color=bg_color, transparency=transparency,
            on_toggle=self._on_overlay_toggle, hotkeys=False,
        )

        self.dps_thresh = int(dps_cfg.get('dps_alarm_thresh', 80))
        self.mining_thresh = int(dps_cfg.get('mining_alarm_thresh', 35))
        self.font_path = dps_cfg.get('font', 'C:/Windows/Fonts/consolab.ttf')
        self.ui_scale = float(C.get('dps_uiscale', 1.0))

        self.logs_dir = find_eve_logs_dir()
        self.readers = {}          # char_name -> LogReader
        self.active = []           # ordered tracked char names
        # Ignored chars are removed via the per-row '-' button in this window and
        # persisted here; the tray's "Show all" clears them (via control.json).
        self.ignore = set(dps_cfg.get('ignore', []))
        self.themes = {}
        self._rows = {}            # char_name -> widget dict
        self._dps_over = {}        # char -> bool (edge-trigger alarm state)
        self._mining_stalled = {}

        self.quit_requested = False
        self._control_mtime = -1.0
        self._show_all_seen = 0
        self._last_scan = 0.0
        self._dps_alarm = _resource(os.path.join('assets', 'alarm_dps.wav'))
        self._mining_alarm = _resource(os.path.join('assets', 'alarm_mining.wav'))

    # ---- overlay / control sync ----------------------------------------

    def _on_overlay_toggle(self):
        self.themes.clear()

    def _apply_control(self):
        mt = ipc.mtime(ipc.CONTROL_FILE)
        if mt == self._control_mtime:
            return
        self._control_mtime = mt
        ctl = ipc.read_json(ipc.CONTROL_FILE)
        if not ctl:
            return
        if not ctl.get('modules', {}).get('dps', True):
            self.quit_requested = True
            return
        ov = self.mgr.set_overlay(ctl.get('overlay', False))
        self.mgr.set_clickthrough(ctl.get('clickthrough', False))
        bg = self.mgr.set_text_bg(ctl.get('text_bg', False))
        if 'transparency' in ctl:
            self.mgr.set_transparency(ctl['transparency'])
        if ov or bg:
            # button backgrounds depend on text_bg -> rebuild with fresh themes
            self.themes.clear()
            self._rebuild_rows()
        if ov:
            self._update_bar_visibility()
        # The tray's "Show all" bumps this counter -> un-ignore everything.
        show_all = int(ctl.get('dps', {}).get('show_all', 0))
        if show_all != self._show_all_seen:
            self._show_all_seen = show_all
            self.ignore.clear()
            self._persist_ignore()
            self._rescan(force=True)

    # ---- client discovery / reader lifecycle ---------------------------

    def _rescan(self, force=False):
        now = time.time()
        if not force and now - self._last_scan < 5.0:
            return
        self._last_scan = now
        discovered = scan_eve_chars()
        new_active = [n for n in discovered if n not in self.ignore]

        for name in list(self.readers):
            if name not in new_active:
                try:
                    self.readers.pop(name).stop()
                except Exception:
                    pass

        need = [n for n in new_active if n not in self.readers]
        # Resolve every new char's log file in ONE directory pass instead of
        # letting each LogReader rescan the whole Gamelogs folder (that made
        # enumeration take seconds with many clients).
        resolved = scan_log_directory(self.logs_dir, target_chars=need) if need else {}
        for name in need:
            info = resolved.get(name)
            try:
                if info:
                    self.readers[name] = LogReader(name, initial_log_file=info[0],
                                                   initial_language=info[1])
                else:
                    self.readers[name] = LogReader(name)
            except Exception:
                logger.exception(f"LogReader init failed for {name}")

        if new_active != self.active:
            self.active = new_active
            self._rebuild_rows()

    def _persist_ignore(self):
        C.dps.ignore = sorted(self.ignore)
        try:
            C.write(['dps.ignore'], 'config.state.dps.yaml')
        except Exception:
            logger.exception("persist dps.ignore failed")

    def _remove_char(self, sender, app_data, user_data):
        name = user_data
        self.ignore.add(name)
        self._persist_ignore()
        self._rescan(force=True)

    # ---- theming -------------------------------------------------------

    def _btn_theme(self, color):
        bg = self.mgr.bg_color_rgba if self.mgr.text_bg else self.mgr.colorkey_rgba
        key = f"btn_{color}_{bg}"
        if key not in self.themes:
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                    dpg.add_theme_color(dpg.mvThemeCol_Button, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, bg)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, bg)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0, 0.5)
            self.themes[key] = theme
        return self.themes[key]

    def _remove_btn_theme(self):
        # Solid (non-colorkey) fill + border + a brighter hover so the '-' reads
        # as a clickable button, not text.
        key = "remove_btn"
        if key not in self.themes:
            with dpg.theme() as theme:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(dpg.mvThemeCol_Text, (235, 235, 235, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (95, 55, 55, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (180, 65, 65, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (220, 80, 80, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_Border, (210, 130, 130, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 1)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.5, 0.5)
            self.themes[key] = theme
        return self.themes[key]

    # ---- gui -----------------------------------------------------------

    def setup_gui(self):
        dpg.create_context()
        base_font_size = int(16 * self.mgr.dpi_scale)
        with dpg.font_registry():
            with dpg.font(self.font_path, base_font_size) as self.font:
                dpg.add_font_range(0x25A0, 0x25C0)
        dpg.bind_font(self.font)

        x, y, w, h = self.mgr.load(default_w=240, default_h=120)
        dpg.create_viewport(title=WIN_TITLE, width=w, height=h, always_on_top=True,
                            clear_color=self.mgr.colorkey_rgba, x_pos=x, y_pos=y)
        dpg.setup_dearpygui()

        with dpg.theme(tag="dps_no_border"):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 0)
        with dpg.theme() as self._input_theme:
            with dpg.theme_component(dpg.mvInputInt):
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (40, 40, 40, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 165, 0, 255))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 2)

        with dpg.window(tag="main", no_title_bar=True, no_move=True, no_resize=True,
                        no_background=True, no_scrollbar=True):
            dpg.bind_item_theme("main", "dps_no_border")
            with dpg.group(tag="zoom_container"):
                dpg.add_slider_float(
                    tag="zoom_slider", default_value=self.ui_scale,
                    min_value=0.5, max_value=2.0, width=-1, format="",
                    callback=self._on_zoom_change)
            with dpg.group(horizontal=True, tag="top_row"):
                self._dps_input = dpg.add_input_int(
                    default_value=self.dps_thresh, width=70, step=0,
                    callback=self._on_dps_thresh)
                dpg.bind_item_theme(self._dps_input, self._input_theme)
                self._mining_input = dpg.add_input_int(
                    default_value=self.mining_thresh, width=70, step=0,
                    callback=self._on_mining_thresh)
                dpg.bind_item_theme(self._mining_input, self._input_theme)
            dpg.add_group(tag="char_container")

        dpg.set_primary_window("main", True)
        dpg.show_viewport()
        dpg.render_dearpygui_frame()
        self.mgr.apply()
        dpg.set_global_font_scale(self.ui_scale)
        self.mgr.apply_saved_state()
        self._update_bar_visibility()
        self._rescan(force=True)

    def _on_zoom_change(self, sender, val):
        self.ui_scale = float(val)
        dpg.set_global_font_scale(self.ui_scale)
        C.dps_uiscale = self.ui_scale
        try:
            C.write(['dps_uiscale'], 'config.state.dps.yaml')
        except Exception:
            logger.exception("persist dps_uiscale failed")

    def _update_bar_visibility(self):
        # The zoom bar shows only when not in overlay mode.
        if not dpg.does_item_exist("zoom_container"):
            return
        if self.mgr.overlay:
            dpg.hide_item("zoom_container")
        else:
            dpg.show_item("zoom_container")

    def _on_dps_thresh(self, sender, val):
        self.dps_thresh = int(val)
        C.dps.dps_alarm_thresh = self.dps_thresh
        try:
            C.write(['dps.dps_alarm_thresh'], 'config.state.dps.yaml')
        except Exception:
            logger.exception("persist dps_alarm_thresh failed")

    def _on_mining_thresh(self, sender, val):
        self.mining_thresh = int(val)
        C.dps.mining_alarm_thresh = self.mining_thresh
        try:
            C.write(['dps.mining_alarm_thresh'], 'config.state.dps.yaml')
        except Exception:
            logger.exception("persist mining_alarm_thresh failed")

    def _rebuild_rows(self):
        for name, w in self._rows.items():
            if dpg.does_item_exist(w['group']):
                dpg.delete_item(w['group'])
        self._rows.clear()
        for name in self.active:
            with dpg.group(horizontal=True, parent="char_container") as grp:
                out_lbl = dpg.add_button(label="")
                dpg.bind_item_theme(out_lbl, self._btn_theme(COL_OUT))
                in_lbl = dpg.add_button(label="")
                dpg.bind_item_theme(in_lbl, self._btn_theme(COL_IN))
                mine_lbl = dpg.add_button(label="")
                dpg.bind_item_theme(mine_lbl, self._btn_theme(COL_MINE_BASE))
                name_lbl = dpg.add_button(label=name, user_data=name,
                                          callback=self._focus_eve_window)
                dpg.bind_item_theme(name_lbl, self._btn_theme(COL_NAME))
                # '-' removes this char from the meter (tray "Show all" restores).
                del_btn = dpg.add_button(label="-", user_data=name,
                                         callback=self._remove_char)
                dpg.bind_item_theme(del_btn, self._remove_btn_theme())
            self._rows[name] = {'group': grp, 'out': out_lbl, 'in': in_lbl,
                                'mine': mine_lbl, 'name': name_lbl, 'del': del_btn}

    def _focus_eve_window(self, sender, app_data, user_data):
        hwnd = win32gui.FindWindow(None, f"EVE - {user_data}")
        if hwnd:
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

    # ---- per-frame update ----------------------------------------------

    def _play(self, path):
        if winsound is None:
            return
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            logger.exception("alarm playback failed")

    def _update_values(self):
        for name in self.active:
            reader = self.readers.get(name)
            row = self._rows.get(name)
            if reader is None or row is None:
                continue
            try:
                reader.update()
            except Exception:
                logger.exception(f"reader.update failed for {name}")
            dps_out = reader.get_dps_out()
            dps_in = reader.get_dps_in()
            idle = reader.get_mining_idle_sec()

            dpg.configure_item(row['out'], label=f"{dps_out:^5.0f}")

            dpg.configure_item(row['in'], label=f"{dps_in:^5.0f}")
            over = dps_in >= self.dps_thresh
            if over and not self._dps_over.get(name):
                self._play(self._dps_alarm)
            self._dps_over[name] = over

            if idle is None:
                dpg.configure_item(row['mine'], label="  -  ")
                dpg.bind_item_theme(row['mine'], self._btn_theme(COL_MINE_IDLE))
                self._mining_stalled[name] = False
            else:
                dpg.configure_item(row['mine'], label=f"{int(idle):>3d}s ")
                stalled = idle > self.mining_thresh
                dpg.bind_item_theme(row['mine'],
                                    self._btn_theme(COL_MINE_STALL if stalled else COL_MINE_OK))
                if stalled and not self._mining_stalled.get(name):
                    self._play(self._mining_alarm)
                self._mining_stalled[name] = stalled

    def run_loop(self):
        # No auto-resize: the window is user-resizable; its size is persisted by
        # the OverlayManager (check_and_save) and restored on next launch.
        while dpg.is_dearpygui_running():
            self._apply_control()
            if self.quit_requested:
                dpg.stop_dearpygui()
                break
            self._rescan()
            self._update_values()
            self.mgr.check_and_save()
            dpg.render_dearpygui_frame()
            time.sleep(0.05)

    def start(self):
        self.setup_gui()
        self.run_loop()
        for r in self.readers.values():
            try:
                r.stop()
            except Exception:
                pass
        self.mgr.cleanup()
        dpg.destroy_context()


def main():
    DpsMeter().start()


if __name__ == "__main__":
    main()
