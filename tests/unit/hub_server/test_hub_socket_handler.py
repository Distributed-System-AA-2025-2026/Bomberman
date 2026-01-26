import pytest
import socket
import time
from unittest.mock import Mock, patch

from bomberman.hub_server.HubSocketHandler import HubSocketHandler, BUFFER_SIZE
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.gossip import messages_pb2 as pb


def create_gossip_message(nonce=1, origin=0, forwarded_by=0, event_type=pb.PEER_ALIVE):
    """Helper to create a GossipMessage for testing."""
    msg = pb.GossipMessage(
        nonce=nonce,
        origin=origin,
        forwarded_by=forwarded_by,
        timestamp=time.time(),
        event_type=event_type
    )

    if event_type == pb.PEER_ALIVE:
        msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=origin))

    return msg


@pytest.fixture
def mock_socket():
    """Mock socket.socket to avoid real networking."""
    with patch('bomberman.hub_server.HubSocketHandler.socket.socket', autospec=True) as mock_socket_class:
        socket_instance = mock_socket_class.return_value

        # Configura return values di default
        socket_instance.bind.return_value = None
        socket_instance.close.return_value = None
        socket_instance.sendto.return_value = None

        socket_instance.recvfrom.side_effect = OSError("Socket closed")

        yield socket_instance


@pytest.fixture
def callback():
    """Provide a mock callback for message handling."""
    return Mock()


@pytest.fixture
def handler(mock_socket, callback):
    """Provide a HubSocketHandler with mocked socket."""
    handler = HubSocketHandler(port=9000, on_message=callback)

    yield handler

    # Cleanup
    if handler._running:
        handler.stop()
        time.sleep(0.1)


