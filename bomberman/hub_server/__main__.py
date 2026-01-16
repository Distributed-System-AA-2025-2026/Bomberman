import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from bomberman.common.hub_rest_api.requests.MatchMakingRequest import MatchmakingRequest
from bomberman.common.hub_rest_api.responses.MatchmakingResponse import MatchmakingResponse
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
    def matchmaking_request(
            request: Request,
            body: MatchmakingRequest = None
    ) -> MatchmakingResponse:
        hub_server = request.app.state.hub_server

        # hub_server fa qualcosa...
        # result = hub_server.find_match()
        # TODO: FARE TEST SULLE API!

        return MatchmakingResponse(
            request_code=200,
            request_message="Wait for implementation... (it will arrive soon) ",
            room_token="",
            room_address="",
            room_port=8000
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

        return {
            "hostname": hub_server.hostname,
            "hub_index": hub_server.hub_index,
            "discovery_mode": hub_server.discovery_mode,
            "fanout": hub_server.fanout,
            "last_nonce": hub_server.last_used_nonce,
            "peers_count": len(peers_info),
            "alive_peers_count": len([p for p in peers_info if p["status"] == "alive"]),
            "peers": peers_info
        }


    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower()
    )
