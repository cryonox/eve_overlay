import asyncio
import threading
import aiohttp
from typing import Dict, List, Optional
from loguru import logger

from .models import PilotData, PilotState, get_invalid_pilot_name_reason
from cache import CacheManager
from esi import ESIResolver
from zkill import ZKillStatsProvider, calc_danger
from evekill import EveKillStatsProvider
from cache_stats import CacheStatsProvider


class PilotService:
    def __init__(self, cache_dir: str = 'cache', stats_provider: str = 'zkill',
                 rate_limit_delay: int = 5, stats_limit: int = 50):
        self.cache = CacheManager(cache_dir)
        self.cache.load_cache()
        self.esi = ESIResolver()
        self.stats_limit = stats_limit

        providers = {
            'zkill': lambda: ZKillStatsProvider(rate_limit_delay),
            'evekill': lambda: EveKillStatsProvider(rate_limit_delay),
            'cache': CacheStatsProvider
        }
        self.stats_provider = providers.get(
            stats_provider, providers['zkill'])()

        self._pilots: Dict[str, PilotData] = {}
        self._network_thread: Optional[threading.Thread] = None

    def clear_caches(self):
        self.stats_provider.client.clear_cache()
        self.esi = ESIResolver()
        logger.info("Caches cleared")

    def set_pilots(self, clipboard_data: str) -> bool:
        names = self._parse_pilot_list(clipboard_data)
        if not names:
            return False
        self._pilots = self._lookup_from_cache(names)
        skip_stats = len(names) > self.stats_limit
        self._fetch_missing_data(skip_stats)
        return True

    def get_pilots(self) -> Dict[str, PilotData]:
        def sort_key(item):
            p = item[1]
            kills = p.stats.get('kills', -1) if p.stats else -1
            return -kills
        return dict(sorted(self._pilots.items(), key=sort_key))

    def reset(self):
        self._pilots = {}

    def _parse_pilot_list(self, clipboard_data: str) -> Optional[List[str]]:
        lines = [line.strip()
                 for line in clipboard_data.strip().split('\n') if line.strip()]
        if not lines:
            return None
        for line in lines:
            reason = get_invalid_pilot_name_reason(line)
            if reason:
                logger.debug(f"Invalid pilot list: '{line[:30]}' - {reason}")
                return None
        return lines

    def _lookup_from_cache(self, names: List[str]) -> Dict[str, PilotData]:
        pilots = {}
        stats_cache = self.stats_provider.client.cache

        for name in names:
            info = self.cache.get_char_info(name)
            if info:
                pilot = PilotData(
                    name=name, state=PilotState.CACHE_HIT, char_id=info['char_id'])
                if not self._apply_esi_cache(pilot):
                    pilot.corp_id = info['corp_id']
                    pilot.alliance_id = info['alliance_id']
                    pilot.corp_name = info['corp_name']
                    pilot.alliance_name = info['alliance_name']
                pilot.stats_link = self.stats_provider.get_link(pilot.char_id)
                self._apply_stats_from_cache(pilot, name, stats_cache)
            elif name in self.esi.name_cache:
                char_id = self.esi.name_cache[name]
                pilot = PilotData(name=name, char_id=char_id,
                                  state=PilotState.SEARCHING_STATS)
                pilot.stats_link = self.stats_provider.get_link(char_id)
                self._apply_esi_cache(pilot)
                self._apply_stats_from_cache(pilot, name, stats_cache)
            else:
                pilot = PilotData(name=name, state=PilotState.SEARCHING_ESI)
            pilots[name] = pilot
        return pilots

    def _apply_esi_cache(self, pilot: PilotData) -> bool:
        if pilot.char_id not in self.esi.char_cache:
            return False
        char_info = self.esi.char_cache[pilot.char_id]
        pilot.corp_id = char_info.get('corporation_id')
        pilot.alliance_id = char_info.get('alliance_id')
        pilot.corp_name = self.esi.id_name_cache.get(
            pilot.corp_id, 'Unknown') if pilot.corp_id else None
        pilot.alliance_name = self.esi.id_name_cache.get(
            pilot.alliance_id) if pilot.alliance_id else None
        pilot.corp_alliance_resolved = True
        return True

    def _apply_stats_from_cache(self, pilot: PilotData, name: str, stats_cache: dict) -> bool:
        if pilot.char_id in stats_cache:
            stats = stats_cache[pilot.char_id]
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
                return True
        preloaded = self.cache.get_char_stats(name)
        if preloaded:
            k, l = preloaded['kills'], preloaded['losses']
            pilot.stats = {'kills': k, 'losses': l,
                           'danger': calc_danger(k, l)}
            pilot.state = PilotState.CACHE_HIT
            return True
        return False

    def _fetch_missing_data(self, skip_stats: bool = False):
        pilots_esi = [p for p in self._pilots.values() if p.state == PilotState.SEARCHING_ESI]
        pilots_stats = [p for p in self._pilots.values()
                        if p.state in [PilotState.CACHE_HIT, PilotState.SEARCHING_STATS]]
        pilots_corp = [p for p in self._pilots.values()
                       if p.corp_id and not p.corp_alliance_resolved]

        if skip_stats:
            for p in pilots_stats:
                p.state = PilotState.FOUND

        if pilots_esi or pilots_corp or (not skip_stats and pilots_stats):
            self._start_network_fetch(
                pilots_esi, pilots_stats, skip_stats, pilots_corp)

    def _start_network_fetch(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData],
                             skip_stats: bool, pilots_corp: List[PilotData] = None):
        def run_fetch():
            asyncio.run(self._fetch_network_data(
                pilots_esi, pilots_stats, skip_stats, pilots_corp or []))

        self._network_thread = threading.Thread(target=run_fetch, daemon=True)
        self._network_thread.start()

    async def _fetch_network_data(self, pilots_esi: List[PilotData], pilots_stats: List[PilotData],
                                  skip_stats: bool, pilots_corp: List[PilotData]):
        connector = aiohttp.TCPConnector(limit=50)
        async with aiohttp.ClientSession(connector=connector) as session:
            if pilots_esi:
                tasks = [self._lookup_pilot_async(p, session, skip_stats) for p in pilots_esi]
                await asyncio.gather(*tasks, return_exceptions=True)

            if pilots_corp:
                tasks = [self._resolve_corp_alliance_async(p, session) for p in pilots_corp
                         if not p.corp_alliance_resolved]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            if not skip_stats and pilots_stats:
                for p in pilots_stats:
                    p.state = PilotState.SEARCHING_STATS
                tasks = [self._fetch_stats_async(p, session) for p in pilots_stats]
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _lookup_pilot_async(self, pilot: PilotData, session: aiohttp.ClientSession,
                                  skip_stats: bool = False):
        try:
            if pilot.char_id is None:
                name_map = await self.esi.resolve_names_to_ids(session, [pilot.name])
                if pilot.name not in name_map:
                    pilot.state = PilotState.NOT_FOUND
                    return
                pilot.char_id = name_map[pilot.name]

            if pilot.corp_id is None:
                char_info = await self.esi.get_char_info(session, pilot.char_id)
                pilot.corp_id = char_info.get('corporation_id')
                pilot.alliance_id = char_info.get('alliance_id')

                ids = [i for i in [pilot.corp_id, pilot.alliance_id] if i]
                if ids:
                    names = await self.esi.resolve_ids_to_names(session, ids)
                    pilot.corp_name = names.get(pilot.corp_id, 'Unknown')
                    pilot.alliance_name = names.get(pilot.alliance_id) if pilot.alliance_id else None
                pilot.corp_alliance_resolved = True

            pilot.stats_link = self.stats_provider.get_link(pilot.char_id)

            if skip_stats:
                pilot.state = PilotState.FOUND
                return

            pilot.state = PilotState.SEARCHING_STATS
            await self._fetch_stats_async(pilot, session)

        except Exception as e:
            logger.info(f"Error looking up pilot {pilot.name}: {e}")
            pilot.state = PilotState.ERROR
            pilot.error_msg = str(e)

    async def _fetch_stats_async(self, pilot: PilotData, session: aiohttp.ClientSession):
        try:
            stats = await self.stats_provider.get_stats(session, pilot.char_id)
            if stats and 'error' not in stats:
                pilot.stats = self.stats_provider.extract_display_stats(stats)
                pilot.state = PilotState.FOUND
            elif stats and stats.get('error') == 'not_found':
                pilot.state = PilotState.NOT_FOUND
            elif stats and stats.get('error') == 'rate_limited':
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.RATE_LIMITED
                pilot.error_msg = f"Retry in {int(stats.get('retry_after', 0))}s"
            else:
                pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.ERROR
                pilot.error_msg = stats.get('error', 'unknown') if stats else 'unknown'
        except Exception as e:
            pilot.state = PilotState.CACHE_HIT if pilot.stats else PilotState.ERROR
            pilot.error_msg = str(e)

    async def _resolve_corp_alliance_async(self, pilot: PilotData, session: aiohttp.ClientSession):
        if pilot.corp_alliance_resolved:
            return
        try:
            char_info = await self.esi.get_char_info(session, pilot.char_id)
            new_corp_id = char_info.get('corporation_id')
            new_alliance_id = char_info.get('alliance_id')

            ids = [i for i in [new_corp_id, new_alliance_id] if i]
            if ids:
                names = await self.esi.resolve_ids_to_names(session, ids)
                pilot.corp_id = new_corp_id
                pilot.alliance_id = new_alliance_id
                pilot.corp_name = names.get(new_corp_id, 'Unknown')
                pilot.alliance_name = names.get(new_alliance_id) if new_alliance_id else None

            pilot.corp_alliance_resolved = True
        except Exception as e:
            logger.info(f"Error resolving corp/alliance for {pilot.name}: {e}")
