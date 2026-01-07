from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from common.hub_rest_api.requests.MatchMakingRequest import MatchmakingRequest
from common.hub_rest_api.responses.MatchmakingResponse import MatchmakingResponse
from hub_server.HubServer import HubServer
import os

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


@app.post("/matchmaking", response_model=MatchmakingResponse)
def matchmaking_request(
        request: Request,
        body: MatchmakingRequest = None
) -> MatchmakingResponse:
    hub_server = request.app._state.hub_server

    # hub_server fa qualcosa...
    # result = hub_server.find_match()
    # TODO: FARE TEST SULLE API!

    return MatchmakingResponse(
        request_code = 200,
        request_message = "Wait for implementation... (it will arrive soon) ",
        room_token="", #TODO: IMPLEMENT
        room_address="", #TODO: IMPLEMENT
        room_port=8000 #TODO: IMPLEMENT
    )


@app.get("/debug/")
def debug_request(request: Request):
    hub_server = request.app._state.hub_server
    return {"content": str(hub_server)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(f"{__name__}:app", host=host, port=port, reload=True)

