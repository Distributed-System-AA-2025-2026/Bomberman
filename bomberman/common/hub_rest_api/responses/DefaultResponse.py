from pydantic import BaseModel

class DefaultResponse(BaseModel):
    response_code: int
    response_message: str