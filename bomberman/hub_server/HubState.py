import time
import threading

from bomberman.hub_server.HubPeer import HubPeer
from common.ServerReference import ServerReference


class HubState:
    _peers: list[HubPeer | None]
    _lock: threading.RLock


    def __init__(self):
        self._lock = threading.RLock()
        self._peers = []

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
        with self._lock:
            if required_peer < len(self._peers):
                return self._peers[required_peer]
            return None


    def execute_heartbeat_check(self, origin_index: int, received_heart_beat: int) -> bool:
        """
        Aggiorna l'heartbeat di un peer se quello ricevuto è più recente.

        Args:
            origin_index: Indice del peer (es. 0 per hub-0)
            received_heart_beat: Valore dell'heartbeat ricevuto nel messaggio

        Returns:
            True se l'heartbeat è stato aggiornato (era più recente),
            False se il messaggio era obsoleto (heartbeat già visto o più vecchio)
        """
        with self._lock:
            if self.get_peer(origin_index) is None:
                return False
            last_heartbeat = self._peers[origin_index].heartbeat
            if last_heartbeat < received_heart_beat:
                self._peers[origin_index].heartbeat = received_heart_beat
                return True
        return False