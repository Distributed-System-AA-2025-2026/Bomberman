from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EventType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PEER_JOIN: _ClassVar[EventType]
    PEER_LEAVE: _ClassVar[EventType]
    PEER_ALIVE: _ClassVar[EventType]
    PEER_SUSPICIOUS: _ClassVar[EventType]
    PEER_DEAD: _ClassVar[EventType]
    ROOM_ACTIVATED: _ClassVar[EventType]
    ROOM_STARTED: _ClassVar[EventType]
PEER_JOIN: EventType
PEER_LEAVE: EventType
PEER_ALIVE: EventType
PEER_SUSPICIOUS: EventType
PEER_DEAD: EventType
ROOM_ACTIVATED: EventType
ROOM_STARTED: EventType

class GossipMessage(_message.Message):
    __slots__ = ("nonce", "origin", "forwarded_by", "timestamp", "event_type", "peer_join", "peer_leave", "peer_alive", "peer_suspicious", "peer_dead", "room_activated", "room_closed")
    NONCE_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    FORWARDED_BY_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    PEER_JOIN_FIELD_NUMBER: _ClassVar[int]
    PEER_LEAVE_FIELD_NUMBER: _ClassVar[int]
    PEER_ALIVE_FIELD_NUMBER: _ClassVar[int]
    PEER_SUSPICIOUS_FIELD_NUMBER: _ClassVar[int]
    PEER_DEAD_FIELD_NUMBER: _ClassVar[int]
    ROOM_ACTIVATED_FIELD_NUMBER: _ClassVar[int]
    ROOM_CLOSED_FIELD_NUMBER: _ClassVar[int]
    nonce: int
    origin: int
    forwarded_by: int
    timestamp: float
    event_type: EventType
    peer_join: PeerJoinPayload
    peer_leave: PeerLeavePayload
    peer_alive: PeerAlivePayload
    peer_suspicious: PeerSuspiciousPayload
    peer_dead: PeerDeadPayload
    room_activated: RoomActivatedPayload
    room_closed: RoomClosedPayload
    def __init__(self, nonce: _Optional[int] = ..., origin: _Optional[int] = ..., forwarded_by: _Optional[int] = ..., timestamp: _Optional[float] = ..., event_type: _Optional[_Union[EventType, str]] = ..., peer_join: _Optional[_Union[PeerJoinPayload, _Mapping]] = ..., peer_leave: _Optional[_Union[PeerLeavePayload, _Mapping]] = ..., peer_alive: _Optional[_Union[PeerAlivePayload, _Mapping]] = ..., peer_suspicious: _Optional[_Union[PeerSuspiciousPayload, _Mapping]] = ..., peer_dead: _Optional[_Union[PeerDeadPayload, _Mapping]] = ..., room_activated: _Optional[_Union[RoomActivatedPayload, _Mapping]] = ..., room_closed: _Optional[_Union[RoomClosedPayload, _Mapping]] = ...) -> None: ...

class PeerJoinPayload(_message.Message):
    __slots__ = ("joining_peer",)
    JOINING_PEER_FIELD_NUMBER: _ClassVar[int]
    joining_peer: int
    def __init__(self, joining_peer: _Optional[int] = ...) -> None: ...

class PeerLeavePayload(_message.Message):
    __slots__ = ("leaving_peer",)
    LEAVING_PEER_FIELD_NUMBER: _ClassVar[int]
    leaving_peer: int
    def __init__(self, leaving_peer: _Optional[int] = ...) -> None: ...

class PeerAlivePayload(_message.Message):
    __slots__ = ("alive_peer",)
    ALIVE_PEER_FIELD_NUMBER: _ClassVar[int]
    alive_peer: int
    def __init__(self, alive_peer: _Optional[int] = ...) -> None: ...

class PeerSuspiciousPayload(_message.Message):
    __slots__ = ("suspicious_peer",)
    SUSPICIOUS_PEER_FIELD_NUMBER: _ClassVar[int]
    suspicious_peer: int
    def __init__(self, suspicious_peer: _Optional[int] = ...) -> None: ...

class PeerDeadPayload(_message.Message):
    __slots__ = ("dead_peer",)
    DEAD_PEER_FIELD_NUMBER: _ClassVar[int]
    dead_peer: int
    def __init__(self, dead_peer: _Optional[int] = ...) -> None: ...

class RoomActivatedPayload(_message.Message):
    __slots__ = ("room_id",)
    ROOM_ID_FIELD_NUMBER: _ClassVar[int]
    room_id: int
    def __init__(self, room_id: _Optional[int] = ...) -> None: ...

class RoomClosedPayload(_message.Message):
    __slots__ = ("room_id",)
    ROOM_ID_FIELD_NUMBER: _ClassVar[int]
    room_id: int
    def __init__(self, room_id: _Optional[int] = ...) -> None: ...
