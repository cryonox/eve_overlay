import aiohttp
from abc import ABC, abstractmethod
from typing import Dict
from base_api_client import BaseAPIClient


class StatsInterface(ABC):
    @abstractmethod
    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        pass

    @abstractmethod
    def get_link(self, char_id: int) -> str:
        pass

    @abstractmethod
    def extract_display_stats(self, stats: Dict) -> Dict:
        pass


class ZKillClient(BaseAPIClient):
    @property
    def base_url(self):
        return "https://zkillboard.com/api"

    def _build_url(self, char_id):
        return f"{self.base_url}/stats/characterID/{char_id}/"

    def _handle_response_data(self, data):
        if isinstance(data, dict) and data.get('error') == 'Invalid type or id':
            return {'error': 'not_found'}
        return data


class ZKillStatsProvider(StatsInterface):
    def __init__(self, rate_limit_retry_delay=5):
        from base_api_client import APIClientFactory
        self.client = APIClientFactory.create_client('zkill', rate_limit_retry_delay=rate_limit_retry_delay)

    async def get_stats(self, session: aiohttp.ClientSession, char_id: int) -> Dict:
        return await self.client._get_char_short_stats_with_session(session, char_id)

    def get_link(self, char_id: int) -> str:
        return f"https://zkillboard.com/character/{char_id}/"

    def extract_display_stats(self, stats: Dict) -> Dict:
        if not stats or 'error' in stats:
            return {}
        return {
            'danger': stats.get('dangerRatio', 0),
            'kills': stats.get('shipsDestroyed', 0),
            'losses': stats.get('shipsLost', 0)
        }
