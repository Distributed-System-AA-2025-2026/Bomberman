from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Packet(_message.Message):
    __slots__ = ("join_request", "server_response", "client_action", "state_snapshot")
    JOIN_REQUEST_FIELD_NUMBER: _ClassVar[int]
    SERVER_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ACTION_FIELD_NUMBER: _ClassVar[int]
    STATE_SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    join_request: JoinRequest
    server_response: ServerResponse
    client_action: GameAction
    state_snapshot: GameStateSnapshot
    def __init__(self, join_request: _Optional[_Union[JoinRequest, _Mapping]] = ..., server_response: _Optional[_Union[ServerResponse, _Mapping]] = ..., client_action: _Optional[_Union[GameAction, _Mapping]] = ..., state_snapshot: _Optional[_Union[GameStateSnapshot, _Mapping]] = ...) -> None: ...

class JoinRequest(_message.Message):
    __slots__ = ("player_id",)
    PLAYER_ID_FIELD_NUMBER: _ClassVar[int]
    player_id: str
    def __init__(self, player_id: _Optional[str] = ...) -> None: ...

class ServerResponse(_message.Message):
    __slots__ = ("success", "message", "error", "tick_rate")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    TICK_RATE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    error: str
    tick_rate: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., error: _Optional[str] = ..., tick_rate: _Optional[int] = ...) -> None: ...

class GameAction(_message.Message):
    __slots__ = ("action_type", "player_id")
    class ActionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STAY: _ClassVar[GameAction.ActionType]
        MOVE_UP: _ClassVar[GameAction.ActionType]
        MOVE_DOWN: _ClassVar[GameAction.ActionType]
        MOVE_LEFT: _ClassVar[GameAction.ActionType]
        MOVE_RIGHT: _ClassVar[GameAction.ActionType]
        PLACE_BOMB: _ClassVar[GameAction.ActionType]
        QUIT: _ClassVar[GameAction.ActionType]
    STAY: GameAction.ActionType
    MOVE_UP: GameAction.ActionType
    MOVE_DOWN: GameAction.ActionType
    MOVE_LEFT: GameAction.ActionType
    MOVE_RIGHT: GameAction.ActionType
    PLACE_BOMB: GameAction.ActionType
    QUIT: GameAction.ActionType
    ACTION_TYPE_FIELD_NUMBER: _ClassVar[int]
    PLAYER_ID_FIELD_NUMBER: _ClassVar[int]
    action_type: GameAction.ActionType
    player_id: str
    def __init__(self, action_type: _Optional[_Union[GameAction.ActionType, str]] = ..., player_id: _Optional[str] = ...) -> None: ...

class GameStateSnapshot(_message.Message):
    __slots__ = ("ascii_grid", "is_game_over")
    ASCII_GRID_FIELD_NUMBER: _ClassVar[int]
    IS_GAME_OVER_FIELD_NUMBER: _ClassVar[int]
    ascii_grid: str
    is_game_over: bool
    def __init__(self, ascii_grid: _Optional[str] = ..., is_game_over: bool = ...) -> None: ...
