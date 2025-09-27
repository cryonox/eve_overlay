import asyncio
import aiohttp
from logger import logger
from abc import ABC, abstractmethod

class BaseAPIClient(ABC):
    def __init__(self, max_concurrent=50):
        self.user_agent = "Eve Overlay"
        self.cache = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)

    @property
    @abstractmethod
    def base_url(self):
        pass

    @abstractmethod
    def _build_url(self, char_id):
        pass

    @abstractmethod
    def _handle_response_data(self, data):
        pass

    async def get_char_short_stats_batch(self, char_ids, max_concurrent=10):
        if max_concurrent:
            old_semaphore = self.semaphore
            self.semaphore = asyncio.Semaphore(max_concurrent)
        
        try:
            connector = aiohttp.TCPConnector(limit=max_concurrent or 50)
            async with aiohttp.ClientSession(connector=connector) as session:
                tasks = [self._get_char_short_stats_with_session(session, char_id) for char_id in char_ids]
                results = await asyncio.gather(*tasks)
                return dict(zip(char_ids, results))
        finally:
            if max_concurrent:
                self.semaphore = old_semaphore

    async def _get_char_short_stats_with_session(self, session, char_id, max_retries=3):
        if char_id in self.cache:
            return self.cache[char_id]
        
        async with self.semaphore:
            for attempt in range(max_retries + 1):
                try:
                    url = self._build_url(char_id)
                    headers = {'User-Agent': self.user_agent}
                    
                    async with session.get(url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            processed_data = self._handle_response_data(data)
                            if processed_data.get('error') != 'not_found':
                                self.cache[char_id] = processed_data
                            return processed_data
                        elif response.status in [429, 1015]:
                            return {'error': 'rate_limited'}
                        elif response.status == 404:
                            return {'error': 'not_found'}
                        else:
                            return {'error': 'api_error', 'status': response.status}
                except Exception as e:
                    if attempt < max_retries:
                        wait_time = (2 ** attempt) * 2
                        logger.log(f"{self.__class__.__name__} network error for char {char_id}, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.log(f"Error fetching {self.__class__.__name__} data for {char_id}: {e}")
                    return {'error': 'network_error'}
            
            return {'error': 'max_retries_exceeded'}
    
    def clear_cache(self):
        self.cache = {}

class APIClientFactory:
    @staticmethod
    def create_client(client_type, **kwargs):
        if client_type == 'evekill':
            from evekill import EveKillClient
            return EveKillClient(**kwargs)
        elif client_type == 'zkill':
            from zkill import ZKillClient
            return ZKillClient(**kwargs)
        else:
            raise ValueError(f"Unknown client type: {client_type}")
