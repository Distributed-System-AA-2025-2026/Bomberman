import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException

from bomberman.common.hub_rest_api.responses.MatchmakingResponse import MatchmakingResponse
from bomberman.common.hub_rest_api.responses.DefaultResponse import DefaultResponse
from bomberman.hub_server.HubServer import HubServer
import os



if __name__ == '__main__':

    discovery_mode = os.environ.get("HUB_DISCOVERY_MODE", "manual")


    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: creazione dell'istanza
        hub_server = HubServer(discovery_mode)
        app.state.hub_server = hub_server

        yield

        # Shutdown phase
        hub_server.stop()
        del hub_server


    app = FastAPI(lifespan=lifespan)


    @app.get("/")
    def get_root(request: Request):
        return {"content": "Go away."}


    @app.get("/health")
    def health_check():
        return {"status": "healthy"}


    @app.get("/ready")
    def readiness_check(request: Request):
        hub_server = request.app.state.hub_server
        # Verifica che hub_server sia inizializzato
        if hub_server is None:
            return Response(status_code=503, content="Not ready")
        return {"status": "ready"}


    @app.post("/matchmaking", response_model=MatchmakingResponse)
    def matchmaking(request: Request) -> MatchmakingResponse:
        hub_server: HubServer = request.app.state.hub_server

        room = hub_server.get_or_activate_room()

        if room is None:
            raise HTTPException(status_code=503, detail="No available rooms")

        return MatchmakingResponse(
            request_code=200,
            request_message="Room assigned",
            room_address=hub_server.room_manager.get_room_address(room),
            room_port=room.external_port,
            room_id=room.room_id
        )


    @app.post("/room/{room_id}/start")
    def room_started(room_id: str, request: Request):
        hub_server = request.app.state.hub_server
        hub_server.broadcast_room_started(room_id)
        return DefaultResponse(
            response_code=200,
            response_message="Ok."
        )


    @app.post("/room/{room_id}/close")
    def room_closed(room_id: str, request: Request):
        hub_server = request.app.state.hub_server
        hub_server.broadcast_room_closed(room_id)
        return DefaultResponse(
            response_code=200,
            response_message="Ok."
        )


    @app.get("/debug/")
    def debug_request(request: Request):
        hub_server: HubServer = request.app.state.hub_server

        peers_info = []
        for peer in hub_server.get_all_peers():
            peers_info.append({
                "index": peer.index,
                "status": peer.status,
                "heartbeat": peer.heartbeat,
                "last_seen": peer.last_seen,
                "address": peer.reference.address,
                "port": peer.reference.port
            })

        rooms_info = []
        for room in hub_server.get_all_rooms():
            rooms_info.append({
                "room_id": room.room_id,
                "owner_hub_index": room.owner_hub_index,
                "status": room.status.value,
                "external_port": room.external_port,
                "is_local": room.owner_hub_index == hub_server.hub_index,
                "is_joinable": room.is_joinable
            })

        # Group rooms by status for quick overview
        active_rooms = [r for r in rooms_info if r["status"] == "active"]

        return {
            "hostname": hub_server.hostname,
            "hub_index": hub_server.hub_index,
            "discovery_mode": hub_server.discovery_mode,
            "fanout": hub_server.fanout,
            "last_nonce": hub_server.last_used_nonce,
            "peers_count": len(peers_info),
            "alive_peers_count": len([p for p in peers_info if p["status"] == "alive"]),
            "peers": peers_info,
            "rooms_count": len(rooms_info),
            "active_rooms_count": len(active_rooms),
            "rooms": rooms_info
        }


    port = int(os.environ.get("HTTP_PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower()
    )
