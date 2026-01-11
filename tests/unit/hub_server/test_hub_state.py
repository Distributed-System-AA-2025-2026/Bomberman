# tests/unit/test_hub_state.py
import pytest
import time
import threading
from typing import Literal

from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.common.ServerReference import ServerReference


class TestHubStateAddPeer:
    """Test add_peer"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_add_peer_expands_list_with_none(self):
        """List must expand with None up to required index"""
        peer = HubPeer(self.ref, 5)
        self.state.add_peer(peer)

        assert len(self.state._peers) == 6
        assert self.state._peers[5] == peer
        for i in range(5):
            assert self.state._peers[i] is None

    def test_add_peer_overwrites_existing(self):
        """Adding peer with same index overwrites"""
        peer1 = HubPeer(self.ref, 0)
        peer2 = HubPeer(ServerReference("192.168.1.1", 9001), 0)

        self.state.add_peer(peer1)
        self.state.add_peer(peer2)

        assert self.state.get_peer(0) == peer2


class TestHubStateGetPeer:
    """Test get_peer"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_get_peer_not_exists_returns_none(self):
        assert self.state.get_peer(99) is None

    def test_get_peer_none_slot_returns_none(self):
        """Slot with None returns None"""
        peer = HubPeer(self.ref, 5)
        self.state.add_peer(peer)

        assert self.state.get_peer(2) is None

    @pytest.mark.parametrize("index", [-1, -100])
    def test_get_peer_negative_index_raises(self, index: int):
        """Negative indices must raise ValueError"""
        self.state.add_peer(HubPeer(self.ref, 0))

        with pytest.raises(ValueError, match="cannot be negative"):
            self.state.get_peer(index)


class TestHubStateRemovePeer:
    """Test remove_peer - contains failing tests exposing bugs"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_remove_peer_sets_status_dead(self):
        peer = HubPeer(self.ref, 0)
        self.state.add_peer(peer)

        self.state.remove_peer(0)

        assert self.state.get_peer(0).status == 'dead'

    def test_remove_peer_index_out_of_range_raises(self):
        with pytest.raises(ValueError):
            self.state.remove_peer(99)

    def test_remove_peer_none_slot_raises(self):
        self.state.add_peer(HubPeer(self.ref, 5))
        with pytest.raises(ValueError):
            self.state.remove_peer(2)  # Slot is None


class TestHubStateExecuteHeartbeatCheck:
    """Test execute_heartbeat_check - core gossip logic"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_peer_not_exists_returns_false(self):
        result = self.state.execute_heartbeat_check(99, 10, False)
        assert result is False

    @pytest.mark.parametrize("old_hb,new_hb,expected", [
        (0, 1, True),  # New message accepted
        (10, 10, False),  # Same nonce rejected
        (10, 5, False),  # Old message rejected
    ])
    def test_heartbeat_comparison(self, old_hb: int, new_hb: int, expected: bool):
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = old_hb
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, new_hb, False)
        assert result is expected

    def test_peer_leaving_sets_dead(self):
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = 5
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, 10, is_peer_leaving=True)

        assert result is True
        assert self.state.get_peer(0).status == 'dead'

    def test_dead_peer_leaving_again_rejected(self):
        """Dead peer sending PEER_LEAVE is ignored (avoid infinite propagation)"""
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = 10
        peer._status = 'dead'
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, 15, is_peer_leaving=True)
        assert result is False

    def test_dead_peer_returns_with_any_nonce(self):
        """Dead peer coming back is accepted even with lower nonce (crash recovery)"""
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = 1000
        peer._status = 'dead'
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, 1, is_peer_leaving=False)

        assert result is True
        assert self.state.get_peer(0).status == 'alive'
        assert self.state.get_peer(0).heartbeat == 1

    def test_suspected_becomes_alive_on_new_message(self):
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = 5
        peer._status = 'suspected'
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, 10, False)

        assert result is True
        assert self.state.get_peer(0).status == 'alive'


class TestHubStateMarkForwardPeerAsAlive:
    """Test mark_forward_peer_as_alive"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_creates_new_peer_if_not_exists(self):
        self.state.mark_forward_peer_as_alive(0, self.ref)

        peer = self.state.get_peer(0)
        assert peer is not None
        assert peer.status == 'alive'

    def test_updates_last_seen_for_existing_peer(self):
        peer = HubPeer(self.ref, 0)
        old_last_seen = peer.last_seen
        self.state.add_peer(peer)

        time.sleep(0.05)
        self.state.mark_forward_peer_as_alive(0, self.ref)

        assert self.state.get_peer(0).last_seen > old_last_seen

    def test_dead_peer_becomes_alive(self):
        """Direct contact from dead peer resurrects it"""
        peer = HubPeer(self.ref, 0)
        peer._status = 'dead'
        self.state.add_peer(peer)

        self.state.mark_forward_peer_as_alive(0, self.ref)

        assert self.state.get_peer(0).status == 'alive'


class TestHubStateMarkPeerExplicitlyAlive:
    """Test mark_peer_explicitly_alive - for PEER_ALIVE messages"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_updates_status_and_last_seen(self):
        peer = HubPeer(self.ref, 0)
        peer._status = 'suspected'
        old_last_seen = peer.last_seen
        self.state.add_peer(peer)

        time.sleep(0.05)
        self.state.mark_peer_explicitly_alive(0)

        assert self.state.get_peer(0).status == 'alive'
        assert self.state.get_peer(0).last_seen > old_last_seen

    def test_peer_not_exists_does_nothing(self):
        """No exception if peer doesn't exist"""
        self.state.mark_peer_explicitly_alive(99)
        assert self.state.get_peer(99) is None


