import asyncio
import json
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

_root = Path(__file__).parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger

from services.api.schemas import EventType, PilotUpdate, StreamEvent, DScanResponse
from services.models import PilotState
from services.pilot_service import PilotService
from services.dscan_service import DScanService, get_dscan_info_url


class LookupRequest(BaseModel):
    names: str
    skip_stats: bool = False


class DScanParseRequest(BaseModel):
    data: str
    diff_timeout: float = 60.0


_pilot_svc: Optional[PilotService] = None
_dscan_svc: Optional[DScanService] = None


def get_pilot_svc() -> PilotService:
    global _pilot_svc
    return _pilot_svc


def get_dscan_svc() -> DScanService:
    global _dscan_svc
    return _dscan_svc


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pilot_svc, _dscan_svc
    cfg = app.state.cfg
    _pilot_svc = PilotService(
        cfg.get("cache_dir", "cache"),
        cfg.get("stats_provider", "zkill"),
        cfg.get("rate_limit_delay", 5),
        cfg.get("stats_limit", 50)
    )
    _dscan_svc = DScanService(cfg.get("ships_file", "ships.json"))
    logger.info("Services initialized")
    yield
    logger.info("Shutting down services")


def create_app(cfg: dict = None) -> FastAPI:
    app = FastAPI(title="Eve Overlay API", lifespan=lifespan)
    app.state.cfg = cfg or {}
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    @app.post("/pilots/lookup")
    async def lookup_pilots(req: LookupRequest):
        svc = get_pilot_svc()
        dscan_svc = get_dscan_svc()
        
        if dscan_svc.is_dscan_format(req.names):
            return JSONResponse({"error": "dscan_format_detected", "message": "Use /dscan/parse for dscan data"}, status_code=400)
        
        if not svc.set_pilots(req.names):
            return JSONResponse({"error": "invalid_input"}, status_code=400)
        
        async def stream():
            pilots = svc.get_pilots()
            initial = {n: _pilot_to_dict(p) for n, p in pilots.items()}
            evt = StreamEvent(type=EventType.INITIAL, pilots=initial)
            yield f"data: {json.dumps(evt.to_dict())}\n\n"
            
            prev_states = {n: (p.state, p.stats) for n, p in pilots.items()}
            max_iters = 6000
            
            for _ in range(max_iters):
                await asyncio.sleep(0.05)
                pilots = svc.get_pilots()
                updated = []
                
                for name, pilot in pilots.items():
                    prev_state, prev_stats = prev_states.get(name, (None, None))
                    if pilot.state != prev_state or pilot.stats != prev_stats:
                        updated.append(name)
                        prev_states[name] = (pilot.state, pilot.stats)
                
                if updated:
                    upd_pilots = {n: _pilot_to_dict(pilots[n]) for n in updated}
                    evt = StreamEvent(type=EventType.UPDATE, pilots=upd_pilots, updated=updated)
                    yield f"data: {json.dumps(evt.to_dict())}\n\n"
                
                terminal = (PilotState.FOUND, PilotState.NOT_FOUND, 
                           PilotState.ERROR, PilotState.CACHE_HIT, PilotState.RATE_LIMITED)
                all_done = all(p.state in terminal for p in pilots.values())
                
                if all_done:
                    final = {n: _pilot_to_dict(p) for n, p in pilots.items()}
                    evt = StreamEvent(type=EventType.COMPLETE, pilots=final)
                    yield f"data: {json.dumps(evt.to_dict())}\n\n"
                    return
            
            final = {n: _pilot_to_dict(p) for n, p in pilots.items()}
            evt = StreamEvent(type=EventType.COMPLETE, pilots=final)
            yield f"data: {json.dumps(evt.to_dict())}\n\n"
        
        return StreamingResponse(stream(), media_type="text/event-stream")
    
    @app.get("/pilots")
    async def get_pilots():
        svc = get_pilot_svc()
        pilots = svc.get_pilots()
        return {n: _pilot_to_dict(p) for n, p in pilots.items()}
    
    @app.post("/pilots/reset")
    async def reset_pilots():
        svc = get_pilot_svc()
        svc.reset()
        return {"status": "ok"}
    
    @app.post("/pilots/clear-cache")
    async def clear_cache():
        svc = get_pilot_svc()
        svc.clear_caches()
        return {"status": "ok"}
    
    @app.post("/dscan/parse")
    async def parse_dscan(req: DScanParseRequest):
        svc = get_dscan_svc()
        
        if not svc.is_dscan_format(req.data):
            return JSONResponse({"error": "not_dscan_format"}, status_code=400)
        
        if not svc.is_valid_dscan(req.data):
            return JSONResponse({"error": "invalid_dscan"}, status_code=400)
        
        res = svc.parse(req.data, req.diff_timeout)
        if not res:
            return JSONResponse({"error": "parse_failed"}, status_code=400)
        
        return DScanResponse(
            ship_counts=res.ship_counts,
            total_ships=res.total_ships,
            group_totals=svc.get_group_totals(),
            ship_diffs=svc.get_ship_diffs(),
            group_diffs=svc.get_group_diffs(),
            dscan_url=get_dscan_info_url(req.data)
        )
    
    @app.get("/dscan")
    async def get_dscan():
        svc = get_dscan_svc()
        res = svc.last_result
        if not res:
            return JSONResponse({"error": "no_data"}, status_code=404)
        
        return DScanResponse(
            ship_counts=res.ship_counts,
            total_ships=res.total_ships,
            group_totals=svc.get_group_totals(),
            ship_diffs=svc.get_ship_diffs(),
            group_diffs=svc.get_group_diffs()
        )
    
    @app.post("/dscan/reset")
    async def reset_dscan():
        svc = get_dscan_svc()
        svc.reset()
        return {"status": "ok"}
    
    return app


def _pilot_to_dict(pilot) -> dict:
    d = {
        "name": pilot.name,
        "state": pilot.state.name,
    }
    if pilot.char_id:
        d["char_id"] = pilot.char_id
    if pilot.corp_id:
        d["corp_id"] = pilot.corp_id
    if pilot.alliance_id:
        d["alliance_id"] = pilot.alliance_id
    if pilot.corp_name:
        d["corp_name"] = pilot.corp_name
    if pilot.alliance_name:
        d["alliance_name"] = pilot.alliance_name
    if pilot.stats:
        d["stats"] = pilot.stats
    if pilot.stats_link:
        d["stats_link"] = pilot.stats_link
    if pilot.error_msg:
        d["error_msg"] = pilot.error_msg
    return d


def run_server(host: str = "127.0.0.1", port: int = 8721, cfg: dict = None):
    import uvicorn
    import signal
    
    def handle_signal(signum, frame):
        raise SystemExit(0)
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    app = create_app(cfg)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8721)
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--stats-provider", default="zkill")
    parser.add_argument("--ships-file", default="ships.json")
    args = parser.parse_args()
    
    cfg = {
        "cache_dir": args.cache_dir,
        "stats_provider": args.stats_provider,
        "ships_file": args.ships_file,
    }
    run_server(args.host, args.port, cfg)
