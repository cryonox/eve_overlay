"""System tray icon: toggle overlay state and quit the app.

The tray runs pystray on its own daemon thread. Toggle callbacks must not touch
win32 / dearpygui state directly (that lives on the main thread) -- instead they
set the same "requested" flags the hotkeys use, which the main loop processes.
"""
import threading
import pystray
import pystray._win32 as _pystray_win32
from loguru import logger

import icon as icon_art

# pystray on Windows only opens the menu on right click; route left click
# to the same handler so a single click shows the menu either way.
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONUP = 0x0205
_orig_on_notify = _pystray_win32.Icon._on_notify


def _on_notify_patched(self, wparam, lparam):
    if lparam == _WM_LBUTTONUP:
        lparam = _WM_RBUTTONUP
    return _orig_on_notify(self, wparam, lparam)


_pystray_win32.Icon._on_notify = _on_notify_patched


def _make_icon():
    return icon_art.make_image(64)


class TrayManager:
    def __init__(self, on_toggle_overlay=None, on_toggle_clickthrough=None,
                 on_toggle_text_bg=None, on_toggle_corp_mode=None,
                 on_toggle_monitor_clipboard=None, on_quit=None,
                 is_overlay=None, is_clickthrough=None, is_text_bg=None,
                 is_corp_mode=None, is_monitor_clipboard=None):
        self.on_toggle_overlay = on_toggle_overlay
        self.on_toggle_clickthrough = on_toggle_clickthrough
        self.on_toggle_text_bg = on_toggle_text_bg
        self.on_toggle_corp_mode = on_toggle_corp_mode
        self.on_toggle_monitor_clipboard = on_toggle_monitor_clipboard
        self.on_quit = on_quit
        self.is_overlay = is_overlay or (lambda: False)
        self.is_clickthrough = is_clickthrough or (lambda: False)
        self.is_text_bg = is_text_bg or (lambda: False)
        self.is_corp_mode = is_corp_mode or (lambda: False)
        self.is_monitor_clipboard = is_monitor_clipboard or (lambda: True)
        self._icon = None
        self._thread = None

    def _wrap_toggle(self, cb):
        def handler(icon, item):
            if cb:
                try:
                    cb()
                except Exception:
                    logger.exception("tray: toggle handler failed")
            if self._icon:
                self._icon.update_menu()
        return handler

    def start(self):
        def quit_app(icon, item):
            icon.stop()
            if self.on_quit:
                self.on_quit()

        self._icon = pystray.Icon(
            'eve_overlay',
            _make_icon(),
            'eve_overlay',
            menu=pystray.Menu(
                pystray.MenuItem(
                    'Overlay', self._wrap_toggle(self.on_toggle_overlay),
                    checked=lambda item: self.is_overlay(),
                ),
                pystray.MenuItem(
                    'Click-through', self._wrap_toggle(self.on_toggle_clickthrough),
                    checked=lambda item: self.is_clickthrough(),
                ),
                pystray.MenuItem(
                    'Show background', self._wrap_toggle(self.on_toggle_text_bg),
                    checked=lambda item: self.is_text_bg(),
                ),
                pystray.MenuItem(
                    'Corp mode (aggregate)', self._wrap_toggle(self.on_toggle_corp_mode),
                    checked=lambda item: self.is_corp_mode(),
                ),
                pystray.MenuItem(
                    'Monitor clipboard', self._wrap_toggle(self.on_toggle_monitor_clipboard),
                    checked=lambda item: self.is_monitor_clipboard(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Exit', quit_app),
            ),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        logger.info("tray icon started")

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                logger.exception("tray: stop failed")