class TestHubStateGetAllNotDeadPeers:
    """Test get_all_not_dead_peers"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_filters_by_status(self):
        """Returns alive and suspected, excludes dead"""
        for i, status in enumerate(['alive', 'suspected', 'dead']):
            peer = HubPeer(self.ref, i)
            peer._status = status
            self.state.add_peer(peer)

        result = self.state.get_all_not_dead_peers()

        assert len(result) == 2
        indices = [p.index for p in result]
        assert 0 in indices  # alive
        assert 1 in indices  # suspected
        assert 2 not in indices  # dead

    def test_exclude_self(self):
        peer0 = HubPeer(self.ref, 0)
        peer1 = HubPeer(self.ref, 1)
        self.state.add_peer(peer0)
        self.state.add_peer(peer1)

        result = self.state.get_all_not_dead_peers(exclude_peers=0)

        assert len(result) == 1
        assert result[0].index == 1


class TestHubStateGetAllPeers:
    """Test get_all_peers"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_includes_all_statuses(self):
        for i, status in enumerate(['alive', 'suspected', 'dead']):
            peer = HubPeer(self.ref, i)
            peer._status = status
            self.state.add_peer(peer)

        result = self.state.get_all_peers()
        assert len(result) == 3

    def test_exclude_multiple(self):
        for i in range(5):
            self.state.add_peer(HubPeer(self.ref, i))

        result = self.state.get_all_peers(exclude=[0, 2, 4])

        assert len(result) == 2
        indices = [p.index for p in result]
        assert indices == [1, 3]


class TestHubStateThreadSafety:
    """Test thread safety"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_concurrent_add_peer(self):
        """Adding peers from different threads doesn't cause race conditions"""
        errors = []

        def add_peer(index: int):
            try:
                self.state.add_peer(HubPeer(self.ref, index))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_peer, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        for i in range(100):
            assert self.state.get_peer(i) is not None

    def test_concurrent_read_write(self):
        """Concurrent reads and writes don't cause race conditions"""
        for i in range(10):
            self.state.add_peer(HubPeer(self.ref, i))

        errors = []

        def reader():
            try:
                for _ in range(100):
                    self.state.get_all_peers()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(100):
                    self.state.set_peer_status(i % 10, 'suspected')
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestHubStateEdgeCases:
    """Edge cases and boundary conditions"""

    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    def test_negative_heartbeat_rejected(self):
        """Negative heartbeat is less than positive, so rejected"""
        peer = HubPeer(self.ref, 0)
        peer._heartbeat = 10
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, -1, False)
        assert result is False

    def test_very_large_heartbeat(self):
        """Large heartbeat values work correctly"""
        peer = HubPeer(self.ref, 0)
        self.state.add_peer(peer)

        result = self.state.execute_heartbeat_check(0, 10 ** 18, False)

        assert result is True
        assert self.state.get_peer(0).heartbeat == 10 ** 18

class TestHubStateNegativeIndex:
    """Edge cases and boundary conditions"""
    def setup_method(self):
        self.state = HubState()
        self.ref = ServerReference("127.0.0.1", 9000)

    """Test negative index handling across all methods"""
    def test_mark_forward_peer_negative_index(self):
        with pytest.raises(ValueError):
            self.state.mark_forward_peer_as_alive(-1, self.ref)

    def test_execute_heartbeat_check_negative_index(self):
        with pytest.raises(ValueError):
            self.state.execute_heartbeat_check(-1, 10, False)

    def test_update_heartbeat_negative_index(self):
        with pytest.raises(ValueError):
            self.state.update_heartbeat(-1, 10)

    def test_set_peer_status_negative_index(self):
        with pytest.raises(ValueError):
            self.state.set_peer_status(-1, 'dead')

    def test_mark_peer_explicitly_alive_negative_index(self):
        with pytest.raises(ValueError):
            self.state.mark_peer_explicitly_alive(-1)

    def test_remove_peer_negative_index(self):
        with pytest.raises(ValueError):
            self.state.remove_peer(-1)