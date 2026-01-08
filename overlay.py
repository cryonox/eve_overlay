import win32gui
import win32con
import ctypes
from ctypes import c_int, byref, wintypes
from global_hotkeys import register_hotkeys, start_checking_hotkeys, stop_checking_hotkeys
from loguru import logger
from utils import get_title_bar_dimensions

user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)]


class OverlayManager:
    DEFAULT_COLORKEY = (0x25, 0x25, 0x26)
    DEFAULT_HOTKEY = "alt + shift + t"
    
    def __init__(self, title, cfg, state_file='config.state.yaml', win_key='winstate', ui_key='uistate', 
                 colorkey=None, hotkey=None, on_toggle=None):
        self._title = title
        self._cfg = cfg
        self._state_file = state_file
        self._win_key = win_key
        self._ui_key = ui_key
        self._last_state = None
        self._dpi_scale = self._get_dpi_scale()
        
        self.colorkey = colorkey or self.DEFAULT_COLORKEY
        self.colorkey_rgb = self.colorkey[0] | (self.colorkey[1] << 8) | (self.colorkey[2] << 16)
        self.enabled = False
        self._saved_style = None
        self._saved_exstyle = None
        self._saved_client_rect = None
        self._saved_window_pos = None
        self._toggle_requested = False
        self._on_toggle = on_toggle
        self._hotkey = hotkey or self.DEFAULT_HOTKEY
        self._overlay_pending = False
        self._setup_hotkey()
    
    @property
    def colorkey_rgba(self):
        return [self.colorkey[0], self.colorkey[1], self.colorkey[2], 255]
    
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
        if hwnd and win32gui.IsWindow(hwnd):
            return hwnd
        return None
    
    def get_state(self):
        hwnd = self._get_hwnd()
        if hwnd:
            rect = win32gui.GetWindowRect(hwnd)
            return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
        return None
    
    def get_pos(self):
        state = self.get_state()
        return (state[0], state[1]) if state else None
    
    def load(self, default_x=100, default_y=100, default_w=400, default_h=300):
        from config import dict2attrdict
        state = self._cfg.get(self._win_key, {})
        x, y = int(state.get('x', default_x)), int(state.get('y', default_y))
        w, h = int(state.get('w', default_w)), int(state.get('h', default_h))
        self._last_state = (x, y, w, h)
        
        ui_state = self._cfg.get(self._ui_key, {})
        self._overlay_pending = ui_state.get('overlay', False)
        
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
        setattr(self._cfg, self._ui_key, dict2attrdict({'overlay': self.enabled}))
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
        if not self._overlay_pending:
            return
        hwnd = self._get_hwnd()
        if hwnd:
            th, bw = get_title_bar_dimensions(hwnd)
            x, y = self.get_pos()
            self.apply_pos(x - bw, y - th)
        self._enable_overlay()
        if self._on_toggle:
            self._on_toggle(self.enabled)
    
    def check_and_save(self):
        cur_state = self.get_state()
        if cur_state and cur_state != self._last_state:
            self._last_state = cur_state
            self.save()
            return True
        return False
    
    def _setup_hotkey(self):
        bindings = [[self._hotkey, None, self._request_toggle, True]]
        register_hotkeys(bindings)
        start_checking_hotkeys()
    
    def _request_toggle(self):
        self._toggle_requested = True
    
    def process_hotkey(self):
        if not self._toggle_requested:
            return False
        self._toggle_requested = False
        self.toggle()
        if self._on_toggle:
            self._on_toggle(self.enabled)
        return True
    
    def cleanup(self):
        stop_checking_hotkeys()
    
    def _enable_overlay(self):
        hwnd = self.hwnd
        if not hwnd:
            return False
        
        self._saved_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        self._saved_exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        
        win_rect = win32gui.GetWindowRect(hwnd)
        client_rect = win32gui.GetClientRect(hwnd)
        self._saved_window_pos = (win_rect[0], win_rect[1])
        self._saved_client_rect = (client_rect[2], client_rect[3])
        
        client_left = win_rect[0] + (win_rect[2] - win_rect[0] - client_rect[2]) // 2
        client_top = win_rect[1] + (win_rect[3] - win_rect[1] - client_rect[3]) - (win_rect[2] - win_rect[0] - client_rect[2]) // 2
        
        style = self._saved_style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_SYSMENU
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        
        exstyle = self._saved_exstyle | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)
        
        win32gui.SetLayeredWindowAttributes(hwnd, self.colorkey_rgb, 0, win32con.LWA_COLORKEY)
        
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, client_left, client_top,
                              self._saved_client_rect[0], self._saved_client_rect[1],
                              win32con.SWP_FRAMECHANGED)
        
        self.enabled = True
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
        
        self.enabled = False
        self._save_ui_state()
        return True
    
    def toggle(self):
        return self._disable_overlay() if self.enabled else self._enable_overlay()
    
    def is_overlay_mode(self):
        return self.enabled
