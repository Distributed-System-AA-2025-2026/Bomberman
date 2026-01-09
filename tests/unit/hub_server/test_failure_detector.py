import pytest
import time
import threading
from unittest.mock import Mock, patch

# Assuming these imports work in your project structure
# Adjust paths as needed for your actual project
from bomberman.hub_server.FailureDetector import FailureDetector
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.common.ServerReference import ServerReference


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def server_ref():
    """Provide a ServerReference for testing."""
    return ServerReference("127.0.0.1", 9000)


@pytest.fixture
def hub_state():
    """Provide a fresh HubState for each test."""
    return HubState()


@pytest.fixture
def suspected_callback():
    """Provide a mock callback for peer suspected events."""
    return Mock()


@pytest.fixture
def dead_callback():
    """Provide a mock callback for peer dead events."""
    return Mock()


@pytest.fixture
def detector(hub_state, suspected_callback, dead_callback):
    """Provide a FailureDetector instance with standard configuration."""
    return FailureDetector(
        state=hub_state,
        my_index=0,
        on_peer_suspected=suspected_callback,
        on_peer_dead=dead_callback
    )


# ============================================================================
# ============================================================================
# INITIALIZATION TESTS

class TestInitialization:
    """Tests for FailureDetector initialization."""

    def test_init_with_valid_parameters(self, hub_state, suspected_callback, dead_callback):
        """Test initialization with all valid parameters."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        assert detector._state is hub_state
        assert detector._my_index == 0
        assert detector._on_peer_suspected is suspected_callback
        assert detector._on_peer_dead is dead_callback
        assert detector._running is False

    @pytest.mark.parametrize("my_index", [0, 1, 10, 99, 1000])
    def test_init_with_various_positive_indices(
            self, hub_state, suspected_callback, dead_callback, my_index
    ):
        """Test initialization with various positive peer indices."""
        detector = FailureDetector(
            state=hub_state,
            my_index=my_index,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )
        assert detector._my_index == my_index

    @pytest.mark.parametrize("my_index", [-1, -10, -100])
    def test_init_with_negative_indices(
            self, hub_state, suspected_callback, dead_callback, my_index
    ):
        """Test initialization with negative indices (should work but be unusual)."""
        detector = FailureDetector(
            state=hub_state,
            my_index=my_index,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )
        assert detector._my_index == my_index

    def test_init_with_none_state(self, suspected_callback, dead_callback):
        """Test that None state causes AttributeError when methods are called."""
        detector = FailureDetector(
            state=None,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )
        # Should not raise during init
        assert detector._state is None

        # But will fail when _check_peers is called
        with pytest.raises(AttributeError):
            detector._check_peers()

    @pytest.mark.parametrize("invalid_state", ["not_a_state", 123, [], {}, lambda: None])
    def test_init_with_invalid_state_types(
            self, invalid_state, suspected_callback, dead_callback
    ):
        """Test initialization with invalid state types."""
        detector = FailureDetector(
            state=invalid_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Will fail when _check_peers tries to call get_all_peers
        with pytest.raises(AttributeError):
            detector._check_peers()

    def test_init_with_none_callbacks(self, hub_state):
        """Test initialization with None callbacks."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=None,
            on_peer_dead=None
        )

        assert detector._on_peer_suspected is None
        assert detector._on_peer_dead is None

    @pytest.mark.parametrize(
        "invalid_callback",
        ["not_callable", 123, [], {}, object()]
    )
    def test_init_with_invalid_callback_types(self, hub_state, invalid_callback):
        """Test initialization with non-callable callback types."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=invalid_callback,
            on_peer_dead=invalid_callback
        )

        # Should not raise during init
        assert detector._on_peer_suspected is invalid_callback
        assert detector._on_peer_dead is invalid_callback

    def test_init_with_lambda_callbacks(self, hub_state):
        """Test initialization with lambda functions as callbacks."""
        results = []
        suspected = lambda x: results.append(('suspected', x))
        dead = lambda x: results.append(('dead', x))

        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected,
            on_peer_dead=dead
        )

        assert detector._on_peer_suspected is suspected
        assert detector._on_peer_dead is dead


# ============================================================================
# LIFECYCLE TESTS
# ============================================================================

class TestLifecycle:
    """Tests for FailureDetector lifecycle (start/stop)."""

    def test_start_initializes_thread(self, detector):
        """Test that start() creates and starts a daemon thread."""
        detector.start()

        assert detector._running is True
        assert detector._thread is not None
        assert detector._thread.daemon is True
        assert detector._thread.is_alive()

        # Cleanup
        detector.stop()
        time.sleep(0.1)  # Give thread time to stop

    def test_stop_sets_running_to_false(self, detector):
        """Test that stop() sets _running flag to False."""
        detector.start()
        assert detector._running is True

        detector.stop()

        assert detector._running is False

    def test_stop_before_start(self, detector):
        """Test that stop() can be called before start() without error."""
        assert detector._running is False
        detector.stop()
        assert detector._running is False

    def test_multiple_start_calls(self, detector):
        """Test behavior with multiple start() calls."""
        detector.start()
        first_thread = detector._thread

        # Second start creates new thread
        detector.start()
        second_thread = detector._thread

        assert first_thread is not second_thread
        assert detector._running is True

        # Cleanup
        detector.stop()
        time.sleep(0.1)

    def test_multiple_stop_calls(self, detector):
        """Test that multiple stop() calls don't cause errors."""
        detector.start()

        detector.stop()
        detector.stop()
        detector.stop()

        assert detector._running is False

    def test_start_stop_start_sequence(self, detector):
        """Test starting, stopping, and restarting the detector."""
        # First cycle
        detector.start()
        assert detector._running is True
        first_thread = detector._thread

        detector.stop()
        assert detector._running is False

        time.sleep(0.2)  # Wait for thread to finish

        # Second cycle
        detector.start()
        assert detector._running is True
        second_thread = detector._thread

        assert first_thread is not second_thread

        # Cleanup
        detector.stop()
        time.sleep(0.1)

    def test_thread_is_daemon(self, detector):
        """Test that the monitoring thread is a daemon thread."""
        detector.start()

        assert detector._thread.daemon is True

        # Cleanup
        detector.stop()
        time.sleep(0.1)