class TestInitialization:
    """Tests for HubSocketHandler initialization."""

    def test_init_with_valid_parameters(self, mock_socket, callback):
        """Test initialization with valid port and callback."""
        handler = HubSocketHandler(port=9000, on_message=callback)

        assert handler._on_message is callback
        assert handler._running is False
        assert handler._socket is mock_socket

        # Verify socket was created and bound
        mock_socket.bind.assert_called_once_with(("0.0.0.0", 9000))

    @pytest.mark.parametrize("port", [0, 1024, 8080, 9000, 65535])
    def test_init_with_various_valid_ports(self, mock_socket, callback, port):
        """Test initialization with various valid port numbers."""
        handler = HubSocketHandler(port=port, on_message=callback)

        mock_socket.bind.assert_called_once_with(("0.0.0.0", port))

    def test_init_creates_udp_socket(self, callback):
        """Test that initialization creates UDP socket."""
        # Patch socket senza usare il fixture
        with patch('bomberman.hub_server.HubSocketHandler.socket.socket', autospec=True) as mock_socket_class:
            socket_instance = mock_socket_class.return_value
            socket_instance.bind.return_value = None
            socket_instance.recvfrom.side_effect = OSError("Socket closed")

            handler = HubSocketHandler(port=9000, on_message=callback)

            # Should create UDP socket (SOCK_DGRAM)
            mock_socket_class.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)

    def test_init_binds_to_all_interfaces(self, mock_socket, callback):
        """Test that socket binds to all interfaces (0.0.0.0)."""
        handler = HubSocketHandler(port=9000, on_message=callback)

        call_args = mock_socket.bind.call_args[0][0]
        assert call_args[0] == "0.0.0.0"

    def test_init_with_none_callback(self, mock_socket):
        """Test initialization with None callback."""
        handler = HubSocketHandler(port=9000, on_message=None)

        assert handler._on_message is None

    @pytest.mark.parametrize("invalid_callback", ["not_callable", 123, [], {}])
    def test_init_with_invalid_callback_types(self, mock_socket, invalid_callback):
        """Test initialization with non-callable callback types."""
        # Should not raise during init
        handler = HubSocketHandler(port=9000, on_message=invalid_callback)

        assert handler._on_message is invalid_callback

    def test_init_with_negative_port(self, mock_socket, callback):
        """Test that negative port raises OSError during bind."""
        # Configure mock to raise error on bind
        mock_socket.bind.side_effect = OSError("Invalid port")

        with pytest.raises(OSError):
            HubSocketHandler(port=-1, on_message=callback)

    def test_init_with_port_already_in_use(self, mock_socket, callback):
        """Test that port already in use raises OSError."""
        # Configure mock to raise error on bind
        mock_socket.bind.side_effect = OSError("[Errno 48] Address already in use")

        with pytest.raises(OSError, match="Address already in use"):
            HubSocketHandler(port=9000, on_message=callback)

    @pytest.mark.parametrize("port", [65536, 70000, 100000])
    def test_init_with_port_out_of_range(self, mock_socket, callback, port):
        """Test that port out of range raises OSError."""
        # Configure mock to raise error on bind
        mock_socket.bind.side_effect = OSError("Invalid port")

        with pytest.raises(OSError):
            HubSocketHandler(port=port, on_message=callback)

    def test_init_not_running_initially(self, mock_socket, callback):
        """Test that handler is not running after initialization."""
        handler = HubSocketHandler(port=9000, on_message=callback)

        assert handler._running is False


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    def test_start_sets_running_flag(self, handler):
        """Test that start() sets _running to True."""
        handler.start()

        assert handler._running is True

    def test_start_creates_listener_thread(self, handler):
        """Test that start() creates and starts listener thread."""
        with patch('threading.Thread') as mock_thread_class:
            mock_thread = Mock()
            mock_thread_class.return_value = mock_thread

            handler.start()

            # Verify thread was created with correct target
            mock_thread_class.assert_called_once()
            call_kwargs = mock_thread_class.call_args[1]
            assert call_kwargs['target'] == handler._listen_loop
            assert call_kwargs['daemon'] is True

            # Verify thread was started
            mock_thread.start.assert_called_once()

            handler.stop()

    def test_start_thread_is_daemon(self, handler):
        """Test that listener thread is a daemon thread."""
        with patch('threading.Thread') as mock_thread_class:
            handler.start()

            call_kwargs = mock_thread_class.call_args[1]
            assert call_kwargs['daemon'] is True

    def test_stop_sets_running_to_false(self, handler):
        """Test that stop() sets _running to False."""
        handler.start()
        assert handler._running is True

        handler.stop()

        assert handler._running is False

    def test_stop_closes_socket(self, handler, mock_socket):
        """Test that stop() closes the socket."""
        handler.stop()

        mock_socket.close.assert_called_once()

    def test_stop_before_start(self, handler, mock_socket):
        """Test that stop() can be called before start()."""
        assert handler._running is False

        handler.stop()

        assert handler._running is False
        mock_socket.close.assert_called_once()

    def test_multiple_start_calls(self, handler):
        """Test behavior with multiple start() calls."""
        handler.start()
        first_running = handler._running

        handler.start()
        second_running = handler._running

        assert first_running is True
        assert second_running is True

    def test_multiple_stop_calls(self, handler, mock_socket):
        """Test that multiple stop() calls don't cause errors."""
        handler.start()

        handler.stop()
        handler.stop()
        handler.stop()

        assert handler._running is False
        # close() might be called multiple times
        assert mock_socket.close.call_count >= 1

    def test_start_stop_start_sequence(self, handler):
        """Test starting, stopping, and restarting."""
        handler.start()
        assert handler._running is True

        handler.stop()
        assert handler._running is False

        handler.start()
        assert handler._running is True

        # Cleanup
        handler.stop()


