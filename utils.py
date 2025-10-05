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
from logger import logger

timer_trackers = {}

def tick(name='default'):
    global timer_trackers
    timer_trackers[name] = time.perf_counter_ns()


def tock(name='default'):
    global timer_trackers
    if name not in timer_trackers:
        return 0
    
    dur = (time.perf_counter_ns() - timer_trackers[name]) / 1000 / 1000
    if name != 'default':
        logger.log(f'{name} = {dur} ms')
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
        # win32gui.SetWindowPos(hwnd,win32con.HWND_TOPMOST,0,0,0,0,win32con.SWP_NOMOVE | win32con.SWP_NOSIZE) #100,100 is the size of the window

        # set ex style for transparency
        styles = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,  styles)
        win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(
            color_key[0], color_key[1], color_key[2]), transparency, win32con.LWA_ALPHA | win32con.LWA_COLORKEY)
    except:
        pass


def get_ch_con():
    try:
        if msvcrt.kbhit():
            return ord(msvcrt.getch().decode('ASCII'))
    except:
        pass
    return -1


def draw_text_withnewline(im, text_orig, pos=(0, 0), color=(0, 255, 0), bg_color=(0, 0, 0), font_scale=0.7, font_thickness=None):
    font = cv2.FONT_HERSHEY_SIMPLEX
    if font_thickness is None:
        font_thickness = math.ceil(2 * font_scale)

    x, y = pos
    start_x, start_y = x, y
    max_w = 0
    lines = text_orig.split('\n')
    
    if not lines:
        return (x, y, x, y)
    
    first_text_size, first_baseline = cv2.getTextSize(lines[0], font, font_scale, font_thickness)
    current_y = y + first_text_size[1]
    final_y = current_y
    
    for text in lines:
        text_size, baseline = cv2.getTextSize(text, font, font_scale, font_thickness)
        text_w, text_h = text_size
        
        cv2.rectangle(im, (x, current_y-text_h), (x+text_w, current_y+baseline), bg_color, -1)
        cv2.putText(im, text, (x, current_y), font, font_scale, color, font_thickness, cv2.LINE_AA)
        
        max_w = max(max_w, text_w)
        final_y = current_y + baseline
        current_y += text_h + baseline
    
    return (start_x, start_y, start_x + max_w, final_y)


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
