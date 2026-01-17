import json
import time
import socket
import threading
import atexit
from multiprocessing import Process
from typing import Optional, Dict, Callable
from dataclasses import dataclass

import requests
from loguru import logger

from .schemas import EventType
from .server import run_server
from services.models import PilotState, PilotData


DEFAULT_PORT = 8721
HEALTH_TIMEOUT = 10
HEALTH_INTERVAL = 0.1


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    cache_dir: str = "cache"
    stats_provider: str = "zkill"
    ships_file: str = "ships.json"
    rate_limit_delay: int = 5
    stats_limit: int = 50
    
    @classmethod
    def from_config(cls, cfg) -> "ServerConfig":
        api_cfg = cfg.get("api", {})
        dscan_cfg = cfg.get("dscan", {})
        return cls(
            host=api_cfg.get("host", "127.0.0.1"),
            port=api_cfg.get("port", DEFAULT_PORT),
            cache_dir=cfg.get("cache", "cache"),
            stats_provider=dscan_cfg.get("stats_provider", "zkill"),
            ships_file=cfg.get("ships_file", "ships.json"),
            rate_limit_delay=dscan_cfg.get("rate_limit_retry_delay", 5),
            stats_limit=dscan_cfg.get("aggregated_mode_threshold", 50),
        )


class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
    
    def health(self) -> bool:
        try:
            resp = self._session.get(f"{self.base_url}/health", timeout=2)
            return resp.status_code == 200
        except:
            return False
    
    def lookup_pilots_stream(self, names: str, on_event: Callable[[dict], None]):
        resp = self._session.post(
            f"{self.base_url}/pilots/lookup",
            json={"names": names},
            stream=True,
            timeout=(10, None)
        )
        resp.raise_for_status()
        
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data = json.loads(line[6:])
                on_event(data)
                if data.get("type") == EventType.COMPLETE.value:
                    break
    
    def get_pilots(self) -> Dict[str, dict]:
        resp = self._session.get(f"{self.base_url}/pilots", timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def reset_pilots(self):
        resp = self._session.post(f"{self.base_url}/pilots/reset", timeout=5)
        resp.raise_for_status()
    
    def clear_cache(self):
        resp = self._session.post(f"{self.base_url}/pilots/clear-cache", timeout=5)
        resp.raise_for_status()
    
    def parse_dscan(self, data: str, diff_timeout: float = 60.0) -> Optional[dict]:
        resp = self._session.post(
            f"{self.base_url}/dscan/parse",
            json={"data": data, "diff_timeout": diff_timeout},
            timeout=15
        )
        if resp.status_code == 400:
            return None
        resp.raise_for_status()
        return resp.json()
    
    def get_dscan(self) -> Optional[dict]:
        resp = self._session.get(f"{self.base_url}/dscan", timeout=5)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    
    def reset_dscan(self):
        resp = self._session.post(f"{self.base_url}/dscan/reset", timeout=5)
        resp.raise_for_status()


class ServerManager:
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._proc: Optional[Process] = None
        self._lock = threading.Lock()
        atexit.register(self.stop)
    
    @property
    def base_url(self) -> str:
        return f"http://{self.cfg.host}:{self.cfg.port}"
    
    def is_port_available(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((self.cfg.host, self.cfg.port)) != 0
    
    def find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]
    
    def start(self, auto_port: bool = False) -> bool:
        with self._lock:
            if self._proc and self._proc.is_alive():
                return True
            
            if not self.is_port_available():
                if auto_port:
                    self.cfg.port = self.find_free_port()
                    logger.info(f"Using auto-assigned port {self.cfg.port}")
                else:
                    logger.warning(f"Port {self.cfg.port} in use")
                    return False
            
            cfg = {
                "cache_dir": self.cfg.cache_dir,
                "stats_provider": self.cfg.stats_provider,
                "ships_file": self.cfg.ships_file,
            }
            
            logger.info(f"Starting API server on {self.base_url}")
            self._proc = Process(
                target=run_server,
                args=(self.cfg.host, self.cfg.port, cfg),
                daemon=True
            )
            self._proc.start()
            
            return self._wait_for_health()
    
    def _wait_for_health(self) -> bool:
        client = APIClient(self.base_url)
        start = time.time()
        
        while time.time() - start < HEALTH_TIMEOUT:
            if not self._proc.is_alive():
                logger.error("Server process died")
                return False
            
            if client.health():
                logger.info("API server ready")
                return True
            
            time.sleep(HEALTH_INTERVAL)
        
        logger.error("Server health check timeout")
        self.stop()
        return False
    
    def stop(self):
        with self._lock:
            if self._proc and self._proc.is_alive():
                logger.info("Stopping API server")
                self._proc.terminate()
                self._proc.join(timeout=5)
                if self._proc.is_alive():
                    self._proc.kill()
            self._proc = None
    
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.is_alive()


class PilotAPIClient:
    def __init__(self, cfg: ServerConfig = None, auto_start: bool = True):
        self.cfg = cfg or ServerConfig()
        self._mgr: Optional[ServerManager] = None
        self._client: Optional[APIClient] = None
        self._pilots: Dict[str, PilotData] = {}
        self._stream_thread: Optional[threading.Thread] = None
        self._auto_start = auto_start
        self.stats_limit = self.cfg.stats_limit
    
    def _ensure_server(self) -> bool:
        if self._client and self._client.health():
            return True
        
        if not self._auto_start:
            return False
        
        if not self._mgr:
            self._mgr = ServerManager(self.cfg)
        
        if not self._mgr.start(auto_port=True):
            return False
        
        self._client = APIClient(self._mgr.base_url)
        return True
    
    def set_pilots(self, clipboard_data: str) -> bool:
        if not self._ensure_server():
            return False
        
        self._pilots = {}
        
        def on_event(evt: dict):
            evt_type = evt.get("type")
            pilots_data = evt.get("pilots", {})
            
            for name, pdata in pilots_data.items():
                self._pilots[name] = _dict_to_pilot(pdata)
        
        try:
            self._stream_thread = threading.Thread(
                target=self._client.lookup_pilots_stream,
                args=(clipboard_data, on_event),
                daemon=True
            )
            self._stream_thread.start()
            
            time.sleep(0.05)
            return len(self._pilots) > 0 or self._stream_thread.is_alive()
        except requests.HTTPError:
            return False
    
    def get_pilots(self) -> Dict[str, PilotData]:
        def sort_key(item):
            p = item[1]
            kills = p.stats.get("kills", -1) if p.stats else -1
            return -kills
        return dict(sorted(self._pilots.items(), key=sort_key))
    
    def reset(self):
        self._pilots = {}
        if self._client:
            try:
                self._client.reset_pilots()
            except:
                pass
    
    def clear_caches(self):
        if self._client:
            try:
                self._client.clear_cache()
            except:
                pass
    
    def shutdown(self):
        if self._mgr:
            self._mgr.stop()


def _dict_to_pilot(d: dict) -> PilotData:
    state_name = d.get("state", "SEARCHING_ESI")
    state = PilotState[state_name] if state_name in PilotState.__members__ else PilotState.SEARCHING_ESI
    
    return PilotData(
        name=d.get("name", ""),
        state=state,
        char_id=d.get("char_id"),
        corp_id=d.get("corp_id"),
        alliance_id=d.get("alliance_id"),
        corp_name=d.get("corp_name"),
        alliance_name=d.get("alliance_name"),
        stats=d.get("stats"),
        stats_link=d.get("stats_link"),
        error_msg=d.get("error_msg"),
    )
