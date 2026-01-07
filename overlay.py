import win32gui
import win32con
import ctypes
from ctypes import c_int, byref, wintypes
from global_hotkeys import register_hotkeys, start_checking_hotkeys, stop_checking_hotkeys
from loguru import logger

user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)]


class WindowManager:
    def __init__(self, title, cfg, state_file='config.state.yaml', cfg_key='winstate'):
        self._title = title
        self._cfg = cfg
        self._state_file = state_file
        self._cfg_key = cfg_key
        self._last_state = None
        self._dpi_scale = self._get_dpi_scale()
    
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
        state = self._cfg.get(self._cfg_key, {})
        x = int(state.get('x', default_x))
        y = int(state.get('y', default_y))
        w = int(state.get('w', default_w))
        h = int(state.get('h', default_h))
        self._last_state = (x, y, w, h)
        return x, y, w, h
    
    def load_pos(self, default_x=100, default_y=100):
        x, y, _, _ = self.load(default_x, default_y)
        return x, y
    
    def save(self):
        from config import dict2attrdict
        state = self.get_state()
        if state:
            setattr(self._cfg, self._cfg_key, dict2attrdict({'x': state[0], 'y': state[1], 'w': state[2], 'h': state[3]}))
            self._cfg.write([self._cfg_key], self._state_file)
    
    def apply(self, x=None, y=None, w=None, h=None):
        hwnd = self._get_hwnd()
        if hwnd:
            if self._last_state is None:
                self.load()
            if x is None:
                x = self._last_state[0]
            if y is None:
                y = self._last_state[1]
            if w is None:
                w = self._last_state[2]
            if h is None:
                h = self._last_state[3]
            win32gui.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004)
    
    def apply_pos(self, x=None, y=None):
        hwnd = self._get_hwnd()
        if hwnd:
            if x is None or y is None:
                px, py = self._last_state[:2] if self._last_state else self.load_pos()
                x, y = x or px, y or py
            win32gui.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004)
    
    def check_and_save(self):
        cur_state = self.get_state()
        if cur_state and cur_state != self._last_state:
            self._last_state = cur_state
            self.save()
            return True
        return False

class OverlayWindow:
    DEFAULT_COLORKEY = (0x25, 0x25, 0x26)
    DEFAULT_HOTKEY = "alt + shift + t"
    
    def __init__(self, title=None, hwnd=None, colorkey=None, hotkey=None, on_toggle=None):
        self._title = title
        self._hwnd = hwnd
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
        self._setup_hotkey()
    
    @property
    def hwnd(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            return self._hwnd
        if self._title:
            hwnd = win32gui.FindWindow(None, self._title)
            if hwnd:
                return hwnd
        logger.error(f"Window not found (hwnd={self._hwnd}, title={self._title})")
        return None
    
    @property
    def colorkey_rgba(self):
        return [self.colorkey[0], self.colorkey[1], self.colorkey[2], 255]
    
    def _setup_hotkey(self):
        bindings = [
            [self._hotkey, None, self._request_toggle, True],
        ]
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
    
    def enable(self):
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
        return True

    def disable(self):
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
        return True
    
    def toggle(self):
        if self.enabled:
            return self.disable()
        return self.enable()
