from threading import Thread

import msvcrt
import win32gui
import win32ui

import win32api
import win32con

from datetime import datetime
from datetime import timedelta
import ctypes
import win32print
import time
import math
from loguru import logger

timer_trackers = {}
overlay_sizes = {}

def tick(name='default'):
    global timer_trackers
    timer_trackers[name] = time.perf_counter_ns()


def tock(name='default'):
    global timer_trackers
    if name not in timer_trackers:
        return 0

    dur = (time.perf_counter_ns() - timer_trackers[name]) / 1000 / 1000
    if name != 'default':
        logger.info(f'{name} = {dur} ms')
    return dur


def get_system_dpi():
    hdc = win32gui.GetDC(0)
    para_x = 88
    para_y = 90
    x_dpi = win32print.GetDeviceCaps(hdc, para_x)
    y_dpi = win32print.GetDeviceCaps(hdc, para_y)
    return x_dpi, y_dpi


def set_dpi_awareness():
    awareness = ctypes.c_int()
    errorCode = ctypes.windll.shcore.GetProcessDpiAwareness(
        0, ctypes.byref(awareness))
    errorCode = ctypes.windll.shcore.SetProcessDpiAwareness(2)
    success = ctypes.windll.user32.SetProcessDPIAware()


def get_title_bar_dimensions(hwnd):
    x1, y1, x2, y2 = win32gui.GetClientRect(hwnd)
    width = x2-x1
    height = y2-y1
    wx1, wy1, wx2, wy2 = win32gui.GetWindowRect(hwnd)
    wx1, wx2 = wx1-wx1, wx2-wx1
    wy1, wy2 = wy1-wy1, wy2-wy1
    bw = int((wx2-x2)/2.)
    th = wy2-y2-bw
    return th, bw


def nowstr():
    now = datetime.now()
    dt_str = now.strftime("%d/%m/%Y %H:%M:%S")
    return dt_str


def dt2str(dt):
    dt_str = dt.strftime("%d/%m/%Y %H:%M:%S")
    return dt_str


def td_format(td):
    if td.days < 0:
        return '-' + str(timedelta() - td)
    return str(td)


def clear_bit(value, bit):
    return value & ~(1 << bit)


def win_transparent(wclass=None, title='', transparency=80, color_key=(0, 0, 0)):
    try:
        hwnd = win32gui.FindWindow(wclass, title)

        styles = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        # strip classic style
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE,  0)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetWindowPos(hwnd,win32con.HWND_TOPMOST,0,0,0,0,
  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
                              #kwin32con.SWP_NOMOVE | win32con.SWP_NOSIZE) #100,100 is the size of the window

        # set ex style for transparency
        styles = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,  styles)
        win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(
            color_key[0], color_key[1], color_key[2]), transparency, win32con.LWA_ALPHA | win32con.LWA_COLORKEY)
    except:
        pass

def win_normal(wclass=None, title=''):
    try:
        hwnd = win32gui.FindWindow(wclass, title)

        styles = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        styles &= ~(win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, styles)

        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, win32con.WS_OVERLAPPEDWINDOW)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    except:
        pass

def win_no_min_size(wclass=None, title=''):
    try:
        hwnd = win32gui.FindWindow(wclass, title)
        cur_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        new_style = (cur_style & ~(win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX)) | win32con.WS_POPUP
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
        win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
    except:
        pass


def get_ch_con():
    try:
        if msvcrt.kbhit():
            return ord(msvcrt.getch().decode('ASCII'))
    except:
        pass
    return -1