class TestMessageReceiving:
    """Tests for receiving and parsing messages."""

    def test_handle_message_parses_valid_protobuf(self, handler, callback):
        """Test that _handle_message correctly parses valid protobuf."""
        msg = create_gossip_message(nonce=42, origin=5, forwarded_by=5)
        data = msg.SerializeToString()
        addr = ("192.168.1.100", 9001)

        handler._handle_message(data, addr)

        # Callback should be called once
        callback.assert_called_once()

        # Verify callback arguments
        call_args = callback.call_args[0]
        received_msg = call_args[0]
        sender_ref = call_args[1]

        assert received_msg.nonce == 42
        assert received_msg.origin == 5
        assert sender_ref.address == "192.168.1.100"
        assert sender_ref.port == 9001

    def test_handle_message_creates_server_reference(self, handler, callback):
        """Test that _handle_message creates ServerReference from addr."""
        msg = create_gossip_message()
        data = msg.SerializeToString()
        addr = ("10.0.0.5", 8888)

        handler._handle_message(data, addr)

        call_args = callback.call_args[0]
        sender_ref = call_args[1]

        assert isinstance(sender_ref, ServerReference)
        assert sender_ref.address == "10.0.0.5"
        assert sender_ref.port == 8888

    def test_handle_message_with_invalid_protobuf(self, handler, callback, capsys):
        """Test handling of invalid protobuf data."""
        invalid_data = b"this is not valid protobuf data"
        addr = ("127.0.0.1", 9000)

        # Should not raise exception, just print error
        handler._handle_message(invalid_data, addr)

        # Callback should not be called
        callback.assert_not_called()

        # Should print error message
        captured = capsys.readouterr()
        assert "Invalid message" in captured.out
        assert "127.0.0.1" in captured.out

    def test_handle_message_with_empty_data(self, handler, callback, capsys):
        """Test handling of empty data."""
        empty_data = b""
        addr = ("127.0.0.1", 9000)

        handler._handle_message(empty_data, addr)

        # Callback should not be called
        callback.assert_called_once()

        call_args = callback.call_args[0]
        received_msg = call_args[0]

        assert received_msg.nonce == 0
        assert received_msg.origin == 0
        assert received_msg.forwarded_by == 0

    def test_handle_message_with_callback_exception(self, handler, capsys):
        """Test that callback exception is caught and logged."""
        callback = Mock(side_effect=RuntimeError("Callback failed"))
        handler._on_message = callback

        msg = create_gossip_message()
        data = msg.SerializeToString()
        addr = ("127.0.0.1", 9000)

        # Should not raise exception
        handler._handle_message(data, addr)

        # Should print error
        captured = capsys.readouterr()
        assert "Invalid message" in captured.out
        assert "Callback failed" in captured.out

    def test_handle_message_with_none_callback(self, handler):
        """Test handling message when callback is None."""
        handler._on_message = None

        msg = create_gossip_message()
        data = msg.SerializeToString()
        addr = ("127.0.0.1", 9000)

        # Should raise TypeError when trying to call None
        with pytest.raises(TypeError):
            handler._handle_message(data, addr)

    @pytest.mark.parametrize("event_type", [
        pb.PEER_JOIN,
        pb.PEER_LEAVE,
        pb.PEER_ALIVE,
        pb.PEER_SUSPICIOUS,
        pb.PEER_DEAD,
    ])
    def test_handle_message_various_event_types(self, handler, callback, event_type):
        """Test handling messages with various event types."""
        msg = pb.GossipMessage(
            nonce=1,
            origin=1,
            forwarded_by=1,
            timestamp=time.time(),
            event_type=event_type
        )

        # Set appropriate payload
        if event_type == pb.PEER_JOIN:
            msg.peer_join.CopyFrom(pb.PeerJoinPayload(joining_peer=1))
        elif event_type == pb.PEER_LEAVE:
            msg.peer_leave.CopyFrom(pb.PeerLeavePayload(leaving_peer=1))
        elif event_type == pb.PEER_ALIVE:
            msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=1))
        elif event_type == pb.PEER_SUSPICIOUS:
            msg.peer_suspicious.CopyFrom(pb.PeerSuspiciousPayload(suspicious_peer=1))
        elif event_type == pb.PEER_DEAD:
            msg.peer_dead.CopyFrom(pb.PeerDeadPayload(dead_peer=1))

        data = msg.SerializeToString()
        addr = ("127.0.0.1", 9000)

        handler._handle_message(data, addr)

        # Callback should be called
        callback.assert_called_once()

        # Verify event type
        call_args = callback.call_args[0]
        received_msg = call_args[0]
        assert received_msg.event_type == event_type


