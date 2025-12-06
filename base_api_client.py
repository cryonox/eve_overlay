import asyncio
import aiohttp
import time
from abc import ABC, abstractmethod
from loguru import logger

class BaseAPIClient(ABC):
    def __init__(self, max_concurrent=50, rate_limit_retry_delay=5):
        self.user_agent = "Eve Overlay"
        self.cache = {}
        self.rate_limit_cache = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limit_retry_delay = rate_limit_retry_delay

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
            logger.debug(f"{self.__class__.__name__} cache hit for char {char_id}")
            return self.cache[char_id]

        if char_id in self.rate_limit_cache:
            expire_time = self.rate_limit_cache[char_id]
            if time.time() < expire_time:
                return {'error': 'rate_limited', 'retry_after': expire_time - time.time()}
            del self.rate_limit_cache[char_id]

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
                            if attempt < max_retries:
                                logger.warning(f"{self.__class__.__name__} rate limited for char {char_id}, retrying in {self.rate_limit_retry_delay}s")
                                await asyncio.sleep(self.rate_limit_retry_delay)
                                continue
                            logger.error(f"{self.__class__.__name__} rate limited for char {char_id}, max retries exceeded")
                            self.rate_limit_cache[char_id] = time.time() + self.rate_limit_retry_delay
                            return {'error': 'rate_limited', 'retry_after': self.rate_limit_retry_delay}
                        elif response.status == 404:
                            try:
                                err_data = await response.json()
                                err_msg = err_data.get('message', 'Not Found')
                            except Exception:
                                err_msg = 'Not Found'
                            logger.error(f"{self.__class__.__name__} 404 for char {char_id}: {err_msg}")
                            return {'error': 'not_found', 'message': err_msg}
                        else:
                            try:
                                err_data = await response.json()
                                err_msg = err_data.get('message', str(err_data))
                            except Exception:
                                err_msg = await response.text()
                            logger.error(f"{self.__class__.__name__} API error for char {char_id}: status {response.status}, msg: {err_msg}")
                            return {'error': 'api_error', 'status': response.status, 'message': err_msg}
                except Exception as e:
                    if attempt < max_retries:
                        wait_time = (2 ** attempt) * 2
                        logger.error(f"{self.__class__.__name__} network error for char {char_id}, retrying in {wait_time}s: {type(e).__name__}: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"{self.__class__.__name__} failed fetching data for {char_id}: {type(e).__name__}: {e}")
                    return {'error': 'network_error', 'message': f"{type(e).__name__}: {e}"}

            logger.error(f"{self.__class__.__name__} max retries exceeded for char {char_id}")
            return {'error': 'max_retries_exceeded'}
    
    def clear_cache(self):
        self.cache = {}
        self.rate_limit_cache = {}

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
