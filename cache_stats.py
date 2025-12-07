import aiohttp
from typing import Dict
from zkill import StatsInterface, calc_danger


class DummyClient:
    def __init__(self):
        self.cache = {}
    
    def clear_cache(self):
        self.cache.clear()


class CacheStatsProvider(StatsInterface):
    def __init__(self):
        self.client = DummyClient()

    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        return {'error': 'cache_only'}

    def get_link(self, char_id: int) -> str:
        return f"https://zkillboard.com/character/{char_id}/"

    def extract_display_stats(self, stats: Dict) -> Dict:
        if not stats or 'error' in stats:
            return {}
        kills, losses = stats.get('kills', 0), stats.get('losses', 0)
        return {'danger': calc_danger(kills, losses), 'kills': kills, 'losses': losses}

