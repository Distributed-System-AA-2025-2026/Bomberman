import time
import threading
import os
from common.ServerReference import ServerReference
from hub_server.HubState import HubState

class HubServer:

    hostname: str


    def __init__(self, peers: list[ServerReference]):
        if len(peers) > 0:
            self.state.set_peers(peers)
        self._lock = threading.Lock()  # per thread safety
        self.hostname = os.environ["HOSTNAME"]
        self.state = HubState()


    """
    def start_gossip(self):
        # Avvia il thread gossip.
        thread = threading.Thread(target=self._gossip_loop, daemon=True)
        thread.start()
        """

    """
    def _gossip_loop(self):
        # Gira in background, sincronizza con altri hub.
        while True:
            for peer in self.peers:
                self._sync_with_peer(peer)
            time.sleep(GOSSIP_INTERVAL)
    """

    # Metodi chiamati dall'API
    """
    def create_lobby(self, player_id: str, name: str) -> Lobby:
        with self._lock:
            # modifica stato
            ...

    def find_room(self, lobby_id: str) -> RoomInfo:
        with self._lock:
            # legge stato
            ...
    """