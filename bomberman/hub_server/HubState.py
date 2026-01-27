import time
import threading
from typing import Literal

from bomberman.hub_server.HubPeer import HubPeer
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus


class HubState:
    _peers: list[HubPeer | None]
    _known_rooms: dict[str, Room]
    _lock: threading.RLock

    def __init__(self):
        self._lock = threading.RLock()
        self._peers = []
        self._known_rooms = {}

    def add_peer(self, peer: HubPeer) -> None:
        with self._lock:
            while peer.index >= len(self._peers):
                self._peers.append(None)
            self._peers[peer.index] = peer

    def mark_forward_peer_as_alive(self, forwarding_index: int, forward_peer: ServerReference):
        """
        Segna un peer come alive. Se non esiste, lo crea.

        Args:
            forwarding_index: Indice del peer che ha forwardato il messaggio
            forward_peer: Riferimento al server del peer
        """
        with self._lock:
            if self.get_peer(forwarding_index) is None:
                new_hub = HubPeer(forward_peer, forwarding_index)
                self.add_peer(new_hub)
            else:
                self._peers[forwarding_index].last_seen = time.time()
                self._peers[forwarding_index].status = 'alive'

    def get_peer(self, required_peer: int) -> HubPeer | None:
        if required_peer < 0:
            raise ValueError("Required peer cannot be negative")
        with self._lock:
            if required_peer < len(self._peers):
                return self._peers[required_peer]
            return None

    def execute_heartbeat_check(self, origin_index: int, received_heart_beat: int, is_peer_leaving: bool = False) -> bool:
        """
        Aggiorna l'heartbeat di un peer se quello ricevuto è più recente.

        Args:
            origin_index: Indice del peer (es. 0 per hub-0)
            received_heart_beat: Valore dell'heartbeat ricevuto nel messaggio
            is_peer_leaving: Indica se il peer sta uscendo dal gossip protocol

        Returns:
            True se l'heartbeat è stato aggiornato (era più recente),
            False se il messaggio era obsoleto (heartbeat già visto o più vecchio)
        """
        with self._lock:
            if self.get_peer(origin_index) is None:
                return False
            last_heartbeat = self._peers[origin_index].heartbeat

            # Avoid quit message propagation
            if self.get_peer(origin_index).status == 'dead' and is_peer_leaving:
                return False

            # Peer returns!
            if self.get_peer(origin_index).status == 'dead' and not is_peer_leaving:
                self._peers[origin_index].heartbeat = received_heart_beat
                self._peers[origin_index].status = 'alive'
                return True

            if last_heartbeat < received_heart_beat:
                self._peers[origin_index].heartbeat = received_heart_beat
                self._peers[origin_index].status = 'alive'
                if is_peer_leaving:
                    self._peers[origin_index].status = 'dead'
                return True
        return False

    def remove_peer(self, leaving_peer: int) -> None:
        with self._lock:
            if leaving_peer < 0 or leaving_peer >= len(self._peers):
                raise ValueError
            peer = self._peers[leaving_peer]
            if peer is None:
                raise ValueError
            peer.status = 'dead'

    def get_all_not_dead_peers(self, exclude_peers : int = -1) -> list[HubPeer]:
        """ Return a list of not dead peers (alive or suspected)"""
        with self._lock:
            return list(filter(
                lambda p: p is not None and p.status != 'dead' and p.index != exclude_peers,
                self._peers
            ))

    def update_heartbeat(self, peer_index: int, last_heartbeat: int) -> None:
        with self._lock:
            peer = self.get_peer(peer_index)
            if peer is None:
                return
            peer.heartbeat = last_heartbeat

    def get_all_peers(self, exclude: list[int] = None) -> list[HubPeer]:
        """Returns all existent peer, excluding those in the exclude list"""
        if exclude is None:
            exclude = []
        with self._lock:
            return [
                p for p in self._peers
                if p is not None and p.index not in exclude
            ]

    def set_peer_status(self, peer_index: int, status: Literal['alive', 'suspected', 'dead']) -> None:
        with self._lock:
            peer = self.get_peer(peer_index)
            if peer is not None:
                peer.status = status

    def mark_peer_explicitly_alive(self, peer_index: int) -> None:
        """
        Called when a PEER_ALIVE is received. Update all (include the last_seen param)
        """
        with self._lock:
            peer = self.get_peer(peer_index)
            if peer is not None:
                peer.last_seen = time.time()
                peer.status = 'alive'

    def add_room(self, room: Room) -> None:
        with self._lock:
            self._known_rooms[room.room_id] = room

    def get_room(self, room_id: str) -> Room | None:
        with self._lock:
            return self._known_rooms.get(room_id)

    def get_active_room(self) -> Room | None:
        """Ritorna una room attiva e joinable"""
        with self._lock:
            for room in self._known_rooms.values():
                if room.is_joinable:
                    return room
            return None

    def get_all_rooms(self) -> list[Room]:
        with self._lock:
            return list(self._known_rooms.values())

    def set_room_status(self, room_id: str, status: RoomStatus) -> None:
        with self._lock:
            room = self._known_rooms.get(room_id)
            if room is not None:
                room.status = status