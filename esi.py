import asyncio
import aiohttp
from loguru import logger


class ESIClient:
    def __init__(self):
        self.name_cache = {}
        
    async def ids_to_names(self, ids):
        """Convert list of IDs to names using ESI"""
        if not ids:
            return {}
            
        ids = [id for id in ids if id and id != 0]
        if not ids:
            return {}
            
        cached_res = {}
        uncached_ids = []
        
        for id in ids:
            cached_name = self.name_cache.get(id)
            if cached_name:
                cached_res[id] = cached_name
            else:
                uncached_ids.append(id)
        
        if not uncached_ids:
            return cached_res
            
        all_res = cached_res.copy()
        chunk_size = 1000
        
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(uncached_ids), chunk_size):
                chunk = uncached_ids[i:i + chunk_size]
                chunk_res = await self._resolve_ids_batch(session, chunk)
                
                for id, name in chunk_res.items():
                    self.name_cache[id] = name
                    
                all_res.update(chunk_res)
        
        return all_res
    
    async def _resolve_ids_batch(self, session, ids):
        if not ids:
            return {}

        url = "https://esi.evetech.net/latest/universe/names/"

        try:
            async with session.post(url, json=ids, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"ESI error: {response.status}")
                    return {}

                data = await response.json()
                return {item['id']: item['name'] for item in data}
        except Exception as e:
            logger.warning(f"Error resolving IDs: {e}")
            return {}

    async def names_to_ids(self, names):
        """Convert list of names to IDs using ESI"""
        if not names:
            return {}
        
        names = [name for name in names if name and name.strip()]
        if not names:
            return {}
        
        cached_res = {}
        uncached_names = []
        
        for name in names:
            cached_id = None
            for id, cached_name in self.name_cache.items():
                if cached_name == name:
                    cached_id = id
                    break
            
            if cached_id:
                cached_res[name] = cached_id
            else:
                uncached_names.append(name)
        
        if not uncached_names:
            return cached_res
        
        all_res = cached_res.copy()
        chunk_size = 500
        
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(uncached_names), chunk_size):
                chunk = uncached_names[i:i + chunk_size]
                chunk_res = await self._resolve_names_batch(session, chunk)
                
                for name, char_id in chunk_res.items():
                    self.name_cache[char_id] = name
                
                all_res.update(chunk_res)
        
        return all_res

    async def _resolve_names_batch(self, session, names):
        if not names:
            return {}

        url = "https://esi.evetech.net/latest/universe/ids/"
        logger.debug(f"Sending {len(names)} names to ESI: {names[:5]}...")

        try:
            async with session.post(url, json=names, timeout=30) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.warning(f"ESI error: {response.status} - {response_text}")
                    return {}

                data = await response.json()
                return {char['name']: char['id'] for char in data.get('characters', [])}
        except Exception as e:
            logger.warning(f"Error resolving names: {e}")
            return {}
