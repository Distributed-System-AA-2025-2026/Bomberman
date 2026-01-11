from pydantic import BaseModel

class MatchmakingResponse(BaseModel):
    request_code: int
    request_message: str
    room_token: str
    room_address: str
    room_port: int