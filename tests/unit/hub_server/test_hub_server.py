# test_hub_server.py
import pytest
import pytest
import os
import time
from unittest.mock import Mock, patch

from kubernetes import config

from bomberman.hub_server.HubServer import HubServer, get_hub_index, print_console
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.hub_server.FailureDetector import FailureDetector
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.Room import Room


class TestGetHubIndex:
    """Test suite for get_hub_index function"""

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-1.local", 1),
        ("hub-34.local", 34),
        ("hub-542.hub-headless.default.svc.cluster.local", 542),
        ("hub-1000.local", 1000),
        ("hub-20930.hub-headless.default.svc.cluster.local", 20930),
    ])
    def test_valid_indices_different_magnitudes(self, hostname: str, expected: int):
        """Test parsing of hub indices across different orders of magnitude"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-0.local", 0),
        ("hub-0.hub-headless.default.svc.cluster.local", 0),
    ])
    def test_index_zero(self, hostname: str, expected: int):
        """Test that index 0 is correctly parsed (edge case: first pod)"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-007.local", 7),
        ("hub-0042.local", 42),
    ])
    def test_leading_zeros(self, hostname: str, expected: int):
        """Test that leading zeros are handled correctly"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-99999999.local", 99999999),
        ("hub-123456789.hub-headless.default.svc.cluster.local", 123456789),
    ])
    def test_large_indices(self, hostname: str, expected: int):
        """Test parsing of very large indices"""
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname", [
        "",                          # empty string
        "hub-.local",                # missing index
        "hub.local",                 # missing dash and index
        "server-0.local",            # wrong prefix
        "HUB-0.local",               # wrong case
        "hub-abc.local",             # letters instead of digits
        "hub-12abc.local",           # mixed digits and letters
        "hub--1.local",              # double dash (negative-like)
        "0-hub.local",               # reversed format
        "  hub-0.local",             # leading whitespace
        "hub-0.local  ",             # trailing whitespace (re.match handles this, but let's be explicit)
    ])
    def test_invalid_hostname_raises_value_error(self, hostname: str):
        """Test that invalid hostnames raise ValueError"""
        with pytest.raises(ValueError, match="Invalid hub hostname"):
            get_hub_index(hostname)

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-5", 5),                           # no domain
        ("hub-123.a.b.c.d.e.f.g", 123),         # deeply nested domain
    ])
    def test_various_domain_formats(self, hostname: str, expected: int):
        """Test that domain suffix doesn't affect parsing"""
        assert get_hub_index(hostname) == expected


@pytest.fixture
def mock_env_manual():
    """Mock environment variables for manual discovery mode."""
    return {
        'HOSTNAME': 'hub-0',
        'GOSSIP_PORT': '9000',
        'HUB_FANOUT': '4'
    }


@pytest.fixture
def mock_env_k8s():
    """Mock environment variables for k8s discovery mode."""
    return {
        'HOSTNAME': 'hub-1.hub-headless',
        'GOSSIP_PORT': '9000',
        'HUB_FANOUT': '3'
    }


@pytest.fixture
def mock_k8s_config():
    """Mock Kubernetes configuration loading."""
    with patch('kubernetes.config.load_incluster_config') as mock_incluster, \
            patch('kubernetes.config.load_kube_config') as mock_kube, \
            patch('kubernetes.client.CoreV1Api') as mock_api:
        # Simula che load_incluster_config fallisce (non in cluster)
        mock_incluster.side_effect = config.ConfigException("Not in cluster")

        # load_kube_config ha successo (simula kubeconfig locale)
        mock_kube.return_value = None

        # Mock della API
        mock_api_instance = Mock()
        mock_api.return_value = mock_api_instance

        yield {
            'incluster': mock_incluster,
            'kube_config': mock_kube,
            'api': mock_api_instance
        }

@pytest.fixture
def mock_peer_discovery_monitor():
    with patch('bomberman.hub_server.HubServer.PeerDiscoveryMonitor', autospec=True) as mock:
        yield mock.return_value


@pytest.fixture
def mock_socket_handler():
    """Mock HubSocketHandler to avoid real networking."""
    with patch('bomberman.hub_server.HubServer.HubSocketHandler') as mock:
        handler_instance = Mock(spec=HubSocketHandler)
        mock.return_value = handler_instance
        yield handler_instance


@pytest.fixture
def mock_failure_detector():
    """Mock FailureDetector to avoid real threading."""
    with patch('bomberman.hub_server.HubServer.FailureDetector') as mock:
        detector_instance = Mock(spec=FailureDetector)
        mock.return_value = detector_instance
        yield detector_instance


def create_gossip_message(
        nonce: int,
        origin: int,
        forwarded_by: int,
        event_type: int,
        **payload_kwargs
) -> pb.GossipMessage:
    """Helper to create GossipMessage for testing."""
    msg = pb.GossipMessage(
        nonce=nonce,
        origin=origin,
        forwarded_by=forwarded_by,
        timestamp=time.time(),
        event_type=event_type
    )

    # Set the appropriate payload based on event_type
    if event_type == pb.PEER_JOIN:
        msg.peer_join.CopyFrom(pb.PeerJoinPayload(**payload_kwargs))
    elif event_type == pb.PEER_LEAVE:
        msg.peer_leave.CopyFrom(pb.PeerLeavePayload(**payload_kwargs))
    elif event_type == pb.PEER_ALIVE:
        msg.peer_alive.CopyFrom(pb.PeerAlivePayload(**payload_kwargs))
    elif event_type == pb.PEER_SUSPICIOUS:
        msg.peer_suspicious.CopyFrom(pb.PeerSuspiciousPayload(**payload_kwargs))
    elif event_type == pb.PEER_DEAD:
        msg.peer_dead.CopyFrom(pb.PeerDeadPayload(**payload_kwargs))
    elif event_type == pb.ROOM_ACTIVATED:
        msg.room_activated.CopyFrom(pb.RoomActivatedPayload(**payload_kwargs))
    elif event_type == pb.ROOM_STARTED:
        msg.room_closed.CopyFrom(pb.RoomClosedPayload(**payload_kwargs))

    return msg

