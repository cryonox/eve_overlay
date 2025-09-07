import requests
import pyperclip
import time
from datetime import datetime
from bs4 import BeautifulSoup
import re
from rich import print
import json
import asyncio
import aiohttp
from config import C
import cv2
import numpy as np
import utils
from global_hotkeys import register_hotkeys, start_checking_hotkeys
import webbrowser
from bidict import bidict


async def get_zkill_data_async(session, char_id):
    try:
        stats_url = f"https://zkillboard.com/api/stats/characterID/{char_id}/"
        headers = {'User-Agent': 'DScan Analyzer'}
        async with session.get(stats_url, headers=headers, timeout=10) as response:
            if response.status == 200:
                return await response.json()
    except Exception as e:
        print(f"Error fetching zkill data for {char_id}: {e}")
    return None


class NameIdCache:
    def __init__(self):
        self.data = {}

    def get_id(self, name):
        return next((k for k, v in self.data.items() if v == name and isinstance(k, int)), None)

    def get_name(self, id):
        return self.data.get(id)

    def add_mapping(self, name, id):
        self.data[id] = name
        self.data[name] = id


class DScanAnalyzer:
    def __init__(self):
        self.base_url = "https://dscan.info"
        self.zkill_base = "https://zkillboard.com/api"
        self.ignore_alliances = C.dscan.get('ignore_alliances', [])
        self.ignore_corps = C.dscan.get('ignore_corps', [])
        self.display_duration = C.dscan.get('timeout', 30)
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
        cv2.namedWindow(self.win_name, cv2.WINDOW_AUTOSIZE)
        cv2.setWindowProperty(self.win_name, cv2.WND_PROP_TOPMOST, 1)
        cv2.setMouseCallback(self.win_name, self.mouse_callback)

        if self.transparency_on:
            utils.win_transparent('Main HighGUI class',
                                  self.win_name, self.transparency, (64, 64, 64))

        hotkey_transparency = C.dscan.get('hotkey_transparency', 'alt+shift+f')
        bindings = [
            [hotkey_transparency.split('+'), None, self.toggle_transparency]
        ]
        register_hotkeys(bindings)
        start_checking_hotkeys()

        self.show_status("")

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
            print(f"Error reading clipboard: {e}")
            return None

    def parse_dscan(self, dscan_data):
        try:
            timestamp = int(time.time() * 1000)
            url = f"{self.base_url}/?_={timestamp}"
            payload = {"paste": dscan_data}
            response = requests.post(url, data=payload, timeout=10)

            if response.status_code == 200:
                response_text = response.text.strip()
                if response_text.startswith("OK;"):
                    scan_id = response_text.split(";")[1]
                    return self.fetch_scan_results(scan_id)
                else:
                    return self.parse_html_results(response_text)
            else:
                print(f"HTTP error: {response.status_code}")
                return None
        except Exception as e:
            print(f"Request failed: {e}")
            return None

    def fetch_scan_results(self, scan_id):
        try:
            url = f"{self.base_url}/v/{scan_id}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return self.parse_html_results(response.text)
            else:
                print(f"Failed to fetch scan results: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error fetching scan results: {e}")
            return None

    def parse_character_results(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        character_list = []

        table = soup.find('table', id='characterlist')
        if not table:
            return character_list

        # Find all table rows `<tr>` within the table body `<tbody>`
        rows = table.tbody.find_all('tr')

        for row in rows:
            # Get all columns `<td>` in the row
            cols = row.find_all('td')
            if len(cols) == 3:
                # Extract text, stripping whitespace and button text
                char_name = cols[0].get_text(strip=True)
                corp_name = cols[1].get_text(strip=True)
                alliance_name_raw = cols[2].get_text(strip=True)

                character_data = {
                    'char_name': char_name,
                    'corp_name': corp_name,
                    'alliance_name': None if alliance_name_raw == 'No alliance' else alliance_name_raw
                }
                character_list.append(character_data)

        return character_list

    def parse_character_results(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        character_list = []

        table = soup.find('table', id='characterlist')
        if not table or not table.tbody:
            return character_list

        rows = table.tbody.find_all('tr')

        for row in rows:
            cols = row.find_all('td')
            if len(cols) == 3:
                zkill_tag = cols[0].find(
                    'a', href=re.compile("zkillboard.com"))
                zkill_link = zkill_tag['href'] if zkill_tag else None

                char_name = cols[0].get_text(strip=True)
                corp_name = cols[1].get_text(strip=True)
                alliance_name_raw = cols[2].get_text(strip=True)

                character_data = {
                    'char_name': char_name,
                    'corp_name': corp_name,
                    'alliance_name': None if alliance_name_raw == 'No alliance' else alliance_name_raw,
                    'zkill_link': zkill_link
                }
                character_list.append(character_data)

        return character_list

    def parse_html_results(self, html):
        return self.parse_character_results(html)

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

            return await get_zkill_data_async(session, char_id)
        except Exception as e:
            print(f"Error fetching zkill data for {char_name}: {e}")
        return None

    async def fetch_zkill_data(self, char_data):
        async with aiohttp.ClientSession() as session:
            char_id = self.extract_char_id_from_link(char_data.get(
                'zkill_link')) if char_data.get('zkill_link') else None
            if char_id:
                return await get_zkill_data_async(session, char_id)
            else:
                return await self.get_zkill_stats_async(session, char_data['char_name'])

    def should_ignore_character(self, char_data):
        corp_name = char_data.get('corp_name', '')
        alliance_name = char_data.get('alliance_name', '')
        return (corp_name in self.ignore_corps or
                alliance_name in self.ignore_alliances)

    def create_display_image(self, char_data_list, zkill_results):
        if not char_data_list:
            return None

        self.char_rects = {}
        combined_data = []
        for char_data, zkill_stats in zip(char_data_list, zkill_results):
            danger = zkill_stats.get('dangerRatio', 0) if zkill_stats else 0
            kills = zkill_stats.get('shipsDestroyed', 0) if zkill_stats else 0
            losses = zkill_stats.get('shipsLost', 0) if zkill_stats else 0

            combined_data.append({
                'name': char_data['char_name'],
                'danger': danger,
                'kills': kills,
                'losses': losses,
                'zkill_link': char_data.get('zkill_link')
            })

        combined_data.sort(key=lambda x: x['danger'], reverse=True)

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
            text = f"{name} | D:{data['danger']:.1f} K:{data['kills']} L:{data['losses']}"

            text_w, text_h = utils.get_text_size_withnewline(
                text, (10, y), font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

            self.char_rects[data['name']] = (
                (10, y, text_w, text_h), data['zkill_link'])

            color = (255, 255, 255) if data['danger'] == 0 else (
                0, 0, 255) if data['danger'] >= 80 else (0, 255, 255)

            y = utils.draw_text_withnewline(
                im, text, (10, y), color=color, bg_color=self.bg_color, font_scale=C.dscan.font_scale, font_thickness=C.dscan.font_thickness)

        return im

    async def print_results_async(self, data):
        if not data:
            self.show_status("")
            return

        filtered_data = [
            char_data for char_data in data if not self.should_ignore_character(char_data)]

        if not filtered_data:
            self.show_status("")
            return

        self.result_start_time = time.time()

        tasks = [self.fetch_zkill_data(char_data)
                 for char_data in filtered_data]
        zkill_results = await asyncio.gather(*tasks)

        self.last_parsed_data = filtered_data
        self.last_zkill_results = zkill_results

        im = self.create_display_image(filtered_data, zkill_results)
        if im is not None:
            self.last_result_im = im
            self.last_im = im
            cv2.imshow(self.win_name, im)
            cv2.waitKey(1)
            self.handle_transparency()

    def print_results(self, data):
        asyncio.run(self.print_results_async(data))

    def extract_char_id_from_link(self, zkill_link):
        if not zkill_link:
            return None
        match = re.search(r'/character/(\d+)/', zkill_link)
        return int(match.group(1)) if match else None

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
                    result = self.parse_dscan(current_clipboard)
                    self.print_results(result)
                    self.last_result_total_time = utils.tock()
                    last_clipboard = current_clipboard

                if self.result_start_time and time.time() - self.result_start_time >= self.display_duration:
                    self.show_status("")
                    self.result_start_time = None
                    self.last_result_im = None

                if self.result_start_time and hasattr(self, 'last_parsed_data') and hasattr(self, 'last_zkill_results'):
                    im = self.create_display_image(
                        self.last_parsed_data, self.last_zkill_results)
                    if im is not None:
                        cv2.imshow(self.win_name, im)

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
                    print(f"Failed to resolve names batch: {response.status}")
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
            print(f"Error resolving names via ESI after {elapsed:.2f}s: {e}")
            return []
        finally:
            elapsed = time.time() - start_time
            print(f"Total ESI resolution time: {elapsed:.2f}s")

    async def _resolve_ids_batch_esi(self, corp_ids, alliance_ids):
        """Internal function to resolve <=1000 corp/alliance IDs to names using ESI"""
        names_url = "https://esi.evetech.net/latest/universe/names/"

        all_ids = list(corp_ids) + list(alliance_ids)
        if not all_ids:
            return {}

        async with aiohttp.ClientSession() as session:
            async with session.post(names_url, json=all_ids) as response:
                if response.status != 200:
                    print(f"Failed to resolve IDs batch: {response.status}")
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

            if not uncached_ids:
                return cached_results

            all_results = cached_results.copy()
            chunk_size = 1000

            for i in range(0, len(uncached_ids), chunk_size):
                chunk = uncached_ids[i:i + chunk_size]
                chunk_corp_ids = [id for id in chunk if id in corp_ids]
                chunk_alliance_ids = [id for id in chunk if id in alliance_ids]

                chunk_results = await self._resolve_ids_batch_esi(chunk_corp_ids, chunk_alliance_ids)

                for id, name in chunk_results.items():
                    self.name_cache.add_mapping(name, id)

                all_results.update(chunk_results)

            return all_results

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"Error resolving IDs via ESI after {elapsed:.2f}s: {e}")
            return {}
        finally:
            elapsed = time.time() - start_time
            print(f"Total ESI ID resolution time: {elapsed:.2f}s")


def main():
    analyzer = DScanAnalyzer()
    analyzer.monitor_clipboard()


def test():
    async def run_analysis(analyzer, names, run_name):
        print(f"=== {run_name} ===")
        utils.tick()

        result = await analyzer.resolve_names_to_ids_esi(names)

        connector = aiohttp.TCPConnector(limit=200)
        async with aiohttp.ClientSession(connector=connector) as session:
            zkill_tasks = [get_zkill_data_async(
                session, char['char_id']) for char in result]
            zkill_results = await asyncio.gather(*zkill_tasks)

        corp_ids = []
        alliance_ids = []
        for char, zkill_data in zip(result, zkill_results):
            if zkill_data and zkill_data.get('info'):
                corp_id = zkill_data['info'].get('corporationID')
                alliance_id = zkill_data['info'].get('allianceID')
                if corp_id:
                    corp_ids.append(corp_id)
                if alliance_id:
                    alliance_ids.append(alliance_id)

        id_to_name = await analyzer.ids_to_names_esi(corp_ids, alliance_ids)

        char_data_list = []
        for char, zkill_data in zip(result, zkill_results):
            corp_id = zkill_data.get('info', {}).get(
                'corporationID') if zkill_data else None
            alliance_id = zkill_data.get('info', {}).get(
                'allianceID') if zkill_data else None

            char_info = {
                'char_name': char['char_name'],
                'corp_name': id_to_name.get(corp_id, 'Unknown') if corp_id else 'Unknown',
                'alliance_name': id_to_name.get(alliance_id) if alliance_id else None,
                'zkill_link': f"https://zkillboard.com/character/{char['char_id']}/"
            }
            char_data_list.append(char_info)

        filtered_data = [
            char_data for char_data in char_data_list if not analyzer.should_ignore_character(char_data)]
        total_time = utils.tock(f'{run_name} done')

        return filtered_data, zkill_results, total_time

    async def test_esi():
        analyzer = DScanAnalyzer()
        names = pyperclip.paste().splitlines()

        filtered_data, zkill_results, total_time = await run_analysis(analyzer, names, "First run")
        await run_analysis(analyzer, names, "Second run (testing cache)")

        # if filtered_data:
        #    analyzer.result_start_time = time.time()
        #    analyzer.last_result_total_time = total_time
        #    im = analyzer.create_display_image(filtered_data, zkill_results)
        #    if im is not None:
        #        analyzer.last_result_im = im
        #        analyzer.last_im = im
        #        cv2.imshow(analyzer.win_name, im)
        #        cv2.waitKey(2000)

    asyncio.run(test_esi())


if __name__ == "__main__":
    main()
    # test()
