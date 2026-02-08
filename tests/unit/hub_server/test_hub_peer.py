import pytest
import time
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubPeer import HubPeer


class TestHubPeer:

    def _make_ref(self, addr="10.0.0.1", port=9000):
        return ServerReference(addr, port)

    def test_creation_sets_defaults(self):
        peer = HubPeer(self._make_ref(), 0)
        assert peer.index == 0
        assert peer.status == 'alive'
        assert peer.heartbeat == 0
        assert peer.last_seen > 0

    def test_negative_index_rejected(self):
        with pytest.raises(ValueError):
            HubPeer(self._make_ref(), -1)

    def test_zero_index_accepted(self):
        peer = HubPeer(self._make_ref(), 0)
        assert peer.index == 0

    @pytest.mark.parametrize("status", ['alive', 'suspected', 'dead'])
    def test_valid_status_transitions(self, status):
        peer = HubPeer(self._make_ref(), 0)
        peer.status = status
        assert peer.status == status

    @pytest.mark.parametrize("invalid_status", ['unknown', '', 'ALIVE', 'Dead', 'suspectedx'])
    def test_invalid_status_rejected(self, invalid_status):
        peer = HubPeer(self._make_ref(), 0)
        with pytest.raises(ValueError):
            peer.status = invalid_status

    def test_negative_heartbeat_rejected(self):
        peer = HubPeer(self._make_ref(), 0)
        with pytest.raises(ValueError):
            peer.heartbeat = -1

    def test_heartbeat_zero_accepted(self):
        peer = HubPeer(self._make_ref(), 0)
        peer.heartbeat = 0
        assert peer.heartbeat == 0

    def test_negative_last_seen_rejected(self):
        peer = HubPeer(self._make_ref(), 0)
        with pytest.raises(ValueError):
            peer.last_seen = -1

    def test_reference_can_be_updated(self):
        peer = HubPeer(self._make_ref("1.1.1.1", 1000), 0)
        new_ref = self._make_ref("2.2.2.2", 2000)
        peer.reference = new_ref
        assert peer.reference == new_ref

    def test_last_seen_initialized_to_current_time(self):
        before = time.time()
        peer = HubPeer(self._make_ref(), 0)
        after = time.time()
        assert before <= peer.last_seen <= after

    def test_status_setter_does_not_guard_against_non_string_types(self):
        peer = HubPeer(self._make_ref(), 0)
        with pytest.raises(ValueError):
            peer.status = 123