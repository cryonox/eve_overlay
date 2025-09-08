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
from logger import logger
import json


async def get_zkill_data_async(session, char_id, max_retries=3):
    for attempt in range(max_retries + 1):
        try:
            stats_url = f"https://zkillboard.com/api/stats/characterID/{char_id}/"
            headers = {'User-Agent': 'Eve Overlay'}
            async with session.get(stats_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    # Check for zkill's "Invalid type or id" response
                    if isinstance(data, dict) and data.get('error') == 'Invalid type or id':
                        return {'error': 'not_found'}
                    return data
                elif response.status == 429 or response.status == 1015:  # Cloudflare rate limit
                    return {'error': 'rate_limited'}
                elif response.status == 404:
                    return {'error': 'not_found'}
                else:
                    return {'error': 'api_error', 'status': response.status}
        except Exception as e:
            if attempt < max_retries:
                wait_time = (2 ** attempt) * 2
                logger.log(f"Network error for char {char_id}, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
                continue
            logger.log(f"Error fetching zkill data for {char_id}: {e}")
            return {'error': 'network_error'}
    
    return {'error': 'max_retries_exceeded'}


class NameIdCache:
    def __init__(self):
        self.data = bidict()

    def get_id(self, name):
        return self.data.inverse.get(name)

    def get_name(self, id):
        return self.data.get(id)

    def add_mapping(self, name, id):
        self.data[id] = name


class DScanAnalyzer:
    def __init__(self):
        self.zkill_base = "https://zkillboard.com/api"
        self.ignore_alliances = C.dscan.get('ignore_alliances', [])
        self.ignore_corps = C.dscan.get('ignore_corps', [])
        self.display_duration = C.dscan.get('timeout', 30)
        self.zkill_limit = C.dscan.get('zkill_limit', 50)
        self.win_name = "D-Scan Analysis"
        self.transparency_on = C.dscan.get('transparency_on', True)
        self.transparency = C.dscan.get('transparency', 180)
        self.bg_color = C.dscan.get('bg_color', [25, 25, 25])
        self.should_destroy_window = False
        self.last_im = None
        self.last_result_im = None
        self.char_rects = {}
        self.result_start_time = None
        self.last_result_total_time = None
        self.name_cache = NameIdCache()
        self.zkill_cache = {}
        self.esi_char_cache = {}
        self.ticker_cache = {}
        self.aggregated_mode = False
        self.mode_changed = False
        cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        if self.transparency_on:
            utils.win_transparent('Main HighGUI class',
                                  self.win_name, self.transparency, (64, 64, 64))

        hotkey_transparency = C.dscan.get('hotkey_transparency', 'alt+shift+f')
        hotkey_mode = C.dscan.get('hotkey_mode', 'alt+shift+m')
        hotkey_clear_cache = C.dscan.get('hotkey_clear_cache', 'alt+shift+e')
        bindings = [
            [hotkey_transparency.split('+'), None, self.toggle_transparency],
            [hotkey_mode.split('+'), None, self.toggle_mode],
            [hotkey_clear_cache.split('+'), None, self.clear_cache]
        ]
        register_hotkeys(bindings)
        start_checking_hotkeys()

        self.show_status("")

        self.last_ship_counts = None
        self.previous_ship_counts = None
        self.is_diff_mode = False
        self.last_dscan_time = None

    def toggle_transparency(self):
        self.transparency_on = not self.transparency_on
        self.should_destroy_window = True

    def handle_transparency(self):
        if self.should_destroy_window:
            cv2.destroyWindow(self.win_name)
            cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
            cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
            cv2.setMouseCallback(self.win_name, self.mouse_callback)

            if self.transparency_on:
                cv2.setWindowProperty(
                    self.win_name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
                utils.win_transparent(
                    'Main HighGUI class', self.win_name, self.transparency, (64, 64, 64))

            self.should_destroy_window = False

            im_to_show = self.last_result_im if self.last_result_im is not None else self.last_im
            if im_to_show is not None:
                cv2.imshow(self.win_name, im_to_show)
                cv2.waitKey(1)

    def show_status(self, message):
        if message == "":
            im = np.full((50, 50, 3), C.dscan.transparency_color, np.uint8)
            cv2.imshow(self.win_name, im)
            cv2.waitKey(1)
            return
        w, h = utils.get_text_size_withnewline(
            message, (10, 10), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        im = np.full((h, w, 3), C.dscan.transparency_color, np.uint8)
        utils.draw_text_withnewline(
            im, message, (10, 10), color=(255, 255, 255), bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
        self.last_im = im
        cv2.imshow(self.win_name, im)
        cv2.waitKey(1)

    def get_clipboard_data(self):
        try:
            return pyperclip.paste()
        except Exception as e:
            logger.log(f"Error reading clipboard: {e}")
            return None

    async def parse_local(self, dscan_data):
        try:
            lines = dscan_data.strip().split('\n')
            char_names = []
            for line in lines:
                char_name = line.strip()
                if char_name:
                    char_names.append(char_name)

            data = await self.process_names_esi(char_names)

            if not data:
                self.show_status("")
                return

            filtered_data = [
                char_data for char_data in data if not self.should_ignore_character(char_data)]
            if not filtered_data:
                self.show_status("")
                return

            self.result_start_time = time.time()
            self.last_parsed_data = filtered_data

            if self.aggregated_mode:
                im = self.create_aggregated_display(filtered_data)
                if im is not None:
                    self.last_result_im = im
                    self.last_im = im
                    cv2.imshow(self.win_name, im)
                    cv2.waitKey(1)
                    self.handle_transparency()
            else:
                # Use zkill data already fetched in process_names_esi
                zkill_results = []
                for char_data in filtered_data:
                    char_id = char_data.get('char_id')
                    zkill_data = self.zkill_cache.get(char_id)
                    zkill_results.append(zkill_data)
                
                self.last_zkill_results = zkill_results

                im = self.create_display_image_from_processed_data(
                    filtered_data, zkill_results)
                if im is not None:
                    self.last_result_im = im
                    self.last_im = im
                    cv2.imshow(self.win_name, im)
                    cv2.waitKey(1)
                    self.handle_transparency()

        except Exception as e:
            logger.log(f"Error parsing local: {e}")
            return None

    async def parse_dscan(self, dscan_data):
        try:
            
            # Load ship data
            with open('ships.json', 'r') as f:
                ships = json.load(f)
            
            # Clear diff mode if too much time has passed
            current_time = time.time()
            if self.last_dscan_time and current_time - self.last_dscan_time > 60:  # 60 seconds
                self.last_ship_counts = None
                self.previous_ship_counts = None
                self.is_diff_mode = False
            
            lines = dscan_data.strip().split('\n')
            ship_counts = {}
            
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 3:
                    ship_name = parts[2].strip()
                    
                    # Handle ship names with pilot info (e.g., "Venture - Pilot Name")
                    if ' - ' in ship_name:
                        ship_name = ship_name.split(' - ')[0].strip()
                    
                    # Skip non-ship items
                    if ship_name not in ships:
                        continue
                    
                    ship_info = ships[ship_name]
                    group_name = ship_info['group_name']
                    
                    if group_name not in ship_counts:
                        ship_counts[group_name] = {}
                    
                    if ship_name not in ship_counts[group_name]:
                        ship_counts[group_name][ship_name] = 0
                    
                    ship_counts[group_name][ship_name] += 1
            
            if not ship_counts:
                self.show_status("No ships found in dscan")
                return
            
            # Check if this is a consecutive dscan for diff mode
            if self.last_ship_counts is not None:
                self.previous_ship_counts = self.last_ship_counts
                self.is_diff_mode = True
            else:
                self.is_diff_mode = False
            
            self.result_start_time = time.time()
            self.last_dscan_time = current_time
            self.last_ship_counts = ship_counts
            
            # Create display
            im = self.create_dscan_display(ship_counts)
            if im is not None:
                self.last_result_im = im
                self.last_im = im
                cv2.imshow(self.win_name, im)
                cv2.waitKey(1)
                self.handle_transparency()
                
        except Exception as e:
            logger.log(f"Error parsing dscan: {e}")
            return None

    def parse_clipboard(self, clipboard_data):
        try:
            lines = clipboard_data.strip().split('\n')

            is_dscan = any('\t' in line for line in lines[:5])

            if is_dscan:
                return asyncio.run(self.parse_dscan(clipboard_data))
            else:
                # Reset dscan state when switching to local
                self.last_ship_counts = None
                self.previous_ship_counts = None
                self.is_diff_mode = False
                return asyncio.run(self.parse_local(clipboard_data))
        except Exception as e:
            logger.log(f"Error parsing clipboard: {e}")
            return None

    async def process_names_esi(self, char_names):
        try:
            result = await self.resolve_names_to_ids_esi(char_names)

            # Check if we should skip zkill due to limit
            skip_zkill = len(result) > self.zkill_limit
            
            if skip_zkill:
                logger.log(f"Skipping zkill lookup for {len(result)} characters (limit: {self.zkill_limit})")
                # Force aggregate mode when skipping zkill
                if not self.aggregated_mode:
                    self.aggregated_mode = True
                    self.mode_changed = True
                    logger.log("Automatically switched to aggregate mode due to zkill limit")
            else:
                # Fetch zkill data for all characters
                utils.tick()
                connector = aiohttp.TCPConnector(limit=200)
                async with aiohttp.ClientSession(connector=connector) as session:
                    zkill_tasks = [self.get_zkill_data_cached(
                        session, char['char_id']) for char in result]
                    zkill_results = await asyncio.gather(*zkill_tasks)

                all_results = [(char, zkill_data) for char, zkill_data in zip(result, zkill_results)]
                utils.tock('zkill work')

            # Get corp/alliance info for chars not on zkill or when skipping zkill
            chars_needing_esi = []
            if skip_zkill:
                chars_needing_esi = [char['char_id'] for char in result]
            else:
                for char, zkill_data in all_results:
                    if zkill_data is None or (isinstance(zkill_data, dict) and 'error' in zkill_data):
                        chars_needing_esi.append(char['char_id'])

            esi_char_info = {}
            if chars_needing_esi:
                esi_char_info = await self.get_char_info_esi(chars_needing_esi)

            corp_ids = []
            alliance_ids = []
            
            if skip_zkill:
                # Use only ESI data
                for char in result:
                    char_info = esi_char_info.get(char['char_id'], {})
                    corp_id = char_info.get('corporation_id')
                    alliance_id = char_info.get('alliance_id')
                    
                    if corp_id:
                        corp_ids.append(corp_id)
                    if alliance_id:
                        alliance_ids.append(alliance_id)
            else:
                # Use zkill data where available, ESI otherwise
                for char, zkill_data in all_results:
                    if zkill_data and zkill_data.get('info') and 'error' not in zkill_data:
                        corp_id = zkill_data['info'].get('corporationID')
                        alliance_id = zkill_data['info'].get('allianceID')
                    else:
                        char_info = esi_char_info.get(char['char_id'], {})
                        corp_id = char_info.get('corporation_id')
                        alliance_id = char_info.get('alliance_id')
                    
                    if corp_id:
                        corp_ids.append(corp_id)
                    if alliance_id:
                        alliance_ids.append(alliance_id)

            id_to_name = await self.ids_to_names_esi(corp_ids, alliance_ids)
            tickers = await self.get_corp_alliance_tickers(corp_ids, alliance_ids)
            
            logger.log(f'Resolved names: {len(id_to_name)} entries')
            logger.log(f'Resolved tickers: {len(tickers)} entries')

            char_data_list = []
            
            if skip_zkill:
                # Build char data without zkill info
                for char in result:
                    char_info = esi_char_info.get(char['char_id'], {})
                    corp_id = char_info.get('corporation_id')
                    alliance_id = char_info.get('alliance_id')

                    char_data = {
                        'char_name': char['char_name'],
                        'char_id': char['char_id'],
                        'corp_id': corp_id,
                        'alliance_id': alliance_id,
                        'corp_name': id_to_name.get(corp_id, 'Unknown') if corp_id else 'Unknown',
                        'alliance_name': id_to_name.get(alliance_id) if alliance_id else None,
                        'corp_ticker': tickers.get(corp_id, {}).get('ticker') if corp_id else None,
                        'alliance_ticker': tickers.get(alliance_id, {}).get('ticker') if alliance_id else None,
                        'zkill_link': f"https://zkillboard.com/character/{char['char_id']}/"
                    }
                    char_data_list.append(char_data)
            else:
                # Build char data with zkill info
                for char, zkill_data in all_results:
                    if zkill_data and zkill_data.get('info'):
                        corp_id = zkill_data['info'].get('corporationID')
                        alliance_id = zkill_data['info'].get('allianceID')
                    else:
                        char_info = esi_char_info.get(char['char_id'], {})
                        corp_id = char_info.get('corporation_id')
                        alliance_id = char_info.get('alliance_id')

                    char_data = {
                        'char_name': char['char_name'],
                        'char_id': char['char_id'],
                        'corp_id': corp_id,
                        'alliance_id': alliance_id,
                        'corp_name': id_to_name.get(corp_id, 'Unknown') if corp_id else 'Unknown',
                        'alliance_name': id_to_name.get(alliance_id) if alliance_id else None,
                        'corp_ticker': tickers.get(corp_id, {}).get('ticker') if corp_id else None,
                        'alliance_ticker': tickers.get(alliance_id, {}).get('ticker') if alliance_id else None,
                        'zkill_link': f"https://zkillboard.com/character/{char['char_id']}/"
                    }
                    char_data_list.append(char_data)

            return char_data_list
        except Exception as e:
            logger.log(f"Error processing names via ESI: {e}")
            return None

    async def get_zkill_stats_async(self, session, char_name):
        try:
            search_url = f"{self.zkill_base}/search/{char_name}/"
            async with session.get(search_url, timeout=10) as response:
                if response.status != 200:
                    return None
                search_data = await response.json()

            char_id = None
            for result in search_data:
                if result.get('type') == 'character' and result.get('name', '').lower() == char_name.lower():
                    char_id = result.get('id')
                    break

            if not char_id:
                return None

            return await self.get_zkill_data_cached(session, char_id)
        except Exception as e:
            logger.log(f"Error fetching zkill data for {char_name}: {e}")
        return None

    async def fetch_zkill_data(self, char_data):
        async with aiohttp.ClientSession() as session:
            char_id = char_data.get('char_id')
            return await self.get_zkill_data_cached(session, char_id)

    def should_ignore_character(self, char_data):
        corp_name = char_data.get('corp_name', '')
        alliance_name = char_data.get('alliance_name', '')
        corp_ticker = char_data.get('corp_ticker', '')
        alliance_ticker = char_data.get('alliance_ticker', '')
        
        return (corp_name in self.ignore_corps or 
                alliance_name in self.ignore_alliances or
                corp_ticker in self.ignore_corps or
                alliance_ticker in self.ignore_alliances)

    def create_display_image_from_processed_data(self, char_data_list, zkill_results=None):
        if not char_data_list:
            return None

        self.char_rects = {}
        combined_data = []

        for i, char_data in enumerate(char_data_list):
            zkill_data = zkill_results[i] if zkill_results and i < len(zkill_results) else None

            if zkill_data is None or (isinstance(zkill_data, dict) and 'error' in zkill_data):
                if zkill_data and zkill_data.get('error') == 'rate_limited':
                    status = 'Rate limited'
                    color = (0, 165, 255)  # Orange
                elif zkill_data and zkill_data.get('error') == 'not_found':
                    status = 'Not on zkill'
                    color = (128, 128, 128)  # Gray
                else:
                    status = 'API error'
                    color = (0, 0, 255)  # Red
                
                combined_data.append({
                    'name': char_data['char_name'],
                    'zkill_status': status,
                    'zkill_link': char_data.get('zkill_link'),
                    'color': color
                })
            else:
                danger = zkill_data.get('dangerRatio', 0)
                kills = zkill_data.get('shipsDestroyed', 0)
                losses = zkill_data.get('shipsLost', 0)

                combined_data.append({
                    'name': char_data['char_name'],
                    'danger': danger,
                    'kills': kills,
                    'losses': losses,
                    'zkill_link': char_data.get('zkill_link')
                })

        # Sort by danger, putting "Not on zkill" entries at the end
        combined_data.sort(key=lambda x: x.get('danger', -1), reverse=True)

        remaining_time = max(0, self.display_duration - (time.time() - self.result_start_time)
                             ) if self.result_start_time else self.display_duration
        pilot_count = len(combined_data)
        if self.last_result_total_time:
            header_text = f"Pilots: {pilot_count} | Time: {self.last_result_total_time/1000:.2f}s | Timeout: {remaining_time:.0f}s"
        else:
            header_text = f"Pilots: {pilot_count} | Timeout: {remaining_time:.0f}s"

        text_lines = [header_text]
        for data in combined_data:
            name = data['name'][:20]
            if 'zkill_status' in data:
                text = f"{name} | {data['zkill_status']}"
            else:
                text = f"{name} | D:{data['danger']:.1f} K:{data['kills']} L:{data['losses']}"
            text_lines.append(text)

        full_text = '\n'.join(text_lines)
        w, h = utils.get_text_size_withnewline(
            full_text, (20, 20), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        im = np.zeros((h, w, 3), dtype=np.uint8)
        im[:] = C.dscan.transparency_color

        y = utils.draw_text_withnewline(im, header_text, (10, 20), color=(
            0, 255, 0), bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        for data in combined_data:
            name = data['name'][:20]
            if 'zkill_status' in data:
                text = f"{name} | {data['zkill_status']}"
                color = data.get('color', (128, 128, 128))
            else:
                text = f"{name} | D:{data['danger']:.1f} K:{data['kills']} L:{data['losses']}"
                color = (255, 255, 255) if data['danger'] == 0 else (0, 0, 255) if data['danger'] >= 80 else (0, 255, 255)

            text_w, text_h = utils.get_text_size_withnewline(
                text, (10, y), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

            self.char_rects[data['name']] = (
                (10, y, text_w, text_h), data['zkill_link'])

            y = utils.draw_text_withnewline(
                im, text, (10, y), color=color, bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        return im

    def create_aggregated_display(self, char_data_list):
        if not char_data_list:
            return None

        corp_counts = {}
        alliance_counts = {}

        for char_data in char_data_list:
            corp_name = char_data.get('corp_name', 'Unknown')
            alliance_name = char_data.get('alliance_name')

            corp_counts[corp_name] = corp_counts.get(corp_name, 0) + 1
            if alliance_name:
                alliance_counts[alliance_name] = alliance_counts.get(
                    alliance_name, 0) + 1

        remaining_time = max(0, self.display_duration - (time.time() - self.result_start_time)
                             ) if self.result_start_time else self.display_duration
        pilot_count = len(char_data_list)

        if self.last_result_total_time:
            header_text = f"Aggregated | Pilots: {pilot_count} | Time: {self.last_result_total_time/1000:.2f}s | Timeout: {remaining_time:.0f}s"
        else:
            header_text = f"Aggregated | Pilots: {pilot_count} | Timeout: {remaining_time:.0f}s"

        text_lines = [header_text, ""]

        if alliance_counts:
            text_lines.append("Alliances:")
            sorted_alliances = sorted(
                alliance_counts.items(), key=lambda x: x[1], reverse=True)
            for alliance_name, count in sorted_alliances:
                text_lines.append(f"  {alliance_name}: {count}")

        if corp_counts:
            if alliance_counts:
                text_lines.append("")
            text_lines.append("Corporations:")
            sorted_corps = sorted(corp_counts.items(),
                                  key=lambda x: x[1], reverse=True)
            for corp_name, count in sorted_corps:
                text_lines.append(f"  {corp_name}: {count}")

        full_text = '\n'.join(text_lines)
        w, h = utils.get_text_size_withnewline(
            full_text, (20, 20), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        im = np.zeros((h, w, 3), dtype=np.uint8)
        im[:] = C.dscan.transparency_color

        utils.draw_text_withnewline(im, full_text, (10, 20), color=(255, 255, 255),
                                    bg_color=self.bg_color, font_scale=C.dscan.font_scale,
                                    font_thickness=C.dscan.font_thickness)

        return im

    def create_dscan_display(self, ship_counts):
        try:
            # Calculate ship diffs if in diff mode
            if ship_counts is None:
                return None
            ship_diffs = {}
            if self.is_diff_mode and self.previous_ship_counts is not None:
                ship_diffs = self.calculate_ship_diffs(self.previous_ship_counts, ship_counts)
            
            # Flatten ship data and calculate totals
            ship_list = []
            group_totals = {}
            total_ships = 0
            
            # Current ships
            for group_name, ships_in_group in ship_counts.items():
                group_total = sum(ships_in_group.values())
                group_totals[group_name] = group_total
                total_ships += group_total
                
                for ship_name, count in ships_in_group.items():
                    diff = ship_diffs.get(ship_name, 0)
                    ship_list.append((ship_name, count, diff))
            
            # Add ships that disappeared (show as 0 count) - only for current scan
            if self.is_diff_mode and self.previous_ship_counts is not None:
                for group_name, ships_in_group in self.previous_ship_counts.items():
                    for ship_name, prev_count in ships_in_group.items():
                        # Only show if ship is not in current scan at all
                        found_in_current = False
                        for curr_group, curr_ships in ship_counts.items():
                            if ship_name in curr_ships:
                                found_in_current = True
                                break
                        
                        if not found_in_current:
                            ship_list.append((ship_name, 0, -prev_count))
            
            # Sort ships by count (descending), zero counts go last
            ship_list.sort(key=lambda x: (x[1] == 0, -x[1]))
            
            # Sort groups by count (descending)
            sorted_groups = sorted(group_totals.items(), key=lambda x: x[1], reverse=True)
            
            # Calculate remaining time
            remaining_time = max(0, self.display_duration - (time.time() - self.result_start_time)
                                 ) if self.result_start_time else self.display_duration
            
            # Build display lines with diff info
            mode_text = " " if self.is_diff_mode else ""
            header_text = f"D-Scan{mode_text} | Total Ships: {total_ships} | Timeout: {remaining_time:.0f}s"
            left_lines = [header_text, ""]
            
            for ship_name, count, diff in ship_list:
                if diff > 0:
                    left_lines.append(f"{ship_name}: {count} (+{diff})")
                elif diff < 0:
                    left_lines.append(f"{ship_name}: {count} ({diff})")
                else:
                    left_lines.append(f"{ship_name}: {count}")
            
            right_lines = ["Ship Categories:", ""]
            for group_name, count in sorted_groups:
                right_lines.append(f"{group_name}: {count}")
            
            # Calculate text dimensions
            left_text = '\n'.join(left_lines)
            right_text = '\n'.join(right_lines)
            
            left_w, left_h = utils.get_text_size_withnewline(
                left_text, (20, 20), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
            right_w, right_h = utils.get_text_size_withnewline(
                right_text, (20, 20), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
            
            # Create image with both columns
            padding = 20
            total_w = left_w + right_w + padding * 3
            total_h = max(left_h, right_h) + 40
            
            im = np.full((total_h, total_w, 3), C.dscan.transparency_color, np.uint8)
            
            # Draw left column with color coding
            self.draw_dscan_text_with_colors(im, left_lines, ship_list, (20, 20))
            
            # Draw right column
            right_x = left_w + padding * 2
            utils.draw_text_withnewline(
                im, right_text, (right_x, 20), color=(255, 255, 255), bg_color=self.bg_color,
                font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)
            
            return im
            
        except Exception as e:
            logger.log(f"Error creating dscan display: {e}")
            return None

    def calculate_ship_diffs(self, prev_counts, curr_counts):
        """Calculate differences between previous and current ship counts"""
        diffs = {}
        
        # Check all current ships
        for group_name, ships_in_group in curr_counts.items():
            for ship_name, curr_count in ships_in_group.items():
                prev_count = 0
                if group_name in prev_counts and ship_name in prev_counts[group_name]:
                    prev_count = prev_counts[group_name][ship_name]
                
                diff = curr_count - prev_count
                if diff != 0:
                    diffs[ship_name] = diff
        
        return diffs

    def draw_dscan_text_with_colors(self, im, text_lines, ship_data, pos):
        """Draw dscan text with color coding for diffs"""
        x, y = pos
        
        for i, line in enumerate(text_lines):
            if i < 2:  # Header lines
                color = (255, 255, 255)
            elif i - 2 < len(ship_data):
                ship_name, count, diff = ship_data[i - 2]
                if count == 0 and diff < 0:
                    color = (0, 0, 255)  # Red for removed ships
                elif diff > 0:
                    color = (0, 255, 0)  # Green for additions
                elif diff < 0:
                    color = (0, 0, 255)  # Red for removals
                else:
                    color = (255, 255, 255)  # White for unchanged
            else:
                color = (255, 255, 255)
            
            y = utils.draw_text_withnewline(
                im, line, (x, y), color=color, bg_color=self.bg_color,
                font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            for char_name, (rect, zkill_link) in self.char_rects.items():
                rx, ry, rw, rh = rect
                if rx <= x <= rx + rw and ry - rh <= y <= ry and zkill_link:
                    webbrowser.open(zkill_link)
                    break

    def monitor_clipboard(self):
        print("Press Ctrl+C to exit\n")
        last_clipboard = ""
        
        try:
            while True:
                current_clipboard = self.get_clipboard_data()
                if current_clipboard and current_clipboard != last_clipboard:
                    self.show_status("Working...")

                    utils.tick()
                    self.parse_clipboard(current_clipboard)
                    self.last_result_total_time = utils.tock()
                    last_clipboard = current_clipboard

                if self.result_start_time and time.time() - self.result_start_time >= self.display_duration:
                    self.show_status("")
                    self.result_start_time = None
                    self.last_result_im = None
                
                # Single display update per loop
                im_to_show = None
                if self.result_start_time:
                    if hasattr(self, 'last_ship_counts'):
                        im_to_show = self.create_dscan_display(self.last_ship_counts)
                    elif hasattr(self, 'last_parsed_data'):
                        if self.aggregated_mode:
                            im_to_show = self.create_aggregated_display(self.last_parsed_data)
                        elif hasattr(self, 'last_zkill_results'):
                            im_to_show = self.create_display_image_from_processed_data(
                                self.last_parsed_data, self.last_zkill_results)
                
                if im_to_show is not None:
                    cv2.imshow(self.win_name, im_to_show)
                
                # Handle mode changes
                if self.mode_changed and hasattr(self, 'last_parsed_data'):
                    if self.aggregated_mode:
                        im = self.create_aggregated_display(
                            self.last_parsed_data)
                    else:
                        im = self.create_display_image_from_processed_data(
                            self.last_parsed_data, getattr(self, 'last_zkill_results', None))
                    if im is not None:
                        self.last_result_im = im
                        self.last_im = im
                        cv2.imshow(self.win_name, im)
                        # Reset timeout when switching modes
                        if not self.result_start_time:
                            self.result_start_time = time.time()
                    self.mode_changed = False

                cv2.waitKey(100)
                self.handle_transparency()

        except KeyboardInterrupt:
            print("\nExiting...")
            cv2.destroyAllWindows()

    async def _resolve_names_batch_esi(self, char_names):
        """Internal function to resolve <=500 character names to IDs using ESI"""
        names_url = "https://esi.evetech.net/latest/universe/ids/"

        async with aiohttp.ClientSession() as session:
            async with session.post(names_url, json=char_names) as response:
                if response.status != 200:
                    logger.log(
                        f"Failed to resolve names batch: {response.status}")
                    return []

                names_data = await response.json()
                char_ids = {char['name']: char['id']
                            for char in names_data.get('characters', [])}

                return [{'char_name': name, 'char_id': char_id} for name, char_id in char_ids.items()]

    async def resolve_names_to_ids_esi(self, char_names):
        start_time = time.time()
        try:
            cached_results = []
            uncached_names = []

            for name in char_names:
                cached_id = self.name_cache.get_id(name)
                if cached_id:
                    cached_results.append(
                        {'char_name': name, 'char_id': cached_id})
                else:
                    uncached_names.append(name)

            if not uncached_names:
                return cached_results

            all_results = cached_results.copy()
            chunk_size = 500
            logger.log(f"Resolving {len(uncached_names)} names via ESI")
            for i in range(0, len(uncached_names), chunk_size):
                chunk = uncached_names[i:i + chunk_size]
                chunk_results = await self._resolve_names_batch_esi(chunk)

                for result in chunk_results:
                    self.name_cache.add_mapping(
                        result['char_name'], result['char_id'])

                all_results.extend(chunk_results)

            return all_results

        except Exception as e:
            elapsed = time.time() - start_time
            logger.log(
                f"Error resolving names via ESI after {elapsed:.2f}s: {e}")
            return []
        finally:
            elapsed = time.time() - start_time
            logger.log(f"Total ESI resolution time: {elapsed:.2f}s")

    async def _resolve_ids_batch_esi(self, corp_ids, alliance_ids):
        """Internal function to resolve <=1000 corp/alliance IDs to names using ESI"""
        names_url = "https://esi.evetech.net/latest/universe/names/"

        all_ids = list(corp_ids) + list(alliance_ids)
        if not all_ids:
            return {}

        async with aiohttp.ClientSession() as session:
            async with session.post(names_url, json=all_ids) as response:
                if response.status != 200:
                    logger.log(
                        f"Failed to resolve IDs batch: {response.status}")
                    return {}

                names_data = await response.json()
                return {item['id']: item['name'] for item in names_data}

    async def ids_to_names_esi(self, corp_ids, alliance_ids):
        start_time = time.time()
        try:
            corp_ids = set(id for id in corp_ids if id and id != 0)
            alliance_ids = set(id for id in alliance_ids if id and id != 0)

            cached_results = {}
            uncached_ids = []

            for id in list(corp_ids) + list(alliance_ids):
                cached_name = self.name_cache.get_name(id)
                if cached_name:
                    cached_results[id] = cached_name
                else:
                    uncached_ids.append(id)

            logger.log(f'Cached ID->name results: {len(cached_results)}')
            logger.log(f'Uncached IDs: {len(uncached_ids)}')

            if not uncached_ids:
                return cached_results

            all_results = cached_results.copy()
            chunk_size = 1000

            for i in range(0, len(uncached_ids), chunk_size):
                chunk = uncached_ids[i:i + chunk_size]
                chunk_corp_ids = [id for id in chunk if id in corp_ids]
                chunk_alliance_ids = [id for id in chunk if id in alliance_ids]

                chunk_results = await self._resolve_ids_batch_esi(chunk_corp_ids, chunk_alliance_ids)

                logger.log(
                    f'Chunk resolved {len(chunk_results)} names from {len(chunk)} IDs')

                for id, name in chunk_results.items():
                    self.name_cache.add_mapping(name, id)

                all_results.update(chunk_results)

            return all_results

        except Exception as e:
            elapsed = time.time() - start_time
            logger.log(
                f"Error resolving IDs via ESI after {elapsed:.2f}s: {e}")
            return {}
        finally:
            elapsed = time.time() - start_time
            logger.log(f"Total ESI ID resolution time: {elapsed:.2f}s")

    async def get_zkill_data_cached(self, session, char_id):
        if char_id in self.zkill_cache:
            cached_data = self.zkill_cache[char_id]
            # Don't use cached rate limit errors - retry them
            if isinstance(cached_data, dict) and cached_data.get('error') == 'rate_limited':
                pass  # Fall through to fetch again
            else:
                return cached_data

        data = await get_zkill_data_async(session, char_id)
        # Only cache successful responses and permanent errors (not rate limits)
        if data is not None and not (isinstance(data, dict) and data.get('error') == 'rate_limited'):
            self.zkill_cache[char_id] = data
        return data

    def toggle_mode(self):
        self.aggregated_mode = not self.aggregated_mode
        self.mode_changed = True

    async def get_char_info_esi(self, char_ids):
        """Get character corporation and alliance info from ESI"""
        char_info = {}
        uncached_ids = []
        
        # Check cache first
        for char_id in char_ids:
            if char_id in self.esi_char_cache:
                char_info[char_id] = self.esi_char_cache[char_id]
            else:
                uncached_ids.append(char_id)
        
        if not uncached_ids:
            return char_info
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for char_id in uncached_ids:
                url = f"https://esi.evetech.net/latest/characters/{char_id}/"
                tasks.append(self._fetch_char_info(session, char_id, url))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for char_id, result in zip(uncached_ids, results):
                if not isinstance(result, Exception) and result:
                    self.esi_char_cache[char_id] = result
                    char_info[char_id] = result
        
        return char_info

    async def _fetch_char_info(self, session, char_id, url):
        """Helper to fetch individual character info"""
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'corporation_id': data.get('corporation_id'),
                        'alliance_id': data.get('alliance_id')
                    }
        except Exception as e:
            logger.log(f"Error fetching ESI data for char {char_id}: {e}")
        return {}

    async def get_corp_alliance_tickers(self, corp_ids, alliance_ids):
        """Get corporation and alliance tickers from ESI"""
        tickers = {}
        uncached_corp_ids = []
        uncached_alliance_ids = []
        
        # Check cache first
        for corp_id in corp_ids:
            if corp_id and corp_id in self.ticker_cache:
                tickers[corp_id] = self.ticker_cache[corp_id]
            elif corp_id:
                uncached_corp_ids.append(corp_id)
        
        for alliance_id in alliance_ids:
            if alliance_id and alliance_id in self.ticker_cache:
                tickers[alliance_id] = self.ticker_cache[alliance_id]
            elif alliance_id:
                uncached_alliance_ids.append(alliance_id)
        
        if not uncached_corp_ids and not uncached_alliance_ids:
            return tickers
        
        async with aiohttp.ClientSession() as session:
            # Get corp tickers
            corp_tasks = []
            for corp_id in uncached_corp_ids:
                url = f"https://esi.evetech.net/latest/corporations/{corp_id}/"
                corp_tasks.append(self._fetch_corp_info(session, corp_id, url))
            
            # Get alliance tickers
            alliance_tasks = []
            for alliance_id in uncached_alliance_ids:
                url = f"https://esi.evetech.net/latest/alliances/{alliance_id}/"
                alliance_tasks.append(self._fetch_alliance_info(session, alliance_id, url))
            
            if corp_tasks:
                corp_results = await asyncio.gather(*corp_tasks, return_exceptions=True)
                for corp_id, result in zip(uncached_corp_ids, corp_results):
                    if not isinstance(result, Exception) and result:
                        self.ticker_cache[corp_id] = result
                        tickers[corp_id] = result
            
            if alliance_tasks:
                alliance_results = await asyncio.gather(*alliance_tasks, return_exceptions=True)
                for alliance_id, result in zip(uncached_alliance_ids, alliance_results):
                    if not isinstance(result, Exception) and result:
                        self.ticker_cache[alliance_id] = result
                        tickers[alliance_id] = result
        
        return tickers

    async def _fetch_corp_info(self, session, corp_id, url):
        """Helper to fetch corporation info"""
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return {'ticker': data.get('ticker')}
        except Exception as e:
            logger.log(f"Error fetching corp info for {corp_id}: {e}")
        return {}

    async def _fetch_alliance_info(self, session, alliance_id, url):
        """Helper to fetch alliance info"""
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return {'ticker': data.get('ticker')}
        except Exception as e:
            logger.log(f"Error fetching alliance info for {alliance_id}: {e}")
        return {}

    def clear_cache(self):
        self.name_cache = NameIdCache()
        self.zkill_cache = {}
        self.esi_char_cache = {}
        self.ticker_cache = {}
        logger.log("All caches cleared")


def main():
    analyzer = DScanAnalyzer()
    analyzer.monitor_clipboard()


if __name__ == "__main__":
    main()
