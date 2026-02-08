import time
from unittest.mock import MagicMock

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.PeerDiscoveryMonitor import PeerDiscoveryMonitor


class TestPeerDiscoveryMonitor:

    def _make_state_with_peers(self, my_index, alive_indices, dead_indices=None):
        state = HubState()
        state.add_peer(HubPeer(ServerReference("10.0.0.1", 9000 + my_index), my_index))
        for i in alive_indices:
            peer = HubPeer(ServerReference("10.0.0.1", 9000 + i), i)
            state.add_peer(peer)
        for i in (dead_indices or []):
            peer = HubPeer(ServerReference("10.0.0.1", 9000 + i), i)
            peer.status = 'dead'
            state.add_peer(peer)
        return state

    def test_triggers_when_alive_peers_below_fanout(self):
        state = self._make_state_with_peers(0, alive_indices=[1])
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=3, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_called_once()

    def test_does_not_trigger_when_enough_peers(self):
        state = self._make_state_with_peers(0, alive_indices=[1, 2, 3])
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=3, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_not_called()

    def test_does_not_trigger_when_exactly_at_fanout(self):
        state = self._make_state_with_peers(0, alive_indices=[1, 2])
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=2, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_not_called()

    def test_dead_peers_are_not_counted(self):
        state = self._make_state_with_peers(0, alive_indices=[1], dead_indices=[2, 3])
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=3, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_called_once()

    def test_suspected_peers_count_as_not_dead(self):
        """I peer suspected vengono contati come 'non-dead', il che significa
        che se ho abbastanza peer suspected il monitor non triggera' il discovery.
        Questo potrebbe essere un problema se i peer suspected sono in realta' irraggiungibili."""
        state = self._make_state_with_peers(0, alive_indices=[1])
        peer = HubPeer(ServerReference("10.0.0.1", 9002), 2)
        peer.status = 'suspected'
        state.add_peer(peer)
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=2, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_not_called()

    def test_excludes_self_from_count(self):
        state = self._make_state_with_peers(0, alive_indices=[])
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=1, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_called_once()

    def test_no_peers_at_all_triggers(self):
        state = HubState()
        callback = MagicMock()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=1, on_insufficient_peers=callback)
        monitor._check_peer_count()
        callback.assert_called_once()

    def test_start_and_stop(self):
        state = HubState()
        monitor = PeerDiscoveryMonitor(state, my_index=0, fanout=1, on_insufficient_peers=MagicMock())
        monitor.CHECK_INTERVAL = 0.05
        monitor.start()
        assert monitor._running is True
        time.sleep(0.1)
        monitor.stop()
        assert monitor._running is False