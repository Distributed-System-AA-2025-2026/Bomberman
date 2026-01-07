import os
import time
import random
from typing import Literal
import re

from requests.packages import target

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.hub_server.gossip import messages_pb2 as pb
from hub_server.HubPeer import HubPeer


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
    _hostname: str
    _hub_index: int
    _state: HubState
    _socket_handler: HubSocketHandler
    _discovery_mode: Literal['manual', 'k8s']
    _last_used_nonce: int
    _fanout = 4


    def __init__(self, discovery_mode: Literal['manual', 'k8s'] = "manual"):
        self._state = HubState()
        self._hostname = os.environ["HOSTNAME"]
        self._hub_index = get_hub_index(self._hostname)
        self._discovery_mode = discovery_mode
        self._last_used_nonce = 0
        self._fanout = int(os.environ.get("HUB_FANOUT", self._fanout))

        # Socket handler - solo networking, logica qui
        self._socket_handler = HubSocketHandler(
            port=int(os.environ['GOSSIP_PORT']),
            on_message=self._on_gossip_message
        )
        self._socket_handler.start()

        # Aggiungi me stesso
        self._state.add_peer(HubPeer(
            self._calculate_server_reference(self._hub_index),
            self._hub_index
        ))

        self._discovery_peers()

        print_console(f"Hub server started with index {self._hub_index}", "Info")

    def _on_gossip_message(self, message: pb.GossipMessage, sender: ServerReference):
        # Gestione del forwarding in arrivo - sappiamo che il forwarder è vivo
        self._state.mark_forward_peer_as_alive(message.forwarded_by, sender)

        # Traccia l'origine se diverso dal forwarder
        if message.forwarded_by != message.origin:
            self._ensure_peer_exists(message.origin)

        is_new = self._state.execute_heartbeat_check(message.origin, message.nonce)
        if not is_new:
            return

        # Processa in base al tipo
        self._process_message(message)

        # Forward
        self._forward_message(message)

    def _process_message(self, message: pb.GossipMessage):
        """Handle the specific payload"""
        match message.event_type:
            case pb.PEER_JOIN:
                self._handle_peer_join(message.peer_join)
            case pb.PEER_LEAVE:
                self._handle_peer_leave(message.peer_leave)
            case pb.PEER_SUSPICIOUS:
                self._handle_peer_suspicious(message.peer_suspicious) #TODO
            case pb.PEER_DEAD:
                self._handle_peer_dead(message.peer_dead)  #TODO
            case pb.ROOM_ACTIVATED:
                self._handle_room_activated(message.room_activated)
            case pb.ROOM_STARTED:
                self._handle_room_started(message.room_activated)


    def _handle_peer_join(self, payload: pb.PeerJoinPayload):
        print_console(f"Peer with index {payload.joining_peer} joined", "Gossip")
        self._ensure_peer_exists(payload.joining_peer)

    def _handle_peer_leave(self, payload: pb.PeerLeavePayload):
        print_console(f"Peer with index {payload.leaving_peer} left", "Gossip")
        self._state.remove_peer(payload.leaving_peer)

    def _ensure_peer_exists(self, peer_index: int):
        if self._state.get_peer(peer_index) is None:
            ref = self._calculate_server_reference(peer_index)
            self._state.add_peer(HubPeer(ref, peer_index))

    def _forward_message(self, message: pb.GossipMessage):
        alive_peers: list[HubPeer] = self._state.get_all_not_dead_peers()
        targets: list[HubPeer] = random.sample(alive_peers, min(self._fanout, len(alive_peers)))
        references: list[ServerReference] = list(map(lambda e: e.reference , targets))
        message.forwarded_by = self._hub_index
        self._socket_handler.send_to_many(message, references)

    def _calculate_server_reference(self, peer_index: int) -> ServerReference:
        if self._discovery_mode == "manual":
            return ServerReference('127.0.0.1', 9000 + peer_index)
        else:
            return ServerReference(f"hub-{peer_index}.hub-headless", int(os.environ['GOSSIP_PORT']))

    def _discovery_peers(self): #TODO
        if self._discovery_mode == "manual" and self._hub_index != 0:
            msg = pb.GossipMessage(
                nonce=self._get_next_nonce(),
                origin=self._hub_index,
                forwarded_by=self._hub_index,
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(
                    joining_peer=self._hub_index
                )
            )
            self._send_messages_specific_destination(msg, ServerReference('127.0.0.1', 9000))
        if self._discovery_mode == "k8s":
            pass

    def stop(self):
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.PEER_LEAVE,
            peer_leave=pb.PeerLeavePayload(
                leaving_peer=self._hub_index
            )
        )
        self._send_messages_and_forward(msg)
        self._socket_handler.stop()

    def _send_messages_and_forward(self, message: pb.GossipMessage):
        if message.origin != self._hub_index:
            raise ValueError
        self._state.update_heartbeat(message.origin, message.nonce)
        self._forward_message(message)

    def _send_messages_specific_destination(self, message: pb.GossipMessage, reference: ServerReference):
        if message.origin != self._hub_index:
            raise ValueError
        self._state.update_heartbeat(message.origin, message.nonce)
        self._socket_handler.send(message, reference)

    def _get_next_nonce(self) -> int:
        self._last_used_nonce = self._last_used_nonce + 1
        return self._last_used_nonce