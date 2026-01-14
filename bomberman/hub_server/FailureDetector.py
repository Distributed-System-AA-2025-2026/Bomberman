import threading
import time
import os

from typing import Callable

from bomberman.hub_server.HubState import HubState

class FailureDetector:
    SUSPECT_TIMEOUT = os.environ.get('FAILURE_DETECTOR_SUSPECT_TIMEOUT', 5.0)
    DEAD_TIMEOUT = os.environ.get('FAILURE_DETECTOR_DEAD_TIMEOUT', 20.0)
    CHECK_INTERVAL = os.environ.get('FAILURE_DETECTOR_CHECK_INTERVAL', 1.0)

    _state: HubState
    _my_index: int
    _running: bool
    _thread: threading.Thread
    _on_peer_suspected: Callable[[int], None]
    _on_peer_dead: Callable[[int], None]

    def __init__(self, state: HubState, my_index: int, on_peer_suspected: Callable[[int], None], on_peer_dead: Callable[[int], None]
    ):
        self._state = state
        self._my_index = my_index
        self._running = False
        self._on_peer_suspected = on_peer_suspected
        self._on_peer_dead = on_peer_dead

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(self.CHECK_INTERVAL)
            self._check_peers()

    def _check_peers(self):
        now = time.time()
        peers = self._state.get_all_peers(exclude=[self._my_index])

        for peer in peers:
            silence = now - peer.last_seen

            if silence > self.DEAD_TIMEOUT and peer.status != 'dead':
                self._state.set_peer_status(peer.index, 'dead')
                self._on_peer_dead(peer.index)

            elif silence > self.SUSPECT_TIMEOUT and peer.status == 'alive':
                self._state.set_peer_status(peer.index, 'suspected')
                self._on_peer_suspected(peer.index)