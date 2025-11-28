import requests
import pyperclip
import time
import re
from rich import print
import asyncio
import aiohttp
from config import C
import cv2
import numpy as np
import utils
from global_hotkeys import register_hotkeys, start_checking_hotkeys
import webbrowser
from bidict import bidict
from loguru import logger
import json


class DScanAnalyzer:
    def __init__(self):
        self.current_clipboard = ''
        self.state = {}
        self.ignore_alliances = C.dscan.get('ignore_alliances', [])
        self.ignore_corps = C.dscan.get('ignore_corps', [])
        self.display_duration = C.dscan.get('timeout', 30)
        self.zkill_limit = C.dscan.get('zkill_limit', 50)
        self.win_name = "dscan"
        self.transparency_on = C.dscan.get('transparency_on', True)
        self.transparency = C.dscan.get('transparency', 180)
        self.bg_color = C.dscan.get('bg_color', [25, 25, 25])
        self.should_destroy_window = False
        self.last_im = None
        self.last_result_im = None
        utils.set_dpi_awareness()
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
        utils.win_no_min_size('Main HighGUI class', self.win_name)
        self.transparency_on = False
        if self.transparency_on:
            utils.win_transparent('Main HighGUI class',
                                  self.win_name, self.transparency, (64, 64, 64))

        hotkey_transparency = C.dscan.get('hotkey_transparency', 'alt+shift+f')
        hotkey_mode = C.dscan.get('hotkey_mode', 'alt+shift+m')
        hotkey_clear_cache = C.dscan.get('hotkey_clear_cache', 'alt+shift+e')
        bindings = [
            [hotkey_transparency.split('+'), None, self.toggle_transparency],
            # [hotkey_mode.split('+'), None, self.toggle_mode],
            # [hotkey_clear_cache.split('+'), None, self.clear_cache]
        ]
        register_hotkeys(bindings)
        start_checking_hotkeys()
        self.show_status("")

    def toggle_transparency(self):
        self.transparency_on = not self.transparency_on
        self.should_destroy_window = True

    def display(self):
        msg = self.state.get('msg', '')
        if not msg:
            im = np.full((50, 50, 3), C.dscan.transparency_color, np.uint8)
        else:
            im = utils.draw_text_withnewline(
                msg, (0, 0), color=(255, 255, 255), bg_color=self.bg_color,
                font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        self.last_im = im
        cv2.imshow(self.win_name, im)
        cv2.waitKey(1)
        self.handle_transparency()

    def parse_dscan(self, dscan_data):
        self.state['message'] = dscan_data

    def process_clipboard(self):
        try:
            lines = self.current_clipboard.strip().split('\n')
            is_dscan = any('\t' in line for line in lines[:5])
            self.parse_dscan(self.current_clipboard)

        except Exception as e:
            logger.info(f"Error parsing clipboard: {e}")
            return None

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            for char_name, (rect, zkill_link) in self.char_rects.items():
                rx, ry, rw, rh = rect
                if rx <= x <= rx + rw and ry - rh <= y <= ry and zkill_link:
                    webbrowser.open(zkill_link)
                    break

    def handle_transparency(self):
        if self.should_destroy_window:
            utils.reset_overlay_window(
                self.win_name,
                self.transparency_on,
                self.transparency,
                (64, 64, 64),
                self.mouse_callback,
                self.last_im,
                self.last_result_im,
            )
            self.should_destroy_window = False

    def show_status(self, msg):
        self.state['msg'] = msg

    def start(self):
        print("Press Ctrl+C to exit\n")
        try:
            while True:
                clipboard = pyperclip.paste()
                if clipboard != self.current_clipboard:
                    self.current_clipboard = clipboard
                    self.show_status("Working...")
                    self.process_clipboard()
                    self.current_clipboard = clipboard
                self.display()
        except KeyboardInterrupt:
            print("\nExiting...")
            cv2.destroyAllWindows()
