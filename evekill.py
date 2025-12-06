import asyncio
import aiohttp
from loguru import logger
import json
import time
from pathlib import Path
from typing import Dict
from base_api_client import BaseAPIClient
from tqdm import tqdm
from zkill import StatsInterface


class EveKillClient(BaseAPIClient):
    @property
    def base_url(self):
        return "https://eve-kill.com/api"

    def _build_url(self, char_id):
        return f"{self.base_url}/stats/character_id/{char_id}?dataType=basic&days=0"

    def _handle_response_data(self, data):
        return data

    async def get_ek_stats(self):
        export_url = f"{self.base_url}/export"
        headers = {'User-Agent': self.user_agent}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(export_url, headers=headers, timeout=30) as response:
                    if response.status != 200:
                        logger.info(f"Failed to get export info: {response.status}")
                        return None
                    
                    collections = await response.json()
                    stats_collection = next((c for c in collections if c['collection'] == 'stats'), None)
                    
                    if stats_collection:
                        total_count = stats_collection.get('estimatedCount', 0)
                        logger.info(f"Total stats available for export: {total_count:,}")
                        return stats_collection
                    else:
                        logger.info("Stats collection not found in export info")
                        return None
                    
            except Exception as e:
                logger.info(f"Error getting export info: {e}")
                return None

    async def export_ek_stats(self, batch_location='test_data/ek_batches_stats/', batch_size=100000, dst_json=None):
        stats_info = await self.get_ek_stats()
        if not stats_info:
            return []
        
        estimated_count = stats_info.get('estimatedCount', 0)
        batch_dir = Path(batch_location)
        batch_dir.mkdir(parents=True, exist_ok=True)
        
        export_url = f"{self.base_url}/export/stats"
        headers = {'User-Agent': self.user_agent}
        
        # Find existing batches to resume from
        existing_batches = sorted(batch_dir.glob("batch_*.json"))
        batch_cnt = len(existing_batches)
        downloaded_count = 0
        
        # Calculate after_id from last batch
        after_id = None
        if existing_batches:
            with open(existing_batches[-1], 'r') as f:
                last_batch = json.load(f)
                if last_batch:
                    after_id = last_batch[-1].get('_id')
                    downloaded_count = batch_cnt * batch_size
    
        print(existing_batches) 
        cur_batch_data = []
        
        with tqdm(total=estimated_count, initial=downloaded_count, desc="Downloading EK stats") as pbar:
            async with aiohttp.ClientSession() as session:
                while True:
                    params = {'limit': 10000}
                    if after_id:
                        params['after'] = after_id
                    
                    try:
                        async with session.get(export_url, headers=headers, params=params, timeout=60) as response:
                            if response.status != 200:
                                logger.info(f"Export API error: {response.status}")
                                break
                        
                            response_data = await response.json()
                            batch_data = response_data.get('data', [])
                            
                            if not batch_data:
                                break
                            
                            cur_batch_data.extend(batch_data)
                            pbar.update(len(batch_data))
                            
                            after_id = batch_data[-1].get('_id')
                            
                            if len(cur_batch_data) >= batch_size:
                                batch_file = batch_dir / f"batch_{batch_cnt:04d}.json"
                                with open(batch_file, 'w', encoding='utf-8') as f:
                                    json.dump(cur_batch_data, f, indent=2, ensure_ascii=False)
                                
                                batch_cnt += 1
                                cur_batch_data = []
                            
                            await asyncio.sleep(0.1)
                    
                    except Exception as e:
                        logger.info(f"Error downloading: {e}")
                        break
        
        if cur_batch_data:
            batch_file = batch_dir / f"batch_{batch_cnt:04d}.json"
            with open(batch_file, 'w', encoding='utf-8') as f:
                json.dump(cur_batch_data, f, indent=2, ensure_ascii=False)
        return

    async def get_ek_characters(self):
        export_url = f"{self.base_url}/export"
        headers = {'User-Agent': self.user_agent}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(export_url, headers=headers, timeout=30) as response:
                    if response.status != 200:
                        logger.info(f"Failed to get export info: {response.status}")
                        return None
                    
                    collections = await response.json()
                    chars_collection = next((c for c in collections if c['collection'] == 'characters'), None)
                    
                    if chars_collection:
                        total_count = chars_collection.get('estimatedCount', 0)
                        logger.info(f"Total characters available for export: {total_count:,}")
                        return chars_collection
                    else:
                        logger.info("Characters collection not found in export info")
                        return None
                    
            except Exception as e:
                logger.info(f"Error getting export info: {e}")
                return None

    async def export_ek_characters(self, batch_location='test_data/ek_batches_chars/', batch_size=100000, dst_json=None):
        chars_info = await self.get_ek_characters()
        if not chars_info:
            return []
        
        estimated_count = chars_info.get('estimatedCount', 0)
        batch_dir = Path(batch_location)
        batch_dir.mkdir(parents=True, exist_ok=True)
        
        export_url = f"{self.base_url}/export/characters"
        headers = {'User-Agent': self.user_agent}
        
        existing_batches = sorted(batch_dir.glob("batch_*.json"))
        batch_cnt = len(existing_batches)
        downloaded_count = 0
        
        after_id = None
        if existing_batches:
            with open(existing_batches[-1], 'r') as f:
                last_batch = json.load(f)
                if last_batch:
                    after_id = last_batch[-1].get('_id')
                    downloaded_count = batch_cnt * batch_size

        cur_batch_data = []
        
        with tqdm(total=estimated_count, initial=downloaded_count, desc="Downloading EK characters") as pbar:
            async with aiohttp.ClientSession() as session:
                while True:
                    params = {'limit': 10000}
                    if after_id:
                        params['after'] = after_id
                    
                    try:
                        async with session.get(export_url, headers=headers, params=params, timeout=60) as response:
                            if response.status != 200:
                                logger.info(f"Export API error: {response.status}")
                                break
                    
                            response_data = await response.json()
                            batch_data = response_data.get('data', [])
                            
                            if not batch_data:
                                break
                            
                            cur_batch_data.extend(batch_data)
                            pbar.update(len(batch_data))
                            
                            after_id = batch_data[-1].get('_id')
                            
                            if len(cur_batch_data) >= batch_size:
                                batch_file = batch_dir / f"batch_{batch_cnt:04d}.json"
                                with open(batch_file, 'w', encoding='utf-8') as f:
                                    json.dump(cur_batch_data, f, indent=2, ensure_ascii=False)
                                
                                batch_cnt += 1
                                cur_batch_data = []
                            
                            await asyncio.sleep(0.1)
                
                    except Exception as e:
                        logger.info(f"Error downloading: {e}")
                        break
    
        if cur_batch_data:
            batch_file = batch_dir / f"batch_{batch_cnt:04d}.json"
            with open(batch_file, 'w', encoding='utf-8') as f:
                json.dump(cur_batch_data, f, indent=2, ensure_ascii=False)
        return


class EveKillStatsProvider(StatsInterface):
    def __init__(self, rate_limit_retry_delay=5):
        from base_api_client import APIClientFactory
        self.client = APIClientFactory.create_client('evekill', rate_limit_retry_delay=rate_limit_retry_delay)

    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        return await self.client._get_char_short_stats_with_session(session, char_id)

    def get_link(self, char_id: int) -> str:
        return f"https://eve-kill.com/character/{char_id}"

    def extract_display_stats(self, stats: Dict) -> Dict:
        if not stats or 'error' in stats:
            return {}
        return {
            'danger': stats.get('dangerRatio', 0),
            'kills': stats.get('kills', 0),
            'losses': stats.get('losses', 0)
        }