# ============================================================================
# PEER STATUS TRANSITION TESTS
# ============================================================================

class TestPeerStatusTransitions:
    """Tests for peer status transitions (alive -> suspected -> dead)."""

    def test_peer_transition_alive_to_suspected(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test transition from alive to suspected after SUSPECT_TIMEOUT."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that hasn't been seen recently
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should be suspected now
        assert hub_state.get_peer(1).status == 'suspected'
        suspected_callback.assert_called_once_with(1)
        dead_callback.assert_not_called()

    def test_peer_transition_suspected_to_dead(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test transition from suspected to dead after DEAD_TIMEOUT."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that has been suspected for too long
        old_time = time.time() - FailureDetector.DEAD_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'suspected'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should be dead now
        assert hub_state.get_peer(1).status == 'dead'
        suspected_callback.assert_not_called()
        dead_callback.assert_called_once_with(1)

    def test_peer_transition_alive_to_dead_direct(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test direct transition from alive to dead (skip suspected if DEAD_TIMEOUT passed)."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that hasn't been seen for longer than DEAD_TIMEOUT
        old_time = time.time() - FailureDetector.DEAD_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should be dead (not suspected)
        assert hub_state.get_peer(1).status == 'dead'
        suspected_callback.assert_not_called()
        dead_callback.assert_called_once_with(1)

    def test_peer_remains_alive_when_recently_seen(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that a recently seen peer remains alive."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that was seen recently
        recent_time = time.time() - 1.0  # 1 second ago
        peer = HubPeer(server_ref, 1)
        peer.last_seen = recent_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should still be alive
        assert hub_state.get_peer(1).status == 'alive'
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_suspected_peer_remains_suspected_before_dead_timeout(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that suspected peer doesn't transition to dead before DEAD_TIMEOUT."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a suspected peer that hasn't reached DEAD_TIMEOUT yet
        recent_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 2.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = recent_time
        peer.status = 'suspected'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should still be suspected
        assert hub_state.get_peer(1).status == 'suspected'
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_dead_peer_remains_dead(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that a dead peer remains dead."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that is already dead
        old_time = time.time() - 100.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'dead'
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should still be dead, no callbacks
        assert hub_state.get_peer(1).status == 'dead'
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()


# ============================================================================
# BOUNDARY CONDITION TESTS
# ============================================================================

class TestBoundaryConditions:
    """Tests for boundary timeout conditions."""

    @pytest.mark.parametrize("offset", [-0.1, 0.0, 0.1])
    def test_suspect_timeout_boundary(
            self, hub_state, suspected_callback, dead_callback, server_ref, offset
    ):
        """Test behavior around SUSPECT_TIMEOUT boundary."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Set last_seen to exactly SUSPECT_TIMEOUT + offset
        last_seen = time.time() - FailureDetector.SUSPECT_TIMEOUT - offset
        peer = HubPeer(server_ref, 1)
        peer.last_seen = last_seen
        peer.status = 'alive'
        hub_state.add_peer(peer)

        detector._check_peers()

        # Should be suspected if offset >= 0
        if offset >= 0:
            assert hub_state.get_peer(1).status == 'suspected'
            suspected_callback.assert_called_once()
        else:
            assert hub_state.get_peer(1).status == 'alive'
            suspected_callback.assert_not_called()

    @pytest.mark.parametrize("offset", [-0.1, 0.0, 0.1])
    def test_dead_timeout_boundary(
            self, hub_state, suspected_callback, dead_callback, server_ref, offset
    ):
        """Test behavior around DEAD_TIMEOUT boundary."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Set last_seen to exactly DEAD_TIMEOUT + offset
        last_seen = time.time() - FailureDetector.DEAD_TIMEOUT - offset
        peer = HubPeer(server_ref, 1)
        peer.last_seen = last_seen
        peer.status = 'suspected'
        hub_state.add_peer(peer)

        detector._check_peers()

        # Should be dead if offset >= 0
        if offset >= 0:
            assert hub_state.get_peer(1).status == 'dead'
            dead_callback.assert_called_once()
        else:
            assert hub_state.get_peer(1).status == 'suspected'
            dead_callback.assert_not_called()

    def test_exact_suspect_timeout(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test peer at exact SUSPECT_TIMEOUT."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Mock time to have deterministic behavior
        mock_now = 1000.0
        last_seen = mock_now - FailureDetector.SUSPECT_TIMEOUT

        peer = HubPeer(server_ref, 1)
        peer.last_seen = last_seen
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Mock time.time() to return exact value
        with patch('time.time', return_value=mock_now):
            detector._check_peers()

        # At exact timeout, should still be alive (needs to exceed)
        assert hub_state.get_peer(1).status == 'alive'
        suspected_callback.assert_not_called()

    def test_exact_dead_timeout(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test peer at exact DEAD_TIMEOUT."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        last_seen = time.time() - FailureDetector.SUSPECT_TIMEOUT - FailureDetector.CHECK_INTERVAL
        peer = HubPeer(server_ref, 1)
        peer.last_seen = last_seen
        peer.status = 'suspected'
        hub_state.add_peer(peer)

        detector._check_peers()

        # At exact timeout, should still be suspected (needs to exceed)
        assert hub_state.get_peer(1).status == 'suspected'
        dead_callback.assert_not_called()


# ============================================================================
# SELF-EXCLUSION TESTS
# ============================================================================

class TestSelfExclusion:
    """Tests for proper exclusion of self (my_index)."""

    def test_self_is_excluded_from_checks(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that the detector's own peer is excluded from checks."""
        MY_INDEX = 5
        detector = FailureDetector(
            state=hub_state,
            my_index=MY_INDEX,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add self as a peer with old last_seen
        old_time = time.time() - FailureDetector.DEAD_TIMEOUT - 10.0
        self_peer = HubPeer(server_ref, MY_INDEX)
        self_peer.last_seen = old_time
        self_peer.status = 'alive'
        hub_state.add_peer(self_peer)

        # Run check
        detector._check_peers()

        # Self should not be marked as suspected or dead
        assert hub_state.get_peer(MY_INDEX).status == 'alive'
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_self_exclusion_with_multiple_peers(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test self-exclusion when multiple peers exist."""
        MY_INDEX = 2
        detector = FailureDetector(
            state=hub_state,
            my_index=MY_INDEX,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0

        # Add multiple peers including self
        for i in range(5):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        detector._check_peers()

        # All except self should be suspected
        for i in range(5):
            if i == MY_INDEX:
                assert hub_state.get_peer(i).status == 'alive'
            else:
                assert hub_state.get_peer(i).status == 'suspected'

        # Should have been called for all peers except self
        assert suspected_callback.call_count == 4

    @pytest.mark.parametrize("my_index", [0, 5, 10])
    def test_various_self_indices(
            self, hub_state, suspected_callback, dead_callback, server_ref, my_index
    ):
        """Test self-exclusion with various my_index values."""
        detector = FailureDetector(
            state=hub_state,
            my_index=my_index,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0

        # Add peers
        for i in [0, 5, 10]:
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        detector._check_peers()

        # Only self should remain alive
        assert hub_state.get_peer(my_index).status == 'alive'


# ============================================================================
# EMPTY STATE TESTS
# ============================================================================

class TestEmptyState:
    """Tests for behavior with empty or minimal peer lists."""

    def test_empty_peer_list(self, hub_state, suspected_callback, dead_callback):
        """Test behavior when there are no peers."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Run check with no peers
        detector._check_peers()

        # Should not crash, no callbacks
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_only_self_in_peer_list(self, hub_state, suspected_callback, dead_callback, server_ref):
        """Test behavior when only self exists in peer list."""
        MY_INDEX = 0
        detector = FailureDetector(
            state=hub_state,
            my_index=MY_INDEX,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add only self
        peer = HubPeer(server_ref, MY_INDEX)
        hub_state.add_peer(peer)

        # Run check
        detector._check_peers()

        # Should not check self, no callbacks
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_single_other_peer(self, hub_state, suspected_callback, dead_callback, server_ref):
        """Test behavior with a single peer (not self)."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add one peer
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        detector._check_peers()

        # Should suspect the peer
        assert hub_state.get_peer(1).status == 'suspected'
        suspected_callback.assert_called_once_with(1)


# ============================================================================
# CALLBACK EXCEPTION HANDLING TESTS
# ============================================================================

class TestCallbackExceptionHandling:
    """Tests for proper handling of exceptions in callbacks."""

    def test_suspected_callback_exception_does_not_crash(
            self, hub_state, dead_callback, server_ref
    ):
        """Test that exception in suspected callback doesn't crash the detector."""
        exception_callback = Mock(side_effect=RuntimeError("Callback failed"))

        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=exception_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer that should be suspected
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Should raise exception from callback
        with pytest.raises(RuntimeError, match="Callback failed"):
            detector._check_peers()

        # But status should still be updated
        assert hub_state.get_peer(1).status == 'suspected'

    def test_dead_callback_exception_does_not_crash(
            self, hub_state, suspected_callback, server_ref
    ):
        """Test that exception in dead callback doesn't crash the detector."""
        exception_callback = Mock(side_effect=ValueError("Dead callback failed"))

        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=exception_callback
        )

        # Add a peer that should be dead
        old_time = time.time() - FailureDetector.DEAD_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'suspected'
        hub_state.add_peer(peer)

        # Should raise exception from callback
        with pytest.raises(ValueError, match="Dead callback failed"):
            detector._check_peers()

        # But status should still be updated
        assert hub_state.get_peer(1).status == 'dead'

    def test_none_callback_raises_type_error(
            self, hub_state, server_ref
    ):
        """Test that None callbacks raise TypeError when invoked."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=None,
            on_peer_dead=None
        )

        # Add a peer that should be suspected
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Should raise TypeError when trying to call None
        with pytest.raises(TypeError):
            detector._check_peers()

    def test_non_callable_callback_raises_type_error(
            self, hub_state, server_ref
    ):
        """Test that non-callable callbacks raise TypeError."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected="not_callable",
            on_peer_dead="also_not_callable"
        )

        # Add a peer that should be suspected
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = old_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # Should raise TypeError
        with pytest.raises(TypeError):
            detector._check_peers()


# ============================================================================
# MULTIPLE PEERS TESTS
# ============================================================================

class TestMultiplePeers:
    """Tests for scenarios with multiple peers."""

    def test_multiple_peers_different_states(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test multiple peers in different states."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        now = time.time()

        # Peer 1: alive (recent)
        ref1 = ServerReference("127.0.0.1", 9001)
        peer1 = HubPeer(ref1, 1)
        peer1.last_seen = now - 1.0
        peer1.status = 'alive'
        hub_state.add_peer(peer1)

        # Peer 2: should become suspected
        ref2 = ServerReference("127.0.0.1", 9002)
        peer2 = HubPeer(ref2, 2)
        peer2.last_seen = now - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer2.status = 'alive'
        hub_state.add_peer(peer2)

        # Peer 3: already suspected, should stay suspected
        ref3 = ServerReference("127.0.0.1", 9003)
        peer3 = HubPeer(ref3, 3)
        peer3.last_seen = now - FailureDetector.SUSPECT_TIMEOUT - 2.0
        peer3.status = 'suspected'
        hub_state.add_peer(peer3)

        # Peer 4: should become dead
        ref4 = ServerReference("127.0.0.1", 9004)
        peer4 = HubPeer(ref4, 4)
        peer4.last_seen = now - FailureDetector.DEAD_TIMEOUT - 1.0
        peer4.status = 'suspected'
        hub_state.add_peer(peer4)

        detector._check_peers()

        # Verify states
        assert hub_state.get_peer(1).status == 'alive'
        assert hub_state.get_peer(2).status == 'suspected'
        assert hub_state.get_peer(3).status == 'suspected'
        assert hub_state.get_peer(4).status == 'dead'

        # Verify callbacks
        suspected_callback.assert_called_once_with(2)
        dead_callback.assert_called_once_with(4)

    def test_all_peers_timeout_simultaneously(
            self, hub_state, suspected_callback, dead_callback
    ):
        """Test multiple peers timing out at the same time."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0

        # Add multiple peers with same old timestamp
        for i in range(1, 6):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        detector._check_peers()

        # All should be suspected
        for i in range(1, 6):
            assert hub_state.get_peer(i).status == 'suspected'

        # Callback should be called for each peer
        assert suspected_callback.call_count == 5

    def test_large_number_of_peers(
            self, hub_state, suspected_callback, dead_callback
    ):
        """Test with a large number of peers."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0

        # Add 100 peers
        for i in range(1, 101):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        detector._check_peers()

        # All should be suspected
        for i in range(1, 101):
            assert hub_state.get_peer(i).status == 'suspected'

        # Callback should be called 100 times
        assert suspected_callback.call_count == 100


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for complete lifecycle scenarios."""

    def test_full_lifecycle_with_thread(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test full lifecycle: start, detect, stop."""
        # Use custom short timeouts for faster testing
        original_suspect = FailureDetector.SUSPECT_TIMEOUT
        original_dead = FailureDetector.DEAD_TIMEOUT
        original_interval = FailureDetector.CHECK_INTERVAL

        try:
            FailureDetector.SUSPECT_TIMEOUT = 0.5
            FailureDetector.DEAD_TIMEOUT = 1.5
            FailureDetector.CHECK_INTERVAL = 0.2

            detector = FailureDetector(
                state=hub_state,
                my_index=0,
                on_peer_suspected=suspected_callback,
                on_peer_dead=dead_callback
            )

            # Add a peer
            peer = HubPeer(server_ref, 1)
            peer.last_seen = time.time()
            peer.status = 'alive'
            hub_state.add_peer(peer)

            # Start detector
            detector.start()

            # Wait for it to become suspected
            time.sleep(0.8)
            assert hub_state.get_peer(1).status == 'suspected'
            assert suspected_callback.call_count >= 1

            # Wait for it to become dead
            time.sleep(1.2)
            assert hub_state.get_peer(1).status == 'dead'
            assert dead_callback.call_count >= 1

            # Stop detector
            detector.stop()
            time.sleep(0.3)

        finally:
            # Restore original timeouts
            FailureDetector.SUSPECT_TIMEOUT = original_suspect
            FailureDetector.DEAD_TIMEOUT = original_dead
            FailureDetector.CHECK_INTERVAL = original_interval

    def test_peer_recovery(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that a peer can recover by updating last_seen."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add a peer
        peer = HubPeer(server_ref, 1)
        peer.last_seen = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        peer.status = 'alive'
        hub_state.add_peer(peer)

        # First check: should become suspected
        detector._check_peers()
        assert hub_state.get_peer(1).status == 'suspected'
        suspected_callback.assert_called_once()

        # Peer recovers
        hub_state.get_peer(1).last_seen = time.time()
        hub_state.get_peer(1).status = 'alive'

        # Second check: should remain alive
        detector._check_peers()
        assert hub_state.get_peer(1).status == 'alive'
        # No new callback calls
        assert suspected_callback.call_count == 1
        assert dead_callback.call_count == 0


# ============================================================================
# CONCURRENT ACCESS TESTS
# ============================================================================

class TestConcurrentAccess:
    """Tests for thread safety and concurrent access."""

    def test_concurrent_check_peers_calls(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test multiple concurrent _check_peers calls."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add some peers
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        for i in range(1, 6):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        # Run multiple checks concurrently
        threads = []
        for _ in range(10):
            t = threading.Thread(target=detector._check_peers)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All peers should be suspected
        for i in range(1, 6):
            assert hub_state.get_peer(i).status == 'suspected'

        # Callback should be called at least once for each peer
        # (might be more due to race conditions)
        assert suspected_callback.call_count >= 5

    def test_state_modification_during_check(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test that state can be safely modified during checks."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add initial peers
        for i in range(1, 4):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = time.time()
            peer.status = 'alive'
            hub_state.add_peer(peer)

        # Function to add more peers concurrently
        def add_peers():
            for i in range(4, 7):
                ref = ServerReference("127.0.0.1", 9000 + i)
                peer = HubPeer(ref, i)
                peer.last_seen = time.time()
                peer.status = 'alive'
                hub_state.add_peer(peer)
                time.sleep(0.01)

        # Start adding peers in background
        add_thread = threading.Thread(target=add_peers)
        add_thread.start()

        # Run checks multiple times
        for _ in range(5):
            detector._check_peers()
            time.sleep(0.01)

        add_thread.join()

        # Should not crash, all peers should exist
        for i in range(1, 7):
            assert hub_state.get_peer(i) is not None


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestEdgeCases:
    """Tests for unusual edge cases."""

    def test_negative_last_seen_raises_error(self, hub_state, suspected_callback, dead_callback, server_ref):
        """Test that negative last_seen raises ValueError in HubPeer."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        peer = HubPeer(server_ref, 1)

        # Should raise ValueError
        with pytest.raises(ValueError, match="Last seen cannot be negative"):
            peer.last_seen = -1.0

    def test_future_last_seen(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test peer with last_seen in the future."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Peer with future timestamp
        future_time = time.time() + 1000.0
        peer = HubPeer(server_ref, 1)
        peer.last_seen = future_time
        peer.status = 'alive'
        hub_state.add_peer(peer)

        detector._check_peers()

        # Should remain alive (negative silence)
        assert hub_state.get_peer(1).status == 'alive'
        suspected_callback.assert_not_called()
        dead_callback.assert_not_called()

    def test_zero_last_seen(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test peer with last_seen = 0 (epoch time)."""
        detector = FailureDetector(
            state=hub_state,
            my_index=0,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        peer = HubPeer(server_ref, 1)
        peer.last_seen = 0.0
        peer.status = 'alive'
        hub_state.add_peer(peer)

        detector._check_peers()

        # Should definitely be dead (very old)
        assert hub_state.get_peer(1).status == 'dead'
        dead_callback.assert_called_once()

    def test_very_large_my_index(
            self, hub_state, suspected_callback, dead_callback, server_ref
    ):
        """Test with very large my_index value."""
        MY_INDEX = 999999
        detector = FailureDetector(
            state=hub_state,
            my_index=MY_INDEX,
            on_peer_suspected=suspected_callback,
            on_peer_dead=dead_callback
        )

        # Add some regular peers
        old_time = time.time() - FailureDetector.SUSPECT_TIMEOUT - 1.0
        for i in range(1, 4):
            ref = ServerReference("127.0.0.1", 9000 + i)
            peer = HubPeer(ref, i)
            peer.last_seen = old_time
            peer.status = 'alive'
            hub_state.add_peer(peer)

        detector._check_peers()

        # All should be suspected
        for i in range(1, 4):
            assert hub_state.get_peer(i).status == 'suspected'
        assert suspected_callback.call_count == 3