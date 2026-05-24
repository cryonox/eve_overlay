"""System tray icon for the supervisor.

The menu is dynamic (module enable toggles + a variable list of tracked DPS
chars), so it's rebuilt from a builder callback whenever state changes. pystray
on Windows bakes the menu at build time, so refresh() reassigns icon.menu and
calls update_menu(); the rebuild is lock-guarded since it runs from both the
pystray thread (clicks) and the supervisor loop (status changes).
"""
import ctypes
from ctypes import wintypes
import threading
import pystray
import pystray._win32 as _pystray_win32
from pystray._util import win32
from loguru import logger

import icon as icon_art

# pystray on Windows only opens the menu on right click; route left click too.
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_orig_on_notify = _pystray_win32.Icon._on_notify


def _on_notify_patched(self, wparam, lparam):
    if lparam == _WM_LBUTTONUP:
        lparam = _WM_RBUTTONUP
    if lparam != _WM_RBUTTONUP or not self._menu_handle:
        return _orig_on_notify(self, wparam, lparam)
    # Show the menu, and if an action asked to keep it open (opacity quick-clicks)
    # re-show it at the SAME anchor so the items don't shift under the cursor.
    point = wintypes.POINT()
    win32.GetCursorPos(ctypes.byref(point))
    px, py = point.x, point.y
    while True:
        self._eve_reopen = False
        win32.SetForegroundWindow(self._hwnd)
        hmenu, descriptors = self._menu_handle
        index = win32.TrackPopupMenuEx(
            hmenu,
            win32.TPM_RIGHTALIGN | win32.TPM_BOTTOMALIGN | win32.TPM_RETURNCMD,
            px, py, self._menu_hwnd, None)
        if index > 0:
            descriptors[index - 1](self)
        if not getattr(self, '_eve_reopen', False):
            break


_pystray_win32.Icon._on_notify = _on_notify_patched


class TrayManager:
    def __init__(self, menu_builder):
        """menu_builder() -> pystray.Menu, called to (re)build the menu."""
        self._build = menu_builder
        self._icon = None
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._icon = pystray.Icon(
            'eve_overlay', icon_art.make_image(64), 'eve_overlay',
            menu=self._build(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        logger.info("tray icon started")

    def refresh(self):
        with self._lock:
            if not self._icon:
                return
            try:
                self._icon.menu = self._build()
                self._icon.update_menu()
            except Exception:
                logger.exception("tray: refresh failed")

    def request_reopen(self):
        """Ask the patched _on_notify to re-show the menu after this click."""
        if self._icon is not None:
            self._icon._eve_reopen = True

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
