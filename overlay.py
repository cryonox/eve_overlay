import win32gui
import win32con
import ctypes
from ctypes import byref, wintypes
from global_hotkeys import register_hotkeys, start_checking_hotkeys, stop_checking_hotkeys
from utils import get_title_bar_dimensions

user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)]


class OverlayManager:
    DEFAULT_COLORKEY = (0x25, 0x25, 0x26)
    DEFAULT_HOTKEY_OVERLAY = "alt + shift + t"
    DEFAULT_HOTKEY_CLICKTHROUGH = "alt + shift + c"
    DEFAULT_HOTKEY_TRANSPARENT = "alt + shift + b"
    
    def __init__(self, title, cfg, state_file='config.state.yaml', win_key='winstate', ui_key='uistate',
                 colorkey=None, bg_color=None, transparency=255, hotkey_overlay=None, hotkey_clickthrough=None,
                 hotkey_transparent=None, on_toggle=None):
        self._title = title
        self._cfg = cfg
        self._state_file = state_file
        self._win_key = win_key
        self._ui_key = ui_key
        self._last_state = None
        self._dpi_scale = self._get_dpi_scale()

        self.colorkey = colorkey or self.DEFAULT_COLORKEY
        self.colorkey_rgb = self.colorkey[0] | (self.colorkey[1] << 8) | (self.colorkey[2] << 16)
        self.bg_color = tuple(bg_color[:3]) if bg_color else (40, 40, 40)
        self.transparency = max(0, min(255, int(transparency)))

        self.overlay = False
        self.clickthrough = False
        self.text_bg = False

        self._saved_style = None
        self._saved_exstyle = None
        self._saved_client_rect = None
        self._saved_client_pos = None
        self._saved_window_pos = None

        self._toggle_overlay_requested = False
        self._toggle_clickthrough_requested = False
        self._toggle_text_bg_requested = False

        self._on_toggle = on_toggle
        self._hotkey_overlay = hotkey_overlay or self.DEFAULT_HOTKEY_OVERLAY
        self._hotkey_clickthrough = hotkey_clickthrough or self.DEFAULT_HOTKEY_CLICKTHROUGH
        self._hotkey_text_bg = hotkey_transparent or self.DEFAULT_HOTKEY_TRANSPARENT

        self._pending_state = None
        self._setup_hotkeys()

    @property
    def colorkey_rgba(self):
        return [self.colorkey[0], self.colorkey[1], self.colorkey[2], 255]

    @property
    def bg_color_rgba(self):
        return (*self.bg_color, 255)
    
    @property
    def dpi_scale(self):
        return self._dpi_scale
    
    def _get_dpi_scale(self):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    
    def _get_hwnd(self):
        return win32gui.FindWindow(None, self._title)
    
    @property
    def hwnd(self):
        hwnd = self._get_hwnd()
        return hwnd if hwnd and win32gui.IsWindow(hwnd) else None
    
    def get_state(self):
        hwnd = self._get_hwnd()
        if not hwnd:
            return None
        rect = win32gui.GetWindowRect(hwnd)
        return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
    
    def get_pos(self):
        state = self.get_state()
        return (state[0], state[1]) if state else None

    def load(self, default_x=100, default_y=100, default_w=400, default_h=300):
        state = self._cfg.get(self._win_key, {})
        x, y = int(state.get('x', default_x)), int(state.get('y', default_y))
        w, h = int(state.get('w', default_w)), int(state.get('h', default_h))
        self._last_state = (x, y, w, h)
        
        ui_state = self._cfg.get(self._ui_key, {})
        saved_overlay = ui_state.get('overlay', False)
        saved_clickthrough = ui_state.get('clickthrough', False)
        saved_text_bg = ui_state.get('text_bg', False)
        
        if saved_overlay:
            self._pending_state = {
                'overlay': saved_overlay,
                'clickthrough': saved_clickthrough,
                'text_bg': saved_text_bg
            }
        
        return x, y, w, h
    
    def save(self):
        from config import dict2attrdict
        state = self.get_state()
        if state:
            setattr(self._cfg, self._win_key, dict2attrdict({
                'x': state[0], 'y': state[1], 'w': state[2], 'h': state[3]
            }))
            self._cfg.write([self._win_key], self._state_file)
    
    def _save_ui_state(self):
        from config import dict2attrdict
        setattr(self._cfg, self._ui_key, dict2attrdict({
            'overlay': self.overlay,
            'clickthrough': self.clickthrough,
            'text_bg': self.text_bg
        }))
        self._cfg.write([self._ui_key], self._state_file)
    
    def apply(self, x=None, y=None, w=None, h=None):
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        if self._last_state is None:
            self.load()
        x = x if x is not None else self._last_state[0]
        y = y if y is not None else self._last_state[1]
        w = w if w is not None else self._last_state[2]
        h = h if h is not None else self._last_state[3]
        win32gui.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004)
    
    def apply_pos(self, x=None, y=None):
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        if x is None or y is None:
            px, py = self._last_state[:2] if self._last_state else (100, 100)
            x, y = x or px, y or py
        win32gui.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)
    
    def apply_saved_state(self):
        if not self._pending_state:
            return
        hwnd = self._get_hwnd()
        if hwnd:
            th, bw = get_title_bar_dimensions(hwnd)
            x, y = self.get_pos()
            self.apply_pos(x - bw, y - th)
        
        self.clickthrough = self._pending_state['clickthrough']
        self.text_bg = self._pending_state['text_bg']
        self._enable_overlay()
        
        if self._on_toggle:
            self._on_toggle()
    
    def check_and_save(self):
        cur_state = self.get_state()
        if cur_state and cur_state != self._last_state:
            self._last_state = cur_state
            self.save()
            return True
        return False

    def _setup_hotkeys(self):
        bindings = [
            [self._hotkey_overlay, None, self._request_toggle_overlay, True],
            [self._hotkey_clickthrough, None, self._request_toggle_clickthrough, True],
            [self._hotkey_text_bg, None, self._request_toggle_text_bg, True],
        ]
        register_hotkeys(bindings)
        start_checking_hotkeys()
    
    def _request_toggle_overlay(self):
        self._toggle_overlay_requested = True
    
    def _request_toggle_clickthrough(self):
        self._toggle_clickthrough_requested = True
    
    def _request_toggle_text_bg(self):
        self._toggle_text_bg_requested = True
    
    def process_hotkeys(self):
        changed = False
        
        if self._toggle_overlay_requested:
            self._toggle_overlay_requested = False
            self.toggle_overlay()
            changed = True
        
        if self._toggle_clickthrough_requested:
            self._toggle_clickthrough_requested = False
            if self.overlay:
                self.toggle_clickthrough()
                changed = True
        
        if self._toggle_text_bg_requested:
            self._toggle_text_bg_requested = False
            self.toggle_text_bg()
            changed = True
        
        if changed and self._on_toggle:
            self._on_toggle()
        
        return changed
    
    def cleanup(self):
        stop_checking_hotkeys()
    
    def _save_window_state(self):
        hwnd = self.hwnd
        if not hwnd:
            return False
        
        self._saved_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        self._saved_exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        
        win_rect = win32gui.GetWindowRect(hwnd)
        client_rect = win32gui.GetClientRect(hwnd)
        client_left, client_top = self._get_client_pos()
        self._saved_window_pos = (win_rect[0], win_rect[1])
        self._saved_client_pos = (client_left, client_top)
        self._saved_client_rect = (client_rect[2], client_rect[3])
        return True
    
    def _get_client_pos(self):
        hwnd = self.hwnd
        win_rect = win32gui.GetWindowRect(hwnd)
        client_rect = win32gui.GetClientRect(hwnd)
        client_left = win_rect[0] + (win_rect[2] - win_rect[0] - client_rect[2]) // 2
        client_top = win_rect[1] + (win_rect[3] - win_rect[1] - client_rect[3]) - (win_rect[2] - win_rect[0] - client_rect[2]) // 2
        return client_left, client_top

    def _apply_window_style(self):
        hwnd = self.hwnd
        if not hwnd or self._saved_style is None:
            return False

        style = self._saved_style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_SYSMENU
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)

        exstyle = self._saved_exstyle | win32con.WS_EX_LAYERED
        if self.clickthrough:
            exstyle |= win32con.WS_EX_TRANSPARENT
        else:
            exstyle &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)

        win32gui.SetLayeredWindowAttributes(hwnd, self.colorkey_rgb, self.transparency,
                                            win32con.LWA_COLORKEY | win32con.LWA_ALPHA)

        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, self._saved_client_pos[0], self._saved_client_pos[1],
                              self._saved_client_rect[0], self._saved_client_rect[1],
                              win32con.SWP_FRAMECHANGED)
        return True
    
    def _enable_overlay(self):
        hwnd = self.hwnd
        if not hwnd:
            return False
        
        if not self._save_window_state():
            return False
        
        self._apply_window_style()
        self.overlay = True
        self._save_ui_state()
        return True
    
    def _disable_overlay(self):
        hwnd = self.hwnd
        if not hwnd or self._saved_style is None:
            return False
        
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, self._saved_style)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, self._saved_exstyle)
        
        rect = RECT(0, 0, self._saved_client_rect[0], self._saved_client_rect[1])
        user32.AdjustWindowRectEx(byref(rect), self._saved_style, False, self._saved_exstyle)
        new_w, new_h = rect.right - rect.left, rect.bottom - rect.top
        
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, self._saved_window_pos[0], self._saved_window_pos[1],
                              new_w, new_h, win32con.SWP_FRAMECHANGED)
        
        self.overlay = False
        self._save_ui_state()
        return True
    
    def toggle_overlay(self):
        return self._disable_overlay() if self.overlay else self._enable_overlay()
    
    def toggle_clickthrough(self):
        if not self.overlay:
            return False
        self.clickthrough = not self.clickthrough
        self._apply_window_style()
        self._save_ui_state()
        return True
    
    def toggle_text_bg(self):
        self.text_bg = not self.text_bg
        self._save_ui_state()
        return True
    
    @property
    def enabled(self):
        return self.overlay
    
    def is_overlay_mode(self):
        return self.overlay