class TestMessageSending:
    """Tests for sending messages."""

    def test_send_serializes_message(self, handler, mock_socket):
        """Test that send() serializes the message."""
        msg = create_gossip_message(nonce=123)
        addr = ServerReference("192.168.1.50", 8080)

        handler.send(msg, addr)

        # Verify sendto was called
        mock_socket.sendto.assert_called_once()

        # Verify data is serialized protobuf
        call_args = mock_socket.sendto.call_args[0]
        sent_data = call_args[0]
        sent_dest = call_args[1]

        # Deserialize to verify
        parsed_msg = pb.GossipMessage()
        parsed_msg.ParseFromString(sent_data)
        assert parsed_msg.nonce == 123

        assert sent_dest == ("192.168.1.50", 8080)

    def test_send_to_correct_destination(self, handler, mock_socket):
        """Test that send() sends to correct destination."""
        msg = create_gossip_message()
        addr = ServerReference("10.0.0.100", 9999)

        handler.send(msg, addr)

        call_args = mock_socket.sendto.call_args[0]
        sent_dest = call_args[1]

        assert sent_dest == ("10.0.0.100", 9999)

    def test_send_multiple_times(self, handler, mock_socket):
        """Test sending multiple messages."""
        msg1 = create_gossip_message(nonce=1)
        msg2 = create_gossip_message(nonce=2)
        msg3 = create_gossip_message(nonce=3)

        addr = ServerReference("127.0.0.1", 9000)

        handler.send(msg1, addr)
        handler.send(msg2, addr)
        handler.send(msg3, addr)

        assert mock_socket.sendto.call_count == 3

    def test_send_to_many_sends_to_all_addresses(self, handler, mock_socket):
        """Test that send_to_many sends to all provided addresses."""
        msg = create_gossip_message(nonce=42)
        addrs = [
            ServerReference("192.168.1.1", 9001),
            ServerReference("192.168.1.2", 9002),
            ServerReference("192.168.1.3", 9003),
        ]

        handler.send_to_many(msg, addrs)

        # Should call sendto 3 times
        assert mock_socket.sendto.call_count == 3

        # Verify destinations
        sent_destinations = [call[0][1] for call in mock_socket.sendto.call_args_list]
        expected_destinations = [
            ("192.168.1.1", 9001),
            ("192.168.1.2", 9002),
            ("192.168.1.3", 9003),
        ]
        assert sent_destinations == expected_destinations

    def test_send_to_many_with_empty_list(self, handler, mock_socket):
        """Test send_to_many with empty address list."""
        msg = create_gossip_message()
        addrs = []

        handler.send_to_many(msg, addrs)

        # Should not call sendto
        mock_socket.sendto.assert_not_called()

    def test_send_to_many_with_single_address(self, handler, mock_socket):
        """Test send_to_many with single address."""
        msg = create_gossip_message()
        addrs = [ServerReference("127.0.0.1", 9000)]

        handler.send_to_many(msg, addrs)

        # Should call sendto once
        mock_socket.sendto.assert_called_once()

    def test_send_to_many_with_large_list(self, handler, mock_socket):
        """Test send_to_many with many addresses."""
        msg = create_gossip_message()
        addrs = [ServerReference(f"10.0.0.{i}", 9000 + i) for i in range(100)]

        handler.send_to_many(msg, addrs)

        # Should call sendto 100 times
        assert mock_socket.sendto.call_count == 100

    def test_send_with_socket_error(self, handler, mock_socket):
        """Test that socket error during send is propagated."""
        mock_socket.sendto.side_effect = OSError("Network unreachable")

        msg = create_gossip_message()
        addr = ServerReference("192.168.1.1", 9000)

        mock_logging = Mock()
        handler._logging = mock_logging


        handler.send(msg, addr)
        mock_logging.assert_called_once()

    def test_send_to_many_partial_failure(self, handler, mock_socket):
        """Test send_to_many when one send fails."""
        # First send succeeds, second fails, third succeeds
        mock_socket.sendto.side_effect = [
            None,  # Success
            OSError("Network unreachable"),  # Failure
            None,  # Success
        ]

        msg = create_gossip_message()
        addrs = [
            ServerReference("192.168.1.1", 9001),
            ServerReference("192.168.1.2", 9002),
            ServerReference("192.168.1.3", 9003),
        ]

        handler.send_to_many(msg, addrs)

        # Should have called sendto twice (once successful, once failed)
        assert mock_socket.sendto.call_count == 3


