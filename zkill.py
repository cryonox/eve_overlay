
import asyncio
import aiohttp
import logger
from base_api_client import BaseAPIClient

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
