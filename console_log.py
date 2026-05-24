"""On-demand log console for the windowed (console=False) build.

The exe is built without a console, so there's nowhere for logs to show. This
allocates a console window on request and attaches a loguru sink to it, letting
a tray toggle pop the live log up and hide it again.
"""
import ctypes
from ctypes import wintypes
from loguru import logger

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

# 64-bit-safe signatures so HWND/HMENU aren't truncated to 32 bits.
_kernel32.GetConsoleWindow.restype = wintypes.HWND
_kernel32.AllocConsole.restype = wintypes.BOOL
_kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
_user32.GetSystemMenu.restype = wintypes.HMENU
_user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
_user32.DeleteMenu.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]

_SW_HIDE = 0
_SW_SHOW = 5
_SC_CLOSE = 0xF060
_MF_BYCOMMAND = 0x0

_state = {'shown': False, 'sink_id': None, 'stream': None, 'allocated': False}


def is_shown():
    return _state['shown']


def _disable_close_button(hwnd):
    # Stop the X / Alt+F4 from killing the process; hide via the tray instead.
    hmenu = _user32.GetSystemMenu(hwnd, False)
    if hmenu:
        _user32.DeleteMenu(hmenu, _SC_CLOSE, _MF_BYCOMMAND)


def show(level='DEBUG'):
    """Show the log console (allocating one if needed) and start logging to it."""
    if _state['shown']:
        hwnd = _kernel32.GetConsoleWindow()
        if hwnd:
            _user32.ShowWindow(hwnd, _SW_SHOW)
            _user32.SetForegroundWindow(hwnd)
        return

    # Only allocate (and later manage) a console if the process has none. When
    # run from a real terminal we just add the sink and leave that window alone.
    if not _kernel32.GetConsoleWindow():
        if not _kernel32.AllocConsole():
            logger.error("console_log: AllocConsole failed")
            return
        _state['allocated'] = True

    try:
        stream = open('CONOUT$', 'w', buffering=1)
    except OSError:
        logger.exception("console_log: failed to open CONOUT$")
        return

    if _state['allocated']:
        _kernel32.SetConsoleTitleW('eve_overlay log')
        hwnd = _kernel32.GetConsoleWindow()
        if hwnd:
            _disable_close_button(hwnd)
            _user32.ShowWindow(hwnd, _SW_SHOW)
            _user32.SetForegroundWindow(hwnd)

    sink_id = logger.add(stream, level=level, colorize=False)
    _state.update(shown=True, sink_id=sink_id, stream=stream)
    logger.info("console log shown")


def hide():
    """Stop logging to the console and hide the window (kept allocated)."""
    if not _state['shown']:
        return
    if _state['sink_id'] is not None:
        try:
            logger.remove(_state['sink_id'])
        except Exception:
            pass
    if _state['stream']:
        try:
            _state['stream'].close()
        except Exception:
            pass
    if _state['allocated']:
        hwnd = _kernel32.GetConsoleWindow()
        if hwnd:
            _user32.ShowWindow(hwnd, _SW_HIDE)
    _state.update(shown=False, sink_id=None, stream=None)


def toggle(level='DEBUG'):
    """Flip console visibility. Returns the new shown state."""
    if _state['shown']:
        hide()
    else:
        show(level)
    return _state['shown']
