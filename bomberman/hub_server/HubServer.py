import os
import time
import random
from typing import Literal
import re
from bomberman.hub_server.hublogging import print_console

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.hub_server.FailureDetector import FailureDetector
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.hub_server.PeerDiscoveryMonitor import PeerDiscoveryMonitor
from bomberman.hub_server.room_manager import create_room_manager
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.RoomHealthMonitor import RoomHealthMonitor


def get_hub_index(hostname: str) -> int:
    if hostname.strip() != hostname:
        raise ValueError(f"Invalid hub hostname: {hostname}")

    match = re.match(r"hub-(\d+)(?:\.|$)", hostname)
    if not match:
        print(f"GIVEN INVALID HOSTNAME: {hostname}")
        raise ValueError(f"Invalid hub hostname: {hostname}")
    string_index = match.group(1)
    output = int(string_index)
    del string_index
    return output


class HubServer:
    _hostname: str
    _hub_index: int
    _state: HubState
    _socket_handler: HubSocketHandler
    _discovery_mode: Literal['manual', 'k8s']
    _last_used_nonce: int
    _fanout = 4
    _peer_discovery_monitor: PeerDiscoveryMonitor

    def __init__(self, discovery_mode: Literal['manual', 'k8s'] = "manual"):
        self._state = HubState()
        self._hostname = os.environ.get("HOSTNAME", 'hub-0.local')
        self._hub_index = get_hub_index(self._hostname)
        self._discovery_mode = discovery_mode
        self._last_used_nonce = 0
        self._fanout = int(os.environ.get("HUB_FANOUT", self._fanout))

        if self._fanout <= 0:
            raise ValueError(f"Invalid fanout value: {self._fanout}")

        # Socket handler - solo networking, logica qui
        self._socket_handler = HubSocketHandler(
            port=int(os.environ['GOSSIP_PORT']),
            on_message=self._on_gossip_message,
            logging=print_console
        )
        self._socket_handler.start()

        # Aggiungi me stesso
        self._state.add_peer(HubPeer(
            self._calculate_server_reference(self._hub_index),
            self._hub_index
        ))

        self._failure_detector = FailureDetector(
            state=self._state,
            my_index=self._hub_index,
            on_peer_suspected=self._on_peer_suspicious,
            on_peer_dead=self._on_peer_dead
        )
        self._failure_detector.start()

        self._peer_discovery_monitor = PeerDiscoveryMonitor(
            state=self._state,
            my_index=self._hub_index,
            fanout=self._fanout,
            on_insufficient_peers=self._discovery_peers
        )
        self._peer_discovery_monitor.start()

        self._room_manager = create_room_manager(
            discovery_mode=discovery_mode,
            hub_index=self._hub_index,
            on_room_activated=self._broadcast_room_activated
        )
        self._room_manager.initialize_pool()

        self._room_health_monitor = RoomHealthMonitor(
            state=self._state,
            my_index=self._hub_index,
            on_room_unhealthy=self._on_room_unhealthy
        )
        self._room_health_monitor.start()

        print_console(f"Hub server started with index {self._hub_index}", "Info")
        print_console(f"Hub server started with hostname {self._hostname}", "Info")
        print_console(f"Hub server started with discovery mode {self._discovery_mode}", "Info")

    def _on_room_unhealthy(self, room: Room) -> None:
        if room.owner_hub_index == self._hub_index:
            print_console(
                f"Local room {room.room_id} marked as PLAYING (health check failed)",
                "RoomHealthMonitor"
            )
            self._state.set_room_status(room.room_id, RoomStatus.PLAYING)

            # Broadcast agli altri hub
            self.broadcast_room_started(room.room_id)
        else:
            print_console(
                f"Remote room {room.room_id} removed from state (health check failed)",
                "RoomHealthMonitor"
            )
            self._state.remove_room(room.room_id)

    def _on_gossip_message(self, message: pb.GossipMessage, sender: ServerReference):
        sender = self._resolve_server_reference(sender, message.forwarded_by)
        # Traccia l'origine se diverso dal forwarder
        self._ensure_peer_exists(message.forwarded_by)
        if message.forwarded_by != message.origin:
            self._ensure_peer_exists(message.origin)

        is_new = self._state.execute_heartbeat_check(message.origin, message.nonce, message.event_type == pb.PEER_LEAVE)
        self._state.mark_forward_peer_as_alive(message.forwarded_by, sender)  # Marking forwarder as alive
        if not is_new:
            return

        # Processa in base al tipo
        self._process_message(message)

        # Forward
        self._forward_message(message)

    def _resolve_server_reference(self, reference: ServerReference, peer_index: int) -> ServerReference:
        if self._discovery_mode == "k8s":
            return self._calculate_server_reference(peer_index)
        return reference

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
                self._handle_room_started(message.room_started)
            case pb.ROOM_CLOSED:
                self._handle_room_closed(message.room_closed)
            case pb.ROOM_PLAYER_JOINED:
                self._handle_room_player_joined(message.room_player_joined)

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
        # If I'm suspicious, then I'll declare that i'm alive, else I can ignore the message, because I'll discover that a peer is suspicious by myself
        if payload.suspicious_peer == self._hub_index:
            print_console("Someone think that I'm suspicious. Let's declare that I'm alive!", "Gossip")
            self._broadcast_peer_alive()

    def _handle_peer_dead(self, payload: pb.PeerDeadPayload):
        """
        Is called when a peer tell us that another one is dead.
        """
        print_console(f"Peer {payload.dead_peer} declared dead", "Gossip")
        dead_peer_memory = self._state.get_peer(required_peer=payload.dead_peer)
        if dead_peer_memory is not None and dead_peer_memory.status == 'suspected':
            self._state.remove_peer(payload.dead_peer)

    def _handle_room_activated(self, payload: pb.RoomActivatedPayload):
        print_console(f"Room {payload.room_id} activated by hub {payload.owner_hub}", "Gossip")

        # Aggiungi al mio state (room remota)
        room = Room(
            room_id=payload.room_id,
            owner_hub_index=payload.owner_hub,
            status=RoomStatus.ACTIVE,
            external_port=payload.external_port,
            internal_service=""  # Non mi serve, è remota
        )
        self._state.add_room(room)

    def _handle_room_started(self, payload: pb.RoomStartedPayload):
        """Room ha iniziato la partita, non più joinable"""
        print_console(f"Room {payload.room_id} started playing", "Gossip")
        self._state.set_room_status(payload.room_id, RoomStatus.PLAYING)

    def _handle_room_closed(self, payload: pb.RoomClosedPayload):
        """Partita finita, room torna disponibile"""
        print_console(f"Room {payload.room_id} closed.", "Gossip")
        self._state.set_room_status(payload.room_id, RoomStatus.DORMANT)

    def _handle_room_player_joined(self, payload: pb.RoomPlayerJoined):
        print_console(f"Player joined room {payload.room_id}", "Gossip")
        room = self._state.get_room(payload.room_id)
        if room is not None:
            room.increment_player_count()

    def broadcast_room_started(self, room_id: str):
        """Chiamato dalla room quando inizia la partita"""
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.ROOM_STARTED,
            room_started=pb.RoomStartedPayload(room_id=room_id)
        )
        self._state.set_room_status(room_id, RoomStatus.PLAYING)
        self._send_messages_and_forward(msg)

    def broadcast_room_closed(self, room_id: str):
        """Chiamato dalla room quando finisce la partita"""
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.ROOM_CLOSED,
            room_closed=pb.RoomClosedPayload(room_id=room_id)
        )
        self._state.set_room_status(room_id, RoomStatus.DORMANT)
        self._send_messages_and_forward(msg)

    def _ensure_peer_exists(self, peer_index: int):
        if self._state.get_peer(peer_index) is None:
            ref = self._calculate_server_reference(peer_index)
            self._state.add_peer(HubPeer(ref, peer_index))

    def _forward_message(self, message: pb.GossipMessage):
        alive_peers: list[HubPeer] = self._state.get_all_not_dead_peers(self._hub_index)
        # alive_peers: list[HubPeer] = self._state.get_all_not_dead_peers()
        targets: list[HubPeer] = random.sample(alive_peers, min(self._fanout, len(alive_peers)))
        references: list[ServerReference] = list(map(lambda e: e.reference, targets))
        message.forwarded_by = self._hub_index
        self._socket_handler.send_to_many(message, references)

    def _calculate_server_reference(self, peer_index: int) -> ServerReference:
        if self._discovery_mode == "manual":
            return ServerReference('127.0.0.1', 9000 + peer_index)
        else:
            service_name = os.environ.get('HUB_SERVICE_NAME', 'hub-service')
            namespace = os.environ.get('K8S_NAMESPACE', 'bomberman')
            return ServerReference(
                f"hub-{peer_index}.{service_name}.{namespace}.svc.cluster.local",
                int(os.environ['GOSSIP_PORT'])
            )

    def _discovery_peers(self):
        peer_no = int(os.environ.get('EXPECTED_HUB_COUNT', self._hub_index + 1))
        discovering_index = random.randrange(0, peer_no, 1)

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

        if self._discovery_mode == "manual" and self._hub_index != 0:
            self._send_messages_specific_destination(msg, ServerReference('127.0.0.1', 9000 + discovering_index))
        if self._discovery_mode == "k8s":
            reference = self._calculate_server_reference(discovering_index)
            self._send_messages_specific_destination(msg, reference)

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
        self._peer_discovery_monitor.stop()
        self._room_health_monitor.stop()
        self._socket_handler.stop()
        self._room_manager.cleanup()

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
        """
        Is called when the peer discover that another one is dead
        """
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

    def _broadcast_room_activated(self, room: Room):
        """Chiamato da RoomManager quando una room viene attivata"""
        # Aggiungi al mio state
        self._state.add_room(room)

        # Broadcast via gossip
        msg = pb.GossipMessage(
            nonce=self._get_next_nonce(),
            origin=self._hub_index,
            forwarded_by=self._hub_index,
            timestamp=time.time(),
            event_type=pb.ROOM_ACTIVATED,
            room_activated=pb.RoomActivatedPayload(
                room_id=room.room_id,
                owner_hub=room.owner_hub_index,
                external_port=room.external_port,
                external_address=self._room_manager.external_domain
            )
        )
        self._send_messages_and_forward(msg)

    def get_or_activate_room(self) -> Room | None:
        """Chiamato dal matchmaking endpoint"""
        room = self._state.get_active_room()
        if room:
            room.increment_player_count()
            msg = pb.GossipMessage(
                nonce=self._get_next_nonce(),
                origin=self._hub_index,
                forwarded_by=self._hub_index,
                timestamp=time.time(),
                event_type=pb.ROOM_PLAYER_JOINED,
                room_player_joined=pb.RoomPlayerJoined(room_id=room.room_id)
            )
            self._send_messages_and_forward(msg)
            return room

        room = self._room_manager.activate_room()
        if room:
            room.increment_player_count()
            msg = pb.GossipMessage(
                nonce=self._get_next_nonce(),
                origin=self._hub_index,
                forwarded_by=self._hub_index,
                timestamp=time.time(),
                event_type=pb.ROOM_PLAYER_JOINED,
                room_player_joined=pb.RoomPlayerJoined(room_id=room.room_id)
            )
            self._send_messages_and_forward(msg)
        return room

    def get_all_peers(self) -> list[HubPeer]:
        return self._state.get_all_peers()

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def hub_index(self) -> int:
        return self._hub_index

    @property
    def discovery_mode(self) -> str:
        return self._discovery_mode

    @property
    def fanout(self) -> int:
        return self._fanout

    @property
    def last_used_nonce(self) -> int:
        return self._last_used_nonce

    @property
    def room_manager(self):
        return self._room_manager

    def get_all_rooms(self):
        return self._state.get_all_rooms()
