import os
import time
import random
from typing import Literal
import re
from datetime import datetime

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.hub_server.gossip import messages_pb2 as pb
from hub_server.FailureDetector import FailureDetector
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

def print_console(message: str, category: Literal['Error', 'Gossip', 'Info', 'FailureDetector'] = 'Gossip'):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}][HubServer][{category}]: {message}")

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

        self._failure_detector = FailureDetector(
            state=self._state,
            my_index=self._hub_index,
            on_peer_suspected=self._on_peer_suspicious,
            on_peer_dead=self._on_peer_dead
        )
        self._failure_detector.start()


        print_console(f"Hub server started with index {self._hub_index}", "Info")

    def _on_gossip_message(self, message: pb.GossipMessage, sender: ServerReference):
        # Traccia l'origine se diverso dal forwarder
        self._ensure_peer_exists(message.forwarded_by)
        if message.forwarded_by != message.origin:
            self._ensure_peer_exists(message.origin)

        is_new = self._state.execute_heartbeat_check(message.origin, message.nonce, message.event_type == pb.PEER_LEAVE)
        self._state.mark_forward_peer_as_alive(message.forwarded_by, sender) #Marking forwarder as alive
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
            case pb.PEER_ALIVE:
                self._handle_peer_alive(message.peer_alive)
            case pb.PEER_SUSPICIOUS:
                self._handle_peer_suspicious(message.peer_suspicious)
            case pb.PEER_DEAD:
                self._handle_peer_dead(message.peer_dead)
            case pb.ROOM_ACTIVATED:
                self._handle_room_activated(message.room_activated)
            case pb.ROOM_STARTED:
                self._handle_room_started(message.room_closed)


    def _handle_peer_join(self, payload: pb.PeerJoinPayload):
        print_console(f"Peer with index {payload.joining_peer} joined", "Gossip")
        self._ensure_peer_exists(payload.joining_peer)

    def _handle_peer_leave(self, payload: pb.PeerLeavePayload):
        print_console(f"Peer with index {payload.leaving_peer} left", "Gossip")
        self._state.remove_peer(payload.leaving_peer)

    def _handle_peer_alive(self, payload: pb.PeerAlivePayload):
        print_console(f"Peer {payload.alive_peer} declares ALIVE", "Gossip")
        self._state.mark_peer_explicitly_alive(payload.alive_peer)

    def _handle_peer_suspicious(self, payload: pb.PeerSuspiciousPayload):
        #If I'm suspicious, then I'll declare that i'm alive, else I can ignore the message, because I'll discover that a peer is suspicious by myself
        if payload.suspicious_peer == self._hub_index:
            print_console("Someone think that I'm suspicious. Let's declare that I'm alive!", "Gossip")
            self._broadcast_peer_alive()

    def _handle_peer_dead(self, payload: pb.PeerDeadPayload):
        print_console(f"Peer {payload.dead_peer} declared dead", "Gossip")
        dead_peer_memory = self._state.get_peer(required_peer=payload.dead_peer)
        if dead_peer_memory is not None and dead_peer_memory.status == 'suspected':
            self._state.remove_peer(payload.dead_peer)

    def _handle_room_activated(self, payload: pb.RoomActivatedPayload):
        pass #TODO

    def _handle_room_started(self, payload: pb.RoomClosedPayload):
        pass #TODO


    def _ensure_peer_exists(self, peer_index: int):
        if self._state.get_peer(peer_index) is None:
            ref = self._calculate_server_reference(peer_index)
            self._state.add_peer(HubPeer(ref, peer_index))

    def _forward_message(self, message: pb.GossipMessage):
        alive_peers: list[HubPeer] = self._state.get_all_not_dead_peers(self._hub_index)
        # alive_peers: list[HubPeer] = self._state.get_all_not_dead_peers()
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

    def _on_peer_suspicious(self, suspicious_peer: int) -> None:
        print_console(f"Peer {suspicious_peer} is suspicious.", 'FailureDetector')
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.PEER_SUSPICIOUS,
            peer_suspicious=pb.PeerSuspiciousPayload(
                suspicious_peer=suspicious_peer
            )
        )
        self._send_messages_and_forward(msg)

    def _on_peer_dead(self, dead_peer: int) -> None:
        print_console(f"Peer {dead_peer} is dead.", 'FailureDetector')
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.PEER_DEAD,
            peer_dead=pb.PeerDeadPayload(dead_peer=dead_peer)
        )
        self._send_messages_and_forward(msg)
        self._state.remove_peer(dead_peer)

    def _broadcast_peer_alive(self):
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.PEER_ALIVE,
            peer_alive=pb.PeerAlivePayload(
                alive_peer=self._hub_index
            )
        )
        self._send_messages_and_forward(msg)