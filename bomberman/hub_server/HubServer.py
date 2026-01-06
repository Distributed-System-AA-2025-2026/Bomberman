import threading
import os
import time
from typing import Literal
import re

from common.ServerReference import ServerReference
from hub_server.HubPeer import HubPeer
from hub_server.HubState import HubState
from hub_server.HubSocketHandler import HubSocketHandler
from hub_server.gossip import messages_pb2 as pb


def get_hub_index(hostname: str) -> int:
    if hostname.strip() != hostname:
        raise ValueError(f"Invalid hub hostname: {hostname}")

    match = re.match(r"hub-(\d+)(?:\.|$)", hostname)
    if not match:
        raise ValueError(f"Invalid hub hostname: {hostname}")
    string_index = match.group(1)
    output = int(string_index)
    del string_index
    return output

def print_console(message: str, category: Literal['Error', 'Gossip', 'Info'] = 'Gossip'):
    print(f"[HubServer][{category}]: {message}")

class HubServer:
    _lock: threading.Lock
    _hostname: str
    _hub_index: int
    _state: HubState
    _socket_handler: HubSocketHandler

    def __init__(self, discovery_mode: Literal['manual', 'k8s'] = "manual"):
        self._state = HubState()
        self._lock = threading.Lock()
        self._hostname = os.environ["HOSTNAME"]
        self._peers = []
        self._socket_handler = HubSocketHandler(int(os.environ['GOSSIP_PORT']), self._on_gossip_message, self._state)

        try:
            self._hub_index = get_hub_index(self._hostname)
        except ValueError:
            print_console("Unable to retrieve hub index", "Error")

        self._socket_handler.start()
        self.discovery_peers(discovery_mode)
        print_console(f"Hub server started with index {self._hub_index}", "Info")

    def discovery_peers(self, discovery_mode: Literal['manual', 'k8s'] = "manual"):
        if discovery_mode == "manual" and self._hub_index != 0:
            msg = pb.GossipMessage(
                nonce=1,
                origin=self._hub_index,
                forwarded_by=self._hub_index,
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(
                    joining_peer=self._hub_index
                )
            )
            self._socket_handler.send(msg, ServerReference('127.0.0.1', 9000))
        if discovery_mode == "k8s":
            pass




    def _on_gossip_message(self, message: pb.GossipMessage, sender_address: ServerReference):
        pass #TODO: Handle messages here




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