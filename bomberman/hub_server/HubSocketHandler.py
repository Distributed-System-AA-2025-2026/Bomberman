# hub_server/HubSocketHandler.py
import socket
import threading
import json
from typing import Callable

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.hub_server.gossip.messages_pb2 import GossipMessage
from bomberman.hub_server.HubPeer import HubPeer

BUFFER_SIZE = 65535  # max UDP datagram size

# Type alias per il callback
MessageHandler = Callable[[pb.GossipMessage, ServerReference], None]
CalculateServerReferences = Callable[[int], ServerReference]


class HubSocketHandler:
    _socket: socket.socket
    _port: int
    _on_message: MessageHandler
    _calculate_references: CalculateServerReferences
    _running: bool
    _listener_thread: threading.Thread
    _hub_state: HubState

    def __init__(self, port: int, on_message: MessageHandler, calculate_references: CalculateServerReferences, hub_state: HubState):
        self._on_message = on_message
        self._calculate_references = calculate_references
        self._running = False
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("0.0.0.0", port))
        self._hub_state = hub_state

    def start(self):
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop(self):
        self._running = False
        self._socket.close()

    def _listen_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(BUFFER_SIZE)
                # Spawn un thread per gestire il messaggio
                handler_thread = threading.Thread(
                    target=self._handle_message,
                    args=(data, addr),
                    daemon=True
                )
                handler_thread.start()
            except OSError:
                break

    def _handle_message(self, data: bytes, addr: tuple[str, int]):
        """Gestisce un singolo messaggio (in thread separato)"""
        try:
            message = pb.GossipMessage()
            message.ParseFromString(data)
            server_reference = ServerReference(addr[0], addr[1])
            self._hub_state.mark_forward_peer_as_alive(message.forwarded_by, server_reference)
            if message.forwarded_by != message.origin:
                self.handle_origin_peer(message.origin)
            is_new_message = self._hub_state.execute_heartbeat_check(message.origin, message.nonce)
            if is_new_message:
                self._on_message(message, server_reference)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[HubSocketHandler] Invalid message from {addr}: {e}")

    def handle_origin_peer(self, origin_peer_index: int):
        origin_peer = self._hub_state.get_peer(origin_peer_index)
        if origin_peer is None:
            origin_peer = HubPeer(self._calculate_references(origin_peer_index), origin_peer_index)
            self._hub_state.add_peer(origin_peer)

    def send(self, message: GossipMessage, addr: ServerReference):
        """Invia un messaggio a un peer"""
        data: bytes = message.SerializeToString()
        dest = (addr.address, addr.port)
        self._socket.sendto(data, dest)

    def send_to_many(self, message: GossipMessage, addrs: list[ServerReference]):
        """Invia un messaggio a più peer"""
        data = message.to_bytes()
        for addr in addrs:
            dest = (addr.address, addr.port)
            self._socket.sendto(data, dest)