class TestGetHubIndex:
    """Tests for get_hub_index() function."""

    @pytest.mark.parametrize("hostname,expected_index", [
        ("hub-0", 0),
        ("hub-1", 1),
        ("hub-5", 5),
        ("hub-42", 42),
        ("hub-999", 999),
        ("hub-0.hub-headless", 0),
        ("hub-1.hub-headless.default.svc.cluster.local", 1),
        ("hub-123.some-domain", 123),
    ])
    def test_valid_hostnames(self, hostname, expected_index):
        """Test parsing of valid hostnames."""
        assert get_hub_index(hostname) == expected_index

    @pytest.mark.parametrize("invalid_hostname", [
        "hub",  # No number
        "hub-",  # No number after dash
        "hub-abc",  # Non-numeric
        "hub-1-2",  # Multiple numbers
        "wrong-0",  # Wrong prefix
        "0-hub",  # Reversed
        "HUB-0",  # Wrong case
        "",  # Empty
        "   hub-0   ",  # Leading/trailing spaces
        " hub-0",  # Leading space
        "hub-0 ",  # Trailing space
    ])
    def test_invalid_hostnames(self, invalid_hostname):
        """Test that invalid hostnames raise ValueError."""
        with pytest.raises(ValueError, match="Invalid hub hostname"):
            get_hub_index(invalid_hostname)

    def test_hostname_with_whitespace_raises_error(self):
        """Test that hostname with whitespace raises specific error."""
        with pytest.raises(ValueError, match="Invalid hub hostname"):
            get_hub_index("  hub-0  ")

    @pytest.mark.parametrize("hostname", [
        "hub--0",  # Double dash
        "hub-0-0",  # Extra dash and number
        "-hub-0",  # Leading dash
    ])
    def test_malformed_hostnames(self, hostname):
        """Test malformed hostname patterns."""
        with pytest.raises(ValueError):
            get_hub_index(hostname)

    def test_none_hostname(self):
        """Test that None hostname raises error."""
        with pytest.raises(AttributeError):
            get_hub_index(None)

    @pytest.mark.parametrize("invalid_type", [123, [], {}, object()])
    def test_invalid_hostname_types(self, invalid_type):
        """Test that non-string types raise appropriate errors."""
        with pytest.raises(AttributeError):
            get_hub_index(invalid_type)

class TestPrintConsole:
    """Tests for print_console() function."""

    @pytest.mark.parametrize("category", ['Error', 'Gossip', 'Info', 'FailureDetector'])
    def test_print_console_with_all_categories(self, category, capsys):
        """Test print_console with all valid categories."""
        message = "Test message"
        print_console(message, category)

        captured = capsys.readouterr()
        assert message in captured.out
        assert category in captured.out
        assert "[HubServer]" in captured.out

    def test_print_console_default_category(self, capsys):
        """Test print_console with default category."""
        message = "Default category test"
        print_console(message)

        captured = capsys.readouterr()
        assert message in captured.out
        assert "Gossip" in captured.out  # Default category

    def test_print_console_formats_timestamp(self, capsys):
        """Test that print_console includes timestamp."""
        print_console("Timestamp test")

        captured = capsys.readouterr()
        # Should contain date format YYYY-MM-DD
        assert "-" in captured.out
        # Should contain time format HH:MM:SS
        assert ":" in captured.out

class TestHubServerInitialization:
    """Tests for HubServer initialization."""

    def test_init_manual_mode_hub_0(self, mock_env_manual, mock_socket_handler, mock_failure_detector, mock_peer_discovery_monitor):
        """Test initialization in manual mode as hub-0."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            assert server._hub_index == 0
            assert server._hostname == 'hub-0'
            assert server._discovery_mode == 'manual'
            assert server._fanout == 4
            assert server._last_used_nonce == 0

            # Verify socket handler was started
            mock_socket_handler.start.assert_called_once()

            # Verify failure detector was created and started
            mock_failure_detector.start.assert_called_once()

            # Verify self was added to state
            assert server._state.get_peer(0) is not None

    def test_init_manual_mode_hub_1(self, mock_socket_handler, mock_failure_detector):
        """Test initialization in manual mode as hub-1."""
        env = {'HOSTNAME': 'hub-1', 'GOSSIP_PORT': '9001', 'HUB_FANOUT': '3'}

        with patch.dict(os.environ, env), \
            patch('bomberman.hub_server.HubServer.random.randrange', return_value=0):

            server = HubServer(discovery_mode='manual')

            assert server._hub_index == 1
            assert server._fanout == 3

            # Hub-1 should send discovery message to hub-0
            mock_socket_handler.send.assert_called_once()
            call_args = mock_socket_handler.send.call_args
            message = call_args[0][0]
            destination = call_args[0][1]

            assert message.event_type == pb.PEER_JOIN
            assert message.origin == 1
            assert destination.address == '127.0.0.1'
            assert destination.port == 9000

    def test_init_k8s_mode(self, mock_env_k8s, mock_socket_handler, mock_failure_detector, mock_k8s_config):
        """Test initialization in k8s mode."""
        with patch.dict(os.environ, mock_env_k8s):
            server = HubServer(discovery_mode='k8s')

            assert server._hub_index == 1
            assert server._discovery_mode == 'k8s'

            # Verify self peer has correct k8s reference
            self_peer = server._state.get_peer(1)
            assert self_peer is not None

    def test_init_default_fanout(self, mock_socket_handler, mock_failure_detector):
        """Test initialization with default fanout when env var not set."""
        env = {'HOSTNAME': 'hub-0', 'GOSSIP_PORT': '9000'}

        with patch.dict(os.environ, env, clear=True):
            server = HubServer(discovery_mode='manual')

            assert server._fanout == 4  # Default value

    def test_init_custom_fanout(self, mock_socket_handler, mock_failure_detector):
        """Test initialization with custom fanout from environment."""
        env = {'HOSTNAME': 'hub-0', 'GOSSIP_PORT': '9000', 'HUB_FANOUT': '10'}

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            assert server._fanout == 10

    @pytest.mark.parametrize("invalid_fanout", ['abc', '', '-1', '0.5'])
    def test_init_invalid_fanout_raises_error(self, mock_socket_handler, mock_failure_detector, invalid_fanout):
        """Test that invalid fanout values raise ValueError."""
        env = {'HOSTNAME': 'hub-0', 'GOSSIP_PORT': '9000', 'HUB_FANOUT': invalid_fanout}

        with patch.dict(os.environ, env):
            with pytest.raises(ValueError):
                HubServer(discovery_mode='manual')

    def test_init_missing_hostname_raises_error(self, mock_socket_handler, mock_failure_detector):
        """Test that wrong HOSTNAME raises KeyError."""
        env = {'GOSSIP_PORT': '9000', 'HOSTNAME': 'hb0'}

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError):
                HubServer(discovery_mode='manual')

    def test_init_missing_gossip_port_raises_error(self, mock_socket_handler, mock_failure_detector):
        """Test that missing GOSSIP_PORT raises KeyError."""
        env = {'HOSTNAME': 'hub-0'}

        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(KeyError):
                HubServer(discovery_mode='manual')

    def test_init_invalid_hostname_raises_error(self, mock_socket_handler, mock_failure_detector):
        """Test that invalid hostname raises ValueError."""
        env = {'HOSTNAME': 'invalid-name', 'GOSSIP_PORT': '9000'}

        with patch.dict(os.environ, env):
            with pytest.raises(ValueError, match="Invalid hub hostname"):
                HubServer(discovery_mode='manual')

    def test_failure_detector_callbacks_are_set(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that failure detector is initialized with correct callbacks."""
        with patch.dict(os.environ, mock_env_manual):
            with patch('bomberman.hub_server.HubServer.FailureDetector') as mock_fd_class:
                mock_fd_instance = Mock()
                mock_fd_class.return_value = mock_fd_instance

                server = HubServer(discovery_mode='manual')

                # Verify FailureDetector was created with correct parameters
                mock_fd_class.assert_called_once()
                call_kwargs = mock_fd_class.call_args[1]

                assert call_kwargs['state'] == server._state
                assert call_kwargs['my_index'] == 0
                assert callable(call_kwargs['on_peer_suspected'])
                assert callable(call_kwargs['on_peer_dead'])

