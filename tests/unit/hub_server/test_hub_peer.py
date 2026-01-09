# tests/unit/test_hub_peer.py
import pytest
import time
from typing import Literal

from bomberman.hub_server.HubPeer import HubPeer
from bomberman.common.ServerReference import ServerReference


class TestHubPeerInit:
    """Test HubPeer initialization"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_init_sets_default_values(self):
        peer = HubPeer(self.ref, 0)

        assert peer.index == 0
        assert peer.reference == self.ref
        assert peer.status == 'alive'
        assert peer.heartbeat == 0

    def test_init_sets_last_seen_to_now(self):
        before = time.time()
        peer = HubPeer(self.ref, 0)
        after = time.time()

        assert before <= peer.last_seen <= after

    @pytest.mark.parametrize("index", [-1, -100])
    def test_init_negative_index_raises(self, index: int):
        with pytest.raises(ValueError, match="cannot be negative"):
            HubPeer(self.ref, index)


class TestHubPeerIndex:
    """Test index property (read-only)"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_index_is_readonly(self):
        peer = HubPeer(self.ref, 5)

        with pytest.raises(AttributeError):
            peer.index = 10

    @pytest.mark.parametrize("index", [0, 1, 100, 10000])
    def test_index_various_values(self, index: int):
        peer = HubPeer(self.ref, index)
        assert peer.index == index


class TestHubPeerStatus:
    """Test status property"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)
        self.peer = HubPeer(self.ref, 0)

    @pytest.mark.parametrize("status", ['alive', 'suspected', 'dead'])
    def test_status_valid_values(self, status: Literal['alive', 'suspected', 'dead']):
        self.peer.status = status
        assert self.peer.status == status

    @pytest.mark.parametrize("invalid_status", ['invalid', 'ALIVE', 'Dead', ''])
    def test_status_invalid_values_raises(self, invalid_status: str):
        with pytest.raises(ValueError, match="Invalid status"):
            self.peer.status = invalid_status


class TestHubPeerHeartbeat:
    """Test heartbeat property"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)
        self.peer = HubPeer(self.ref, 0)

    @pytest.mark.parametrize("value", [0, 1, 1000, 10**18])
    def test_heartbeat_positive_values(self, value: int):
        self.peer.heartbeat = value
        assert self.peer.heartbeat == value

    @pytest.mark.parametrize("value", [-1, -100])
    def test_heartbeat_negative_values_raises(self, value: int):
        with pytest.raises(ValueError, match="cannot be negative"):
            self.peer.heartbeat = value


class TestHubPeerLastSeen:
    """Test last_seen property"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)
        self.peer = HubPeer(self.ref, 0)

    def test_last_seen_update(self):
        old_value = self.peer.last_seen
        time.sleep(0.05)
        new_value = time.time()

        self.peer.last_seen = new_value

        assert self.peer.last_seen == new_value
        assert self.peer.last_seen > old_value

    def test_last_seen_negative_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            self.peer.last_seen = -1.0


class TestHubPeerReference:
    """Test reference property"""

    def setup_method(self):
        self.ref = ServerReference("127.0.0.1", 9000)
        self.peer = HubPeer(self.ref, 0)

    def test_reference_update(self):
        new_ref = ServerReference("192.168.1.1", 9001)

        self.peer.reference = new_ref

        assert self.peer.reference == new_ref
        assert self.peer.reference.address == "192.168.1.1"
        assert self.peer.reference.port == 9001