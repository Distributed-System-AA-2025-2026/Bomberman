import threading
import time
import os
from typing import Callable

from bomberman.hub_server.HubState import HubState


class PeerDiscoveryMonitor:
    """
    Monitors the number of alive peers and triggers discovery
    when there are fewer than FANOUT peers available.
    """

    CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', '60'))

    _state: HubState
    _my_index: int
    _fanout: int
    _running: bool
    _thread: threading.Thread
    _on_insufficient_peers: Callable[[], None]

    def __init__(
            self,
            state: HubState,
            my_index: int,
            fanout: int,
            on_insufficient_peers: Callable[[], None]
    ):
        self._state = state
        self._my_index = my_index
        self._fanout = fanout
        self._running = False
        self._on_insufficient_peers = on_insufficient_peers

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        self._check_peer_count()

        while self._running:
            time.sleep(self.CHECK_INTERVAL)
            self._check_peer_count()

    def _check_peer_count(self):
        alive_peers = self._state.get_all_not_dead_peers(exclude_peers=self._my_index)

        if len(alive_peers) < self._fanout:
            self._on_insufficient_peers()