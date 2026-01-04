from common.ServerReference import ServerReference


class HubState:
    peers: list[ServerReference]


    def __init__(self):
        self.peers = []


    def set_peers(self, peers: list[ServerReference]):
        self.peers = peers