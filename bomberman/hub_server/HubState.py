from hub_server.HubPeer import HubPeer


class HubState:
    _peers: list[HubPeer | None]


    def __init__(self):
        self._peers = []

    def add_peer(self, peer: HubPeer) -> None:
        while peer.get_index() <= len(self._peers):
            self._peers.append(None)
        self._peers[peer.get_index()] = peer