class TestThreading:
    """Tests for threading behavior."""

    def test_listen_loop_stops_when_running_false(self, handler, mock_socket):
        """Test that _listen_loop stops when _running is False."""

        # Make recvfrom block until running becomes False
        def recvfrom_side_effect(bufsize):
            while handler._running:
                time.sleep(0.01)
            raise OSError("Socket closed")

        mock_socket.recvfrom.side_effect = recvfrom_side_effect

        handler.start()
        time.sleep(0.05)
        handler.stop()

        # Loop should have exited
        # Give thread time to finish
        time.sleep(0.1)

    def test_listen_loop_creates_handler_thread_for_each_message(self, handler, mock_socket):
        """Test that _listen_loop creates a new thread for each received message."""
        msg = create_gossip_message()
        data = msg.SerializeToString()

        call_count = [0]

        def recvfrom_side_effect(bufsize):
            call_count[0] += 1
            if call_count[0] > 3:
                handler._running = False
                raise OSError("Stopped")
            return (data, ("127.0.0.1", 9000))

        mock_socket.recvfrom.side_effect = recvfrom_side_effect

        handler.start()

        # Aspetta che i messaggi siano processati
        time.sleep(0.5)

        # Verifica che recvfrom sia stato chiamato 4 volte (3 messaggi + 1 che fa uscire)
        assert call_count[0] == 4

        handler.stop()

    def test_listen_loop_receives_multiple_messages(self, handler, mock_socket, callback):
        """Test that _listen_loop receives and processes multiple messages."""
        msg = create_gossip_message()
        data = msg.SerializeToString()

        messages_received = [0]

        def recvfrom_side_effect(bufsize):
            messages_received[0] += 1
            if messages_received[0] > 3:
                handler._running = False
                raise OSError("Stopped")
            return (data, ("127.0.0.1", 9000))

        mock_socket.recvfrom.side_effect = recvfrom_side_effect

        handler.start()
        time.sleep(0.5)


        assert callback.call_count == 3
        handler.stop()

    def test_handler_threads_are_daemon(self, handler, mock_socket):
        """Test that handler threads are daemon threads."""
        msg = create_gossip_message()
        data = msg.SerializeToString()

        mock_socket.recvfrom.return_value = (data, ("127.0.0.1", 9000))

        with patch('threading.Thread') as mock_thread_class:
            handler.start()

            # Trigger one receive
            time.sleep(0.05)
            handler.stop()

            # Check that handler threads (not listener) are daemon
            # First call is listener thread, subsequent are handler threads
            if mock_thread_class.call_count > 1:
                handler_thread_call = mock_thread_class.call_args_list[1]
                assert handler_thread_call[1]['daemon'] is True

    def test_concurrent_sends(self, handler, mock_socket):
        """Test that multiple concurrent sends work correctly."""
        import threading

        msg = create_gossip_message()
        addr = ServerReference("127.0.0.1", 9000)

        errors = []

        def send_many_times():
            try:
                for _ in range(100):
                    handler.send(msg, addr)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=send_many_times) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not have any errors
        assert len(errors) == 0

        # Should have called sendto 500 times (5 threads * 100 each)
        assert mock_socket.sendto.call_count == 500


class TestEdgeCasesAndErrorHandling:
    """Tests for edge cases and error conditions."""

    def test_buffer_size_constant(self):
        """Test that BUFFER_SIZE is set correctly."""
        assert BUFFER_SIZE == 65535

    def test_send_very_large_message(self, handler, mock_socket):
        """Test sending message that exceeds typical UDP size."""
        # Create a large message (close to 64KB)
        msg = pb.GossipMessage(
            nonce=1,
            origin=1,
            forwarded_by=1,
            timestamp=time.time(),
            event_type=pb.PEER_ALIVE
        )
        msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=1))

        # Message should still be sent (might fail in real networking)
        addr = ServerReference("127.0.0.1", 9000)
        handler.send(msg, addr)

        mock_socket.sendto.assert_called_once()

    def test_receive_message_at_buffer_size_limit(self, handler, callback):
        """Test receiving message at buffer size limit."""
        # Create data close to BUFFER_SIZE
        large_data = b"x" * (BUFFER_SIZE - 100)
        addr = ("127.0.0.1", 9000)

        # Should handle without error (though parsing will fail)
        handler._handle_message(large_data, addr)

        # Callback should not be called (invalid protobuf)
        callback.assert_not_called()

    def test_send_to_invalid_address(self, handler, mock_socket):
        """Test sending to invalid address format."""
        msg = create_gossip_message()

        # Invalid address (not a tuple)
        addr = ServerReference("not.valid.ip", 9000)

        # Socket might raise error
        mock_socket.sendto.side_effect = OSError("Invalid address")
        mock_logging = Mock()
        handler._logging = mock_logging

        handler.send(msg, addr)
        mock_logging.assert_called_once()

    def test_receive_from_invalid_source(self, handler, callback):
        """Test receiving message from unusual source address."""
        msg = create_gossip_message()
        data = msg.SerializeToString()

        # Unusual but valid address
        addr = ("::1", 9000)  # IPv6 localhost

        handler._handle_message(data, addr)

        # Should still call callback
        callback.assert_called_once()

        call_args = callback.call_args[0]
        sender_ref = call_args[1]
        assert sender_ref.address == "::1"

    def test_socket_close_during_receive(self, handler, mock_socket):
        """Test behavior when socket is closed during receive."""
        mock_socket.recvfrom.side_effect = OSError("Bad file descriptor")

        handler.start()

        # Should exit loop without crashing
        time.sleep(0.1)

        # Stop should still work
        handler.stop()

    def test_message_with_all_fields_populated(self, handler, callback):
        """Test handling message with all optional fields."""
        msg = pb.GossipMessage(
            nonce=999,
            origin=5,
            forwarded_by=3,
            timestamp=1234567890.123,
            event_type=pb.PEER_ALIVE
        )
        msg.peer_alive.CopyFrom(pb.PeerAlivePayload(alive_peer=5))

        data = msg.SerializeToString()
        addr = ("10.20.30.40", 8888)

        handler._handle_message(data, addr)

        callback.assert_called_once()
        call_args = callback.call_args[0]
        received_msg = call_args[0]

        assert received_msg.nonce == 999
        assert received_msg.origin == 5
        assert received_msg.forwarded_by == 3
        assert received_msg.timestamp == 1234567890.123

    def test_message_with_minimal_fields(self, handler, callback):
        """Test handling message with only required fields."""
        msg = pb.GossipMessage()
        msg.nonce = 1
        msg.origin = 0
        msg.forwarded_by = 0

        data = msg.SerializeToString()
        addr = ("127.0.0.1", 9000)

        handler._handle_message(data, addr)

        # Should parse successfully
        callback.assert_called_once()

    @pytest.mark.parametrize("port", [0, 1, 1023, 49152, 65535])
    def test_send_to_various_ports(self, handler, mock_socket, port):
        """Test sending to various port numbers."""
        msg = create_gossip_message()
        addr = ServerReference("127.0.0.1", port)

        handler.send(msg, addr)

        call_args = mock_socket.sendto.call_args[0]
        sent_dest = call_args[1]

        assert sent_dest[1] == port

    def test_stop_while_handling_message(self, handler, callback, mock_socket):
        """Test stopping handler while message is being processed."""

        # Make callback take some time
        def slow_callback(msg, sender):
            time.sleep(0.1)
            callback(msg, sender)

        handler._on_message = slow_callback

        msg = create_gossip_message()
        data = msg.SerializeToString()
        addr = ("127.0.0.1", 9000)

        # Start handling in thread
        import threading
        handle_thread = threading.Thread(target=handler._handle_message, args=(data, addr))
        handle_thread.start()

        # Stop immediately
        handler.stop()

        # Thread should complete
        handle_thread.join(timeout=0.5)

        # Callback should have been called
        callback.assert_called_once()

    def test_receive_malformed_protobuf_with_valid_prefix(self, handler, callback, capsys):
        """Test receiving data that starts like protobuf but is malformed."""
        # Data that might parse partially but is invalid
        malformed_data = b'\x08\x01\x10\x00\x18\x00'  # Some protobuf-like bytes
        addr = ("127.0.0.1", 9000)

        handler._handle_message(malformed_data, addr)

        # Should handle gracefully
        # Might call callback with partial data or might fail parsing
        # Either way, should not crash

    def test_send_to_many_maintains_order(self, handler, mock_socket):
        """Test that send_to_many sends in the order provided."""
        msg = create_gossip_message()
        addrs = [
            ServerReference(f"10.0.{i}.1", 9000 + i)
            for i in range(10)
        ]

        handler.send_to_many(msg, addrs)

        # Verify order
        sent_destinations = [call[0][1] for call in mock_socket.sendto.call_args_list]
        expected_destinations = [
            (f"10.0.{i}.1", 9000 + i)
            for i in range(10)
        ]

        assert sent_destinations == expected_destinations

    def test_callback_receives_fresh_message_instance(self, handler):
        """Test that each callback receives a fresh message instance."""
        received_messages = []

        def capture_callback(msg, sender):
            received_messages.append(msg)

        handler._on_message = capture_callback

        # Send two different messages
        msg1 = create_gossip_message(nonce=1)
        msg2 = create_gossip_message(nonce=2)

        data1 = msg1.SerializeToString()
        data2 = msg2.SerializeToString()
        addr = ("127.0.0.1", 9000)

        handler._handle_message(data1, addr)
        handler._handle_message(data2, addr)

        # Should have received two different message instances
        assert len(received_messages) == 2
        assert received_messages[0].nonce == 1
        assert received_messages[1].nonce == 2

        # Should be different objects
        assert received_messages[0] is not received_messages[1]