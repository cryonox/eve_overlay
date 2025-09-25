
import asyncio
import aiohttp
import json

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
        """Resolve batch of IDs to names"""
        if not ids:
            return {}
            
        url = "https://esi.evetech.net/latest/universe/names/"
        
        try:
            async with session.post(url, json=ids, timeout=30) as response:
                if response.status != 200:
                    print(f"ESI error: {response.status}")
                    return {}
                    
                data = await response.json()
                return {item['id']: item['name'] for item in data}
        except Exception as e:
            print(f"Error resolving IDs: {e}")
            return {}
