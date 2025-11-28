from threading import Thread
import cv2
import numpy as np

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


def reset_overlay_window(win_name, transparency_on, transparency, color_key, mouse_cb, last_im, last_result_im):
    hwnd = win32gui.FindWindow('Main HighGUI class', win_name)
    cx = None
    cy = None
    cw = None
    ch = None
    prev_transparent = False
    if hwnd:
        wx, wy, wx2, wy2 = win32gui.GetWindowRect(hwnd)
        th, bw = get_title_bar_dimensions(hwnd)
        cx = wx + bw
        cy = wy + th
        cw = wx2 - wx - 2 * bw
        ch = wy2 - wy - th - bw
        styles = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        prev_transparent = bool(styles & win32con.WS_EX_LAYERED and styles & win32con.WS_EX_TRANSPARENT)
    if cw is not None and ch is not None:
        if not prev_transparent:
            overlay_sizes[win_name] = (cw, ch)
        elif win_name not in overlay_sizes:
            overlay_sizes[win_name] = (cw, ch)
    cv2.destroyWindow(win_name)
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win_name, cv2.WND_PROP_TOPMOST, 1)
    if mouse_cb is not None:
        cv2.setMouseCallback(win_name, mouse_cb)
    if transparency_on:
        cv2.setWindowProperty(win_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
        win_transparent('Main HighGUI class', win_name, transparency, color_key)
    else:
        win_no_min_size('Main HighGUI class', win_name)
    im = last_result_im if last_result_im is not None else last_im
    if im is not None:
        sw = None
        sh = None
        if win_name in overlay_sizes:
            sw, sh = overlay_sizes[win_name]
        elif cw is not None and ch is not None:
            sw = cw
            sh = ch
        disp_im = im
        if transparency_on and sw is not None and sh is not None:
            ih, iw = im.shape[:2]
            if iw != sw or ih != sh:
                disp_im = cv2.resize(im, (sw, sh), interpolation=cv2.INTER_AREA)
        cv2.imshow(win_name, disp_im)
        cv2.waitKey(1)
        if cx is not None and cy is not None:
            hwnd = win32gui.FindWindow('Main HighGUI class', win_name)
            if hwnd:
                if sw is None or sh is None:
                    sh, sw = disp_im.shape[:2]
                if transparency_on:
                    win32gui.MoveWindow(hwnd, cx, cy, sw, sh, True)
                else:
                    th, bw = get_title_bar_dimensions(hwnd)
                    w = sw + 2 * bw
                    h = sh + th + bw
                    win32gui.MoveWindow(hwnd, cx - bw, cy - th, w, h, True)

def get_ch_con():
    try:
        if msvcrt.kbhit():
            return ord(msvcrt.getch().decode('ASCII'))
    except:
        pass
    return -1


def draw_text_withnewline(text_orig, pos=(0, 0), color=(0, 255, 0), bg_color=(0, 0, 0), font_scale=0.7, font_thickness=None, padding=10):
    if font_thickness is None:
        font_thickness = math.ceil(2 * font_scale)

    x, y = pos
    lines = text_orig.split('\n')

    if not lines:
        return np.zeros((padding*2, padding*2, 3), dtype=np.uint8)

    max_w, total_h = get_text_size_withnewline(text_orig, pos, font_scale, font_thickness)

    im_w = max_w + padding * 2
    im_h = total_h + padding * 2
    im = np.full((im_h, im_w, 3), bg_color, dtype=np.uint8)

    font = cv2.FONT_HERSHEY_SIMPLEX
    current_y = y + padding

    for text in lines:
        text_size, baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
        text_h = text_size[1]
        current_y += text_h
        cv2.putText(im, text, (x + padding, current_y), font, font_scale, color, font_thickness, cv2.LINE_AA)
        current_y += baseline

    return im


def draw_text(im, text, pos=(0, 0), color=(0, 255, 0), bg_color=(0, 0, 0), font_scale=0.7, font_thickness=2):
    font = cv2.FONT_HERSHEY_SIMPLEX

    x, y = pos
    text_size, baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
    text_w, text_h = text_size

    text_y = y + text_h  # Move down by text height from top-left
    cv2.rectangle(im, (x, y), (x+text_w, text_y+baseline), bg_color, -1)
    cv2.putText(im, text, (x, text_y), font, font_scale, color, font_thickness, cv2.LINE_AA)

    return (x, y, x + text_w, text_y + baseline)


def get_text_size_withnewline(text_orig, pos=(0, 0), font_scale=0.5, font_thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    x, y = pos
    max_w = 0
    lines = text_orig.split('\n')

    if not lines:
        return 0, 0

    first_text_size, first_baseline = cv2.getTextSize(lines[0], font, font_scale, font_thickness)
    current_y = y + first_text_size[1]
    final_y = current_y

    for text in lines:
        text_size, baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
        text_w, text_h = text_size
        max_w = max(max_w, text_w)
        final_y = current_y + baseline
        current_y += text_h + baseline

    total_h = final_y - y
    return max_w, total_h


def draw_text_on_image(im, text_orig, pos=(0, 0), color=(0, 255, 0), bg_color=(0, 0, 0), font_scale=0.7, font_thickness=None):
    if font_thickness is None:
        font_thickness = math.ceil(2 * font_scale)

    x, y = pos
    lines = text_orig.split('\n')

    if not lines:
        return (x, y, x, y)

    font = cv2.FONT_HERSHEY_SIMPLEX
    current_y = y
    max_x = x

    for text in lines:
        text_size, baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
        text_w, text_h = text_size
        current_y += text_h

        cv2.rectangle(im, (x, current_y - text_h), (x + text_w, current_y + baseline), bg_color, -1)
        cv2.putText(im, text, (x, current_y), font, font_scale, color, font_thickness, cv2.LINE_AA)

        max_x = max(max_x, x + text_w)
        current_y += baseline

    return (x, y, max_x, current_y)