class TestPeerManagement:
    """Tests for peer management methods."""

    def test_ensure_peer_exists_creates_new_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _ensure_peer_exists creates a peer if it doesn't exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Peer 5 doesn't exist initially
            assert server._state.get_peer(5) is None

            server._ensure_peer_exists(5)

            # Now it should exist
            peer = server._state.get_peer(5)
            assert peer is not None
            assert peer.index == 5

    def test_ensure_peer_exists_does_not_overwrite_existing(self, mock_env_manual, mock_socket_handler,
                                                            mock_failure_detector):
        """Test that _ensure_peer_exists doesn't overwrite existing peer."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer manually
            ref = ServerReference("192.168.1.1", 8888)
            original_peer = HubPeer(ref, 3)
            server._state.add_peer(original_peer)

            # Call ensure_peer_exists
            server._ensure_peer_exists(3)

            # Should still be the original peer
            peer = server._state.get_peer(3)
            assert peer.reference.address == "192.168.1.1"
            assert peer.reference.port == 8888

    @pytest.mark.parametrize("peer_index", [0, 1, 10, 100, 999])
    def test_ensure_peer_exists_various_indices(self, mock_env_manual, mock_socket_handler, mock_failure_detector,
                                                peer_index):
        """Test _ensure_peer_exists with various peer indices."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            server._ensure_peer_exists(peer_index)

            assert server._state.get_peer(peer_index) is not None

    def test_calculate_server_reference_manual_mode(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test _calculate_server_reference in manual mode."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            ref = server._calculate_server_reference(5)

            assert ref.address == '127.0.0.1'
            assert ref.port == 9005  # 9000 + 5

    def test_calculate_server_reference_k8s_mode(self, mock_env_k8s, mock_socket_handler, mock_failure_detector, mock_k8s_config):
        """Test _calculate_server_reference in k8s mode."""
        with patch.dict(os.environ, mock_env_k8s):
            server = HubServer(discovery_mode='k8s')

            ref = server._calculate_server_reference(3)

            assert ref.address == 'hub-3.hub-service.bomberman.svc.cluster.local'
            assert ref.port == 9000

    @pytest.mark.parametrize("peer_index,expected_port", [
        (0, 9000),
        (1, 9001),
        (10, 9010),
        (99, 9099),
    ])
    def test_calculate_server_reference_manual_various_indices(
            self, mock_env_manual, mock_socket_handler, mock_failure_detector, peer_index, expected_port
    ):
        """Test _calculate_server_reference with various indices in manual mode."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            ref = server._calculate_server_reference(peer_index)

            assert ref.port == expected_port

class TestMessageForwarding:
    """Tests for message forwarding logic."""

    def test_forward_message_respects_fanout(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _forward_message respects fanout limit."""
        env = dict(mock_env_manual)
        env['HUB_FANOUT'] = '2'  # Fanout of 2

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            # Add 5 peers
            for i in range(1, 6):
                server._ensure_peer_exists(i)

            # Create a message
            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            # Forward the message
            server._forward_message(msg)

            # Should call send_to_many with exactly 2 peers (fanout limit)
            mock_socket_handler.send_to_many.assert_called_once()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            assert len(targets) == 2

    def test_forward_message_with_fewer_peers_than_fanout(self, mock_env_manual, mock_socket_handler,
                                                          mock_failure_detector):
        """Test forwarding when fewer peers than fanout exist."""
        env = dict(mock_env_manual)
        env['HUB_FANOUT'] = '10'  # Fanout larger than available peers

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            # Add only 3 peers
            for i in range(1, 4):
                server._ensure_peer_exists(i)

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._forward_message(msg)

            # Should forward to all 3 available peers
            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            assert len(targets) == 3

    def test_forward_message_excludes_dead_peers(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that dead peers are excluded from forwarding."""
        env = dict(mock_env_manual)
        env['HUB_FANOUT'] = '10'

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            # Add peers
            for i in range(1, 5):
                server._ensure_peer_exists(i)

            # Mark some peers as dead
            server._state.set_peer_status(2, 'dead')
            server._state.set_peer_status(4, 'dead')

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._forward_message(msg)

            # Should only forward to alive/suspected peers (1 and 3)
            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            assert len(targets) == 2
            target_indices = [t.port - 9000 for t in targets]  # Extract indices from ports
            assert 2 not in target_indices
            assert 4 not in target_indices

    def test_forward_message_excludes_self(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that self is excluded from forwarding targets."""
        env = dict(mock_env_manual)
        env['HUB_FANOUT'] = '10'

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            # Add some peers
            for i in range(1, 4):
                server._ensure_peer_exists(i)

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._forward_message(msg)

            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            # Self (hub-0, port 9000) should not be in targets
            target_ports = [t.port for t in targets]
            assert 9000 not in target_ports

    def test_forward_message_updates_forwarded_by(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _forward_message updates forwarded_by field."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add a peer
            server._ensure_peer_exists(1)

            msg = create_gossip_message(
                nonce=1,
                origin=2,  # Original sender is peer 2
                forwarded_by=2,
                event_type=pb.PEER_ALIVE,
                alive_peer=2
            )

            server._forward_message(msg)

            # Message should now have forwarded_by = 0 (this server)
            call_args = mock_socket_handler.send_to_many.call_args[0]
            forwarded_msg = call_args[0]

            assert forwarded_msg.forwarded_by == 0

    def test_forward_message_with_no_peers(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test forwarding when no other peers exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # No peers added (except self)
            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._forward_message(msg)

            # Should call send_to_many with empty list
            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            assert len(targets) == 0

class TestNonceGeneration:
    """Tests for nonce generation."""

    def test_get_next_nonce_starts_at_one(self, mock_env_manual, mock_socket_handler, mock_failure_detector, mock_peer_discovery_monitor):
        """Test that first nonce is 1."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            nonce = server._get_next_nonce()

            assert nonce == 1

    def test_get_next_nonce_increments(self, mock_env_manual, mock_socket_handler, mock_failure_detector, mock_peer_discovery_monitor):
        """Test that nonces increment sequentially."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            nonces = [server._get_next_nonce() for _ in range(10)]

            assert nonces == list(range(1, 11))

    def test_get_next_nonce_thread_safety(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test nonce generation is thread-safe (no duplicates)."""
        import threading

        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            nonces = []
            lock = threading.Lock()

            def get_nonces():
                for _ in range(100):
                    n = server._get_next_nonce()
                    with lock:
                        nonces.append(n)

            threads = [threading.Thread(target=get_nonces) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should have 500 unique nonces (5 threads * 100 each)
            assert len(nonces) == 500
            assert len(set(nonces)) == 500  # All unique

class TestMessageSending:
    """Tests for message sending methods."""

    def test_send_messages_and_forward_validates_origin(self, mock_env_manual, mock_socket_handler,
                                                        mock_failure_detector):
        """Test that _send_messages_and_forward validates message origin."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create message with wrong origin
            msg = create_gossip_message(
                nonce=1,
                origin=99,  # Wrong origin (not self)
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            with pytest.raises(ValueError):
                server._send_messages_and_forward(msg)

    def test_send_messages_and_forward_updates_heartbeat(self, mock_env_manual, mock_socket_handler,
                                                         mock_failure_detector):
        """Test that _send_messages_and_forward updates heartbeat."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = create_gossip_message(
                nonce=42,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._send_messages_and_forward(msg)

            # Heartbeat should be updated
            self_peer = server._state.get_peer(0)
            assert self_peer.heartbeat == 42

    def test_send_messages_and_forward_calls_forward(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _send_messages_and_forward calls _forward_message."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add a peer to forward to
            server._ensure_peer_exists(1)

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._send_messages_and_forward(msg)

            # Should have called send_to_many (via _forward_message)
            mock_socket_handler.send_to_many.assert_called_once()

    def test_send_messages_specific_destination_validates_origin(self, mock_env_manual, mock_socket_handler,
                                                                 mock_failure_detector):
        """Test that _send_messages_specific_destination validates origin."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = create_gossip_message(
                nonce=1,
                origin=5,  # Wrong origin
                forwarded_by=0,
                event_type=pb.PEER_JOIN,
                joining_peer=0
            )

            ref = ServerReference("127.0.0.1", 9001)

            with pytest.raises(ValueError):
                server._send_messages_specific_destination(msg, ref)

    def test_send_messages_specific_destination_sends_to_target(self, mock_env_manual, mock_socket_handler,
                                                                mock_failure_detector):
        """Test that _send_messages_specific_destination sends to specific target."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_JOIN,
                joining_peer=0
            )

            ref = ServerReference("192.168.1.100", 8888)

            server._send_messages_specific_destination(msg, ref)

            # Should call socket_handler.send with the specific reference
            mock_socket_handler.send.assert_called_once()
            call_args = mock_socket_handler.send.call_args[0]
            sent_msg = call_args[0]
            sent_ref = call_args[1]

            assert sent_ref.address == "192.168.1.100"
            assert sent_ref.port == 8888

class TestMessageProcessing:
    """Tests for message processing and handling."""

    def test_on_gossip_message_creates_missing_peers(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _on_gossip_message creates peers if they don't exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Message from unknown peer 5, forwarded by unknown peer 3
            msg = create_gossip_message(
                nonce=1,
                origin=5,
                forwarded_by=3,
                event_type=pb.PEER_ALIVE,
                alive_peer=5
            )

            sender = ServerReference("127.0.0.1", 9003)

            server._on_gossip_message(msg, sender)

            # Both peers should now exist
            assert server._state.get_peer(5) is not None
            assert server._state.get_peer(3) is not None

    def test_on_gossip_message_marks_forwarder_alive(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _on_gossip_message marks forwarder as alive."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Pre-create peer 2
            server._ensure_peer_exists(2)
            server._state.set_peer_status(2, 'suspected')

            msg = create_gossip_message(
                nonce=1,
                origin=2,
                forwarded_by=2,
                event_type=pb.PEER_ALIVE,
                alive_peer=2
            )

            sender = ServerReference("127.0.0.1", 9002)

            server._on_gossip_message(msg, sender)

            # Peer 2 should be marked alive
            peer = server._state.get_peer(2)
            assert peer.status == 'alive'

    def test_on_gossip_message_ignores_duplicate_nonce(self, mock_env_manual, mock_socket_handler,
                                                       mock_failure_detector):
        """Test that duplicate messages (same nonce) are ignored."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            server._ensure_peer_exists(1)

            msg = create_gossip_message(
                nonce=10,
                origin=1,
                forwarded_by=1,
                event_type=pb.PEER_ALIVE,
                alive_peer=1
            )

            sender = ServerReference("127.0.0.1", 9001)

            # First message
            server._on_gossip_message(msg, sender)
            first_call_count = mock_socket_handler.send_to_many.call_count

            # Second message with same nonce
            server._on_gossip_message(msg, sender)
            second_call_count = mock_socket_handler.send_to_many.call_count

            # Should not forward duplicate
            assert second_call_count == first_call_count

    def test_on_gossip_message_forwards_new_messages(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that new messages are forwarded."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peers to forward to
            server._ensure_peer_exists(1)
            server._ensure_peer_exists(2)

            msg = create_gossip_message(
                nonce=1,
                origin=1,
                forwarded_by=1,
                event_type=pb.PEER_ALIVE,
                alive_peer=1
            )

            sender = ServerReference("127.0.0.1", 9001)

            server._on_gossip_message(msg, sender)

            # Should forward to other peers
            mock_socket_handler.send_to_many.assert_called()


class TestMessageHandlers:
    """Tests for individual message type handlers."""

    def test_handle_peer_join_creates_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_JOIN handler creates the peer."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            payload = pb.PeerJoinPayload(joining_peer=5)
            server._handle_peer_join(payload)

            # Peer 5 should exist
            assert server._state.get_peer(5) is not None

    def test_handle_peer_leave_marks_peer_dead(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_LEAVE handler marks peer as dead."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer first
            server._ensure_peer_exists(3)

            payload = pb.PeerLeavePayload(leaving_peer=3)
            server._handle_peer_leave(payload)

            # Peer should be dead
            peer = server._state.get_peer(3)
            assert peer.status == 'dead'

    def test_handle_peer_alive_marks_peer_alive(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_ALIVE handler marks peer as explicitly alive."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer and mark as suspected
            server._ensure_peer_exists(2)
            server._state.set_peer_status(2, 'suspected')
            old_last_seen = server._state.get_peer(2).last_seen

            import time
            time.sleep(0.01)  # Ensure time difference

            payload = pb.PeerAlivePayload(alive_peer=2)
            server._handle_peer_alive(payload)

            # Peer should be alive with updated last_seen
            peer = server._state.get_peer(2)
            assert peer.status == 'alive'
            assert peer.last_seen > old_last_seen

    def test_handle_peer_suspicious_self_broadcasts_alive(self, mock_env_manual, mock_socket_handler,
                                                          mock_failure_detector):
        """Test that PEER_SUSPICIOUS for self triggers alive broadcast."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add a peer to send to
            server._ensure_peer_exists(1)

            # Someone thinks we (hub-0) are suspicious
            payload = pb.PeerSuspiciousPayload(suspicious_peer=0)

            mock_socket_handler.send_to_many.reset_mock()
            server._handle_peer_suspicious(payload)

            # Should broadcast PEER_ALIVE
            mock_socket_handler.send_to_many.assert_called()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            sent_msg = call_args[0]

            assert sent_msg.event_type == pb.PEER_ALIVE
            assert sent_msg.peer_alive.alive_peer == 0

    def test_handle_peer_suspicious_other_ignores(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_SUSPICIOUS for other peer is ignored."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Someone thinks peer 5 is suspicious (not us)
            payload = pb.PeerSuspiciousPayload(suspicious_peer=5)

            mock_socket_handler.send_to_many.reset_mock()
            server._handle_peer_suspicious(payload)

            # Should not broadcast anything
            mock_socket_handler.send_to_many.assert_not_called()

    def test_handle_peer_dead_removes_suspected_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_DEAD removes peer if it was suspected."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer and mark as suspected
            server._ensure_peer_exists(4)
            server._state.set_peer_status(4, 'suspected')

            payload = pb.PeerDeadPayload(dead_peer=4)
            server._handle_peer_dead(payload)

            # Peer should be marked dead
            peer = server._state.get_peer(4)
            assert peer.status == 'dead'

    def test_handle_peer_dead_ignores_alive_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that PEER_DEAD for alive peer doesn't remove it."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer that is alive
            server._ensure_peer_exists(4)
            server._state.set_peer_status(4, 'alive')

            payload = pb.PeerDeadPayload(dead_peer=4)
            server._handle_peer_dead(payload)

            # Peer should still exist (not removed)
            peer = server._state.get_peer(4)
            assert peer is not None
            # Status might be 'alive' or unchanged - the handler only removes if suspected


class TestFailureDetectorCallbacks:
    """Tests for failure detector callback methods."""

    def test_on_peer_suspicious_broadcasts_message(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _on_peer_suspicious broadcasts PEER_SUSPICIOUS message."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peers to forward to
            server._ensure_peer_exists(1)

            mock_socket_handler.send_to_many.reset_mock()
            server._on_peer_suspicious(5)

            # Should broadcast PEER_SUSPICIOUS message
            mock_socket_handler.send_to_many.assert_called()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            sent_msg = call_args[0]

            assert sent_msg.event_type == pb.PEER_SUSPICIOUS
            assert sent_msg.peer_suspicious.suspicious_peer == 5
            assert sent_msg.origin == 0

    def test_on_peer_dead_broadcasts_and_removes(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that _on_peer_dead broadcasts message and removes peer."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create the peer
            server._ensure_peer_exists(3)
            server._ensure_peer_exists(1)  # For forwarding

            mock_socket_handler.send_to_many.reset_mock()
            server._on_peer_dead(3)

            # Should broadcast PEER_DEAD message
            mock_socket_handler.send_to_many.assert_called()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            sent_msg = call_args[0]

            assert sent_msg.event_type == pb.PEER_DEAD
            assert sent_msg.peer_dead.dead_peer == 3

            # Peer should be marked dead
            peer = server._state.get_peer(3)
            assert peer.status == 'dead'

    def test_broadcast_peer_alive_sends_correct_message(self, mock_env_manual, mock_socket_handler,
                                                        mock_failure_detector):
        """Test that _broadcast_peer_alive sends correct message."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peer to forward to
            server._ensure_peer_exists(1)

            mock_socket_handler.send_to_many.reset_mock()
            server._broadcast_peer_alive()

            # Should send PEER_ALIVE for self
            mock_socket_handler.send_to_many.assert_called()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            sent_msg = call_args[0]

            assert sent_msg.event_type == pb.PEER_ALIVE
            assert sent_msg.peer_alive.alive_peer == 0
            assert sent_msg.origin == 0


class TestStopCleanup:
    """Tests for stop() and cleanup."""

    def test_stop_sends_leave_message(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that stop() sends PEER_LEAVE message."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peer to send to
            server._ensure_peer_exists(1)

            mock_socket_handler.send_to_many.reset_mock()
            server.stop()

            # Should send PEER_LEAVE message
            mock_socket_handler.send_to_many.assert_called()
            call_args = mock_socket_handler.send_to_many.call_args[0]
            sent_msg = call_args[0]

            assert sent_msg.event_type == pb.PEER_LEAVE
            assert sent_msg.peer_leave.leaving_peer == 0

    def test_stop_closes_socket_handler(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that stop() calls socket_handler.stop()."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            server.stop()

            mock_socket_handler.stop.assert_called_once()

    def test_stop_can_be_called_multiple_times(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that stop() can be called multiple times without error."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            server.stop()
            server.stop()
            server.stop()

            # Should not raise any errors
            assert mock_socket_handler.stop.call_count >= 1

class TestErrorHandlingAndRobustness:
    """Tests for error handling, edge cases, and robustness."""

    def test_on_gossip_message_with_socket_exception(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling when socket_handler.send_to_many raises exception."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peer to forward to
            server._ensure_peer_exists(1)

            # Make socket handler raise exception
            mock_socket_handler.send_to_many.side_effect = OSError("Network unreachable")

            msg = create_gossip_message(
                nonce=1,
                origin=1,
                forwarded_by=1,
                event_type=pb.PEER_ALIVE,
                alive_peer=1
            )

            sender = ServerReference("127.0.0.1", 9001)

            # Should handle exception gracefully (or raise, depending on implementation)
            with pytest.raises(OSError):
                server._on_gossip_message(msg, sender)

    def test_state_get_peer_raises_exception(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling when HubState.get_peer raises unexpected exception."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Mock state to raise exception
            with patch.object(server._state, 'get_peer', side_effect=RuntimeError("State corrupted")):
                # Should raise or handle gracefully
                with pytest.raises(RuntimeError):
                    server._ensure_peer_exists(5)

    def test_failure_detector_callback_exception_in_on_peer_suspected(
            self, mock_env_manual, mock_socket_handler, mock_failure_detector
    ):
        """Test that exception in failure detector callback doesn't crash server."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Mock socket handler to raise exception
            mock_socket_handler.send_to_many.side_effect = RuntimeError("Failed to send")

            # This should raise (or be caught, depending on implementation)
            with pytest.raises(RuntimeError):
                server._on_peer_suspicious(3)

    def test_forward_message_with_empty_peer_list_after_filtering(
            self, mock_env_manual, mock_socket_handler, mock_failure_detector
    ):
        """Test forwarding when all peers are filtered out (all dead)."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peers but mark them all as dead
            for i in range(1, 5):
                server._ensure_peer_exists(i)
                server._state.set_peer_status(i, 'dead')

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            # Should handle empty list gracefully
            server._forward_message(msg)

            # Should call send_to_many with empty list
            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]
            assert len(targets) == 0

    def test_concurrent_message_processing(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test concurrent processing of multiple messages."""
        import threading

        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add peer to forward to
            server._ensure_peer_exists(2)

            errors = []

            def process_message(peer_id):
                try:
                    msg = create_gossip_message(
                        nonce=peer_id,  # Different nonce for each
                        origin=peer_id,
                        forwarded_by=peer_id,
                        event_type=pb.PEER_JOIN,
                        joining_peer=peer_id
                    )
                    sender = ServerReference("127.0.0.1", 9000 + peer_id)
                    server._on_gossip_message(msg, sender)
                except Exception as e:
                    errors.append(e)

            # Process 10 messages concurrently
            threads = [threading.Thread(target=process_message, args=(i,)) for i in range(10, 20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should not have any errors
            assert len(errors) == 0

            # All peers should exist
            for i in range(10, 20):
                assert server._state.get_peer(i) is not None

    def test_concurrent_nonce_generation_no_duplicates(self, mock_env_manual, mock_socket_handler,
                                                       mock_failure_detector):
        """Test that concurrent nonce generation never produces duplicates."""
        import threading

        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            nonces = []
            lock = threading.Lock()

            def generate_nonces():
                for _ in range(1000):
                    n = server._get_next_nonce()
                    with lock:
                        nonces.append(n)

            threads = [threading.Thread(target=generate_nonces) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should have 10000 unique nonces
            assert len(nonces) == 10000
            assert len(set(nonces)) == 10000, "Found duplicate nonces!"

    def test_state_add_peer_during_forwarding(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test adding peers while forwarding is happening."""
        import threading

        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Add initial peer
            server._ensure_peer_exists(1)

            stop_flag = threading.Event()
            errors = []

            def forward_messages():
                try:
                    while not stop_flag.is_set():
                        msg = create_gossip_message(
                            nonce=server._get_next_nonce(),
                            origin=0,
                            forwarded_by=0,
                            event_type=pb.PEER_ALIVE,
                            alive_peer=0
                        )
                        server._forward_message(msg)
                except Exception as e:
                    errors.append(e)

            def add_peers():
                try:
                    for i in range(10, 20):
                        server._ensure_peer_exists(i)
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

            forward_thread = threading.Thread(target=forward_messages)
            add_thread = threading.Thread(target=add_peers)

            forward_thread.start()
            add_thread.start()

            add_thread.join()
            stop_flag.set()
            forward_thread.join(timeout=1.0)

            # Should not have errors
            assert len(errors) == 0

    def test_handle_peer_leave_nonexistent_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling PEER_LEAVE for a peer that doesn't exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Peer 99 doesn't exist
            payload = pb.PeerLeavePayload(leaving_peer=99)

            # Should raise ValueError (from HubState.remove_peer)
            with pytest.raises(ValueError):
                server._handle_peer_leave(payload)

    def test_handle_peer_alive_nonexistent_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling PEER_ALIVE for a peer that doesn't exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Peer 99 doesn't exist
            payload = pb.PeerAlivePayload(alive_peer=99)

            # Should handle gracefully (mark_peer_explicitly_alive checks for None)
            server._handle_peer_alive(payload)

            # Peer still shouldn't exist (not auto-created)
            assert server._state.get_peer(99) is None

    def test_handle_peer_dead_nonexistent_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling PEER_DEAD for a peer that doesn't exist."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Peer 99 doesn't exist
            payload = pb.PeerDeadPayload(dead_peer=99)

            # Should handle gracefully (get_peer returns None)
            server._handle_peer_dead(payload)

    @pytest.mark.parametrize("invalid_nonce", [-1, -100, -999999])
    def test_message_with_negative_nonce(self, mock_env_manual, mock_socket_handler, mock_failure_detector,
                                         invalid_nonce):
        """Test handling message with negative nonce."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = create_gossip_message(
                nonce=invalid_nonce,
                origin=1,
                forwarded_by=1,
                event_type=pb.PEER_ALIVE,
                alive_peer=1
            )

            sender = ServerReference("127.0.0.1", 9001)

            # Should process (nonce can be any int64)
            server._on_gossip_message(msg, sender)

            # Peer should exist
            assert server._state.get_peer(1) is not None

    def test_message_with_very_large_nonce(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling message with very large nonce."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            huge_nonce = 2 ** 62  # Very large but valid int64

            msg = create_gossip_message(
                nonce=huge_nonce,
                origin=1,
                forwarded_by=1,
                event_type=pb.PEER_ALIVE,
                alive_peer=1
            )

            sender = ServerReference("127.0.0.1", 9001)

            server._on_gossip_message(msg, sender)

            # Should update heartbeat with large value
            peer = server._state.get_peer(1)
            assert peer.heartbeat == huge_nonce

    @pytest.mark.parametrize("invalid_peer_index", [-1, -10, -999])
    def test_ensure_peer_exists_negative_index(self, mock_env_manual, mock_socket_handler, mock_failure_detector,
                                               invalid_peer_index):
        """Test _ensure_peer_exists with negative peer index."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Should raise ValueError (HubPeer doesn't accept negative index)
            with pytest.raises(ValueError, match="Required peer cannot be negative"):
                server._ensure_peer_exists(invalid_peer_index)

    def test_forward_message_with_suspected_peers(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test that suspected peers are included in forwarding."""
        env = dict(mock_env_manual)
        env['HUB_FANOUT'] = '10'

        with patch.dict(os.environ, env):
            server = HubServer(discovery_mode='manual')

            # Add peers with different statuses
            for i in range(1, 4):
                server._ensure_peer_exists(i)

            server._state.set_peer_status(1, 'alive')
            server._state.set_peer_status(2, 'suspected')  # Should be included
            server._state.set_peer_status(3, 'dead')  # Should be excluded

            msg = create_gossip_message(
                nonce=1,
                origin=0,
                forwarded_by=0,
                event_type=pb.PEER_ALIVE,
                alive_peer=0
            )

            server._forward_message(msg)

            call_args = mock_socket_handler.send_to_many.call_args[0]
            targets = call_args[1]

            # Should forward to 2 peers (alive + suspected, not dead)
            assert len(targets) == 2

    def test_multiple_peer_join_same_peer(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling multiple PEER_JOIN messages for same peer."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg1 = create_gossip_message(
                nonce=1,
                origin=5,
                forwarded_by=5,
                event_type=pb.PEER_JOIN,
                joining_peer=5
            )

            msg2 = create_gossip_message(
                nonce=2,
                origin=5,
                forwarded_by=5,
                event_type=pb.PEER_JOIN,
                joining_peer=5
            )

            sender = ServerReference("127.0.0.1", 9005)

            server._on_gossip_message(msg1, sender)
            server._on_gossip_message(msg2, sender)

            # Should only have one peer 5
            peer = server._state.get_peer(5)
            assert peer is not None
            assert peer.heartbeat == 2  # Updated to latest nonce

    def test_peer_leave_then_rejoin(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test peer leaving and then rejoining."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Peer joins
            join_msg = create_gossip_message(
                nonce=1,
                origin=3,
                forwarded_by=3,
                event_type=pb.PEER_JOIN,
                joining_peer=3
            )
            sender = ServerReference("127.0.0.1", 9003)
            server._on_gossip_message(join_msg, sender)

            # Peer leaves
            leave_msg = create_gossip_message(
                nonce=2,
                origin=3,
                forwarded_by=3,
                event_type=pb.PEER_LEAVE,
                leaving_peer=3
            )
            server._on_gossip_message(leave_msg, sender)

            # Peer should be dead
            assert server._state.get_peer(3).status == 'dead'

            # Peer rejoins with higher nonce
            rejoin_msg = create_gossip_message(
                nonce=3,
                origin=3,
                forwarded_by=3,
                event_type=pb.PEER_JOIN,
                joining_peer=3
            )
            server._on_gossip_message(rejoin_msg, sender)

            # Peer should be alive again
            peer = server._state.get_peer(3)
            assert peer.status == 'alive'

    def test_on_peer_dead_callback_removes_and_broadcasts(self, mock_env_manual, mock_socket_handler,
                                                          mock_failure_detector):
        """Test that _on_peer_dead both broadcasts and removes peer."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Create peer
            server._ensure_peer_exists(7)
            server._ensure_peer_exists(1)  # For forwarding

            initial_status = server._state.get_peer(7).status

            mock_socket_handler.send_to_many.reset_mock()
            server._on_peer_dead(7)

            # Should broadcast message
            mock_socket_handler.send_to_many.assert_called_once()

            # Peer should be marked dead
            assert server._state.get_peer(7).status == 'dead'

    def test_very_high_message_rate(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling very high message rate."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            # Process 1000 messages rapidly
            for i in range(1000):
                msg = create_gossip_message(
                    nonce=i,
                    origin=1,
                    forwarded_by=1,
                    event_type=pb.PEER_ALIVE,
                    alive_peer=1
                )
                sender = ServerReference("127.0.0.1", 9001)
                server._on_gossip_message(msg, sender)

            # Peer should have latest nonce
            peer = server._state.get_peer(1)
            assert peer.heartbeat == 999

    def test_message_from_future_timestamp(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling message with timestamp in the future."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = pb.GossipMessage(
                nonce=1,
                origin=1,
                forwarded_by=1,
                timestamp=time.time() + 1000000,  # Far future
                event_type=pb.PEER_ALIVE
            )
            msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=1))

            sender = ServerReference("127.0.0.1", 9001)

            # Should process normally (timestamp not validated)
            server._on_gossip_message(msg, sender)

            assert server._state.get_peer(1) is not None

    def test_message_from_past_timestamp(self, mock_env_manual, mock_socket_handler, mock_failure_detector):
        """Test handling message with very old timestamp."""
        with patch.dict(os.environ, mock_env_manual):
            server = HubServer(discovery_mode='manual')

            msg = pb.GossipMessage(
                nonce=1,
                origin=1,
                forwarded_by=1,
                timestamp=0.0,  # Unix epoch
                event_type=pb.PEER_ALIVE
            )
            msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=1))

            sender = ServerReference("127.0.0.1", 9001)

            # Should process normally
            server._on_gossip_message(msg, sender)

            assert server._state.get_peer(1) is not None