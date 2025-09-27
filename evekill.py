
import asyncio
import aiohttp
import logger

class EveKillClient:
    def __init__(self, max_concurrent=50):
        self.base_url = "https://eve-kill.com/api"
        self.user_agent = "Eve Overlay"
        self.cache = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    async def get_char_short_stats(self, char_id, max_retries=3):
        """Get character short stats from eve-kill API"""
        if char_id in self.cache:
            return self.cache[char_id]
            
        async with self.semaphore:
            for attempt in range(max_retries + 1):
                try:
                    url = f"{self.base_url}/characters/{char_id}/short-stats/"
                    headers = {'User-Agent': self.user_agent}
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers, timeout=10) as response:
                            if response.status == 200:
                                data = await response.json()
                                self.cache[char_id] = data
                                return data
                            elif response.status == 429:
                                return {'error': 'rate_limited'}
                            elif response.status == 404:
                                return {'error': 'not_found'}
                            else:
                                return {'error': 'api_error', 'status': response.status}
                except Exception as e:
                    if attempt < max_retries:
                        wait_time = (2 ** attempt) * 2
                        logger.log(f"EveKill network error for char {char_id}, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.log(f"Error fetching eve-kill data for {char_id}: {e}")
                    return {'error': 'network_error'}
            
            return {'error': 'max_retries_exceeded'}
    
    async def get_char_short_stats_batch(self, char_ids, max_concurrent=10):
        """Get short stats for multiple characters with controlled concurrency"""
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
        """Internal method using provided session"""
        if char_id in self.cache:
            return self.cache[char_id]
            
        async with self.semaphore:
            for attempt in range(max_retries + 1):
                try:
                    url = f"{self.base_url}/characters/{char_id}/short-stats/"
                    headers = {'User-Agent': self.user_agent}
                    
                    async with session.get(url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            self.cache[char_id] = data
                            return data
                        elif response.status == 429:
                            return {'error': 'rate_limited'}
                        elif response.status == 404:
                            return {'error': 'not_found'}
                        else:
                            return {'error': 'api_error', 'status': response.status}
                except Exception as e:
                    if attempt < max_retries:
                        wait_time = (2 ** attempt) * 2
                        logger.log(f"EveKill network error for char {char_id}, retrying in {wait_time}s: {e}")
                        await asyncio.sleep(wait_time)
                        continue
                    logger.log(f"Error fetching eve-kill data for {char_id}: {e}")
                    return {'error': 'network_error'}
            
            return {'error': 'max_retries_exceeded'}
    
    def clear_cache(self):
        """Clear the internal cache"""
        self.cache = {}
