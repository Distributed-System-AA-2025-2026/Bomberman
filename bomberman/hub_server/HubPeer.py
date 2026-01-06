from typing import Literal
import time

from common.ServerReference import ServerReference

class HubPeer:
    _reference: ServerReference
    _index: int
    _status: Literal['alive', 'suspected', 'dead']
    _heartbeat: int
    _last_seen: float

    def __init__(self, reference: ServerReference, index: int):
        self._reference = reference
        self._index = index
        self._status = 'alive'
        self._heartbeat = 0
        self._last_seen = time.time()

    @property
    def index(self) -> int:
        return self._index

    @property
    def reference(self) -> ServerReference:
        return self._reference

    @reference.setter
    def reference(self, value: ServerReference):
        self._reference = value

    @property
    def status(self) -> Literal['alive', 'suspected', 'dead']:
        return self._status

    @status.setter
    def status(self, value: Literal['alive', 'suspected', 'dead']):
        self._status = value

    @property
    def heartbeat(self) -> int:
        return self._heartbeat

    @heartbeat.setter
    def heartbeat(self, value: int):
        self._heartbeat = value

    @property
    def last_seen(self) -> float:
        return self._last_seen

    @last_seen.setter
    def last_seen(self, value: float):
        self._last_seen = value