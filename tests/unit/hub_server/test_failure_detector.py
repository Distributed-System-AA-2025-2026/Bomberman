import time
from unittest.mock import MagicMock, patch

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.FailureDetector import FailureDetector


class TestFailureDetectorCheckPeers:

    def _setup(self, suspect_timeout=5, dead_timeout=20):
        state = HubState()
        on_suspected = MagicMock()
        on_dead = MagicMock()

        with patch.object(FailureDetector, 'SUSPECT_TIMEOUT', suspect_timeout), \
             patch.object(FailureDetector, 'DEAD_TIMEOUT', dead_timeout):
            detector = FailureDetector(
                state=state,
                my_index=0,
                on_peer_suspected=on_suspected,
                on_peer_dead=on_dead,
            )
        detector.SUSPECT_TIMEOUT = suspect_timeout
        detector.DEAD_TIMEOUT = dead_timeout

        return state, detector, on_suspected, on_dead

    def _add_peer(self, state, index, last_seen, status='alive'):
        peer = HubPeer(ServerReference("10.0.0.1", 9000 + index), index)
        peer.last_seen = last_seen
        peer.status = status
        state.add_peer(peer)
        return peer

    def test_alive_peer_within_timeout_is_not_suspected(self):
        state, detector, on_suspected, on_dead = self._setup()
        self._add_peer(state, 1, time.time())
        detector._check_peers()
        on_suspected.assert_not_called()
        on_dead.assert_not_called()

    def test_alive_peer_past_suspect_timeout_becomes_suspected(self):
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 10)
        detector._check_peers()
        on_suspected.assert_called_once_with(1)
        assert state.get_peer(1).status == 'suspected'

    def test_alive_peer_past_dead_timeout_becomes_dead_directly(self):
        """Se il silence supera il dead_timeout, il peer diventa dead direttamente,
        saltando lo stato suspected."""
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 25)
        detector._check_peers()
        on_dead.assert_called_once_with(1)
        assert state.get_peer(1).status == 'dead'

    def test_suspected_peer_past_dead_timeout_becomes_dead(self):
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 25, status='suspected')
        detector._check_peers()
        on_dead.assert_called_once_with(1)

    def test_suspected_peer_within_dead_timeout_stays_suspected(self):
        """Un peer suspected che non ha superato il dead_timeout non viene toccato."""
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 10, status='suspected')
        detector._check_peers()
        on_suspected.assert_not_called()
        on_dead.assert_not_called()

    def test_already_dead_peer_is_not_rechecked(self):
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 100, status='dead')
        detector._check_peers()
        on_dead.assert_not_called()

    def test_self_is_excluded_from_checks(self):
        state, detector, on_suspected, on_dead = self._setup()
        self._add_peer(state, 0, time.time() - 100)
        detector._check_peers()
        on_suspected.assert_not_called()
        on_dead.assert_not_called()

    def test_multiple_peers_checked_independently(self):
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time())
        self._add_peer(state, 2, time.time() - 10)
        self._add_peer(state, 3, time.time() - 25)
        detector._check_peers()
        on_suspected.assert_called_once_with(2)
        on_dead.assert_called_once_with(3)

    def test_start_and_stop(self):
        state, detector, _, _ = self._setup()
        detector.CHECK_INTERVAL = 0.05
        detector.start()
        assert detector._running is True
        time.sleep(0.1)
        detector.stop()
        assert detector._running is False

    def test_peer_past_dead_but_already_dead_skipped_then_suspect_also_checked(self):
        """Verifica che un peer gia' dead non chiama on_dead,
        ma un peer alive oltre suspect_timeout viene comunque gestito."""
        state, detector, on_suspected, on_dead = self._setup(suspect_timeout=5, dead_timeout=20)
        self._add_peer(state, 1, time.time() - 50, status='dead')
        self._add_peer(state, 2, time.time() - 7, status='alive')
        detector._check_peers()
        on_dead.assert_not_called()
        on_suspected.assert_called_once_with(2)