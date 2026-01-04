from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from common.hub_rest_api.requests.MatchMakingRequest import MatchmakingRequest
from common.hub_rest_api.responses.MatchmakingResponse import MatchmakingResponse
from hub_server.HubServer import HubServer

hub_server = HubServer([])

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: creazione dell'istanza
    app.state.hub_server = hub_server
    print("[HubServer] started...")

    yield

    # Shutdown phase
    print("[HubServer] shutting down...")


app = FastAPI(lifespan=lifespan)


@app.get("/")
def read_root(request: Request):
    return {"content": "Go away."}


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
        request_code = 200,
        request_message = "Wait for implementation... (it will arrive soon) ",
        room_token="", #TODO: IMPLEMENT
        room_address="", #TODO: IMPLEMENT
        room_port=8000 #TODO: IMPLEMENT
    )


@app.get("/debug/")
def debug_request(request: Request):
    hub_server = request.app.state.hub_server
    return {"content": str(hub_server)}


