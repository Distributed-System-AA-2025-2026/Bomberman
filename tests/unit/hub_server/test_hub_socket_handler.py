import pytest
import socket
from unittest.mock import MagicMock, patch

from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.gossip import messages_pb2 as pb


class TestHubSocketHandlerValidation:

    def _valid_callback(self, msg, sender):
        pass


    def test_creation_with_valid_callback(self):
        handler = HubSocketHandler(9000, self._valid_callback)
        assert callable(handler._on_message)


    def test_none_callback_raises_type_error(self):
        with pytest.raises(TypeError, match="cannot be None"):
            HubSocketHandler(9000, None)


    @patch("socket.socket")
    def test_non_callable_callback_raises_type_error(self, mock_socket):
        with pytest.raises(TypeError, match="must be callable"):
            HubSocketHandler(9000, "not_a_function")

    @patch("socket.socket")
    def test_callback_wrong_param_count_raises_type_error(self, mock_socket):
        def bad_callback(only_one_param):
            pass
        with pytest.raises(TypeError, match="must accept exactly 2 parameters"):
            HubSocketHandler(9000, bad_callback)

    @patch("socket.socket")
    def test_callback_zero_params_raises_type_error(self, mock_socket):
        def no_params():
            pass
        with pytest.raises(TypeError, match="must accept exactly 2 parameters"):
            HubSocketHandler(9000, no_params)


    @patch("socket.socket")
    def test_callback_three_params_raises_type_error(self, mock_socket):
        def three_params(a, b, c):
            pass
        with pytest.raises(TypeError, match="must accept exactly 2 parameters"):
            HubSocketHandler(9000, three_params)


    @patch("socket.socket")
    def test_non_callable_logging_raises_type_error(self, mock_socket):
        with pytest.raises(TypeError, match="logging must be callable"):
            HubSocketHandler(9000, self._valid_callback, logging="not_callable")

    @patch("socket.socket")
    def test_none_logging_is_accepted(self, mock_socket):
        handler = HubSocketHandler(9000, self._valid_callback, logging=None)
        assert handler._logging is None


class TestHubSocketHandlerSend:

    def _valid_callback(self, msg, sender):
        pass

    @patch("socket.socket")
    def test_send_serializes_and_sends(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        handler = HubSocketHandler(9000, self._valid_callback)

        msg = pb.GossipMessage(nonce=1, origin=0)
        addr = ServerReference("10.0.0.1", 8000)
        handler.send(msg, addr)

        mock_sock.sendto.assert_called_once()
        data, dest = mock_sock.sendto.call_args[0]
        assert dest == ("10.0.0.1", 8000)
        assert isinstance(data, bytes)


    @patch("socket.socket")
    def test_send_to_many_sends_to_all(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        handler = HubSocketHandler(9000, self._valid_callback)

        msg = pb.GossipMessage(nonce=1, origin=0)
        addrs = [ServerReference("10.0.0.1", 8000), ServerReference("10.0.0.2", 8001)]
        handler.send_to_many(msg, addrs)

        assert mock_sock.sendto.call_count == 2


    @patch("socket.socket")
    def test_send_handles_dns_failure(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = socket.gaierror("DNS failed")
        mock_socket_cls.return_value = mock_sock
        logger = MagicMock()

        handler = HubSocketHandler(9000, self._valid_callback, logging=logger)
        msg = pb.GossipMessage(nonce=1, origin=0)
        handler.send(msg, ServerReference("bad.host", 8000))

        logger.assert_called_once()
        assert "DNS" in logger.call_args[0][0]


    @patch("socket.socket")
    def test_send_handles_os_error(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = OSError("Network unreachable")
        mock_socket_cls.return_value = mock_sock
        logger = MagicMock()

        handler = HubSocketHandler(9000, self._valid_callback, logging=logger)
        msg = pb.GossipMessage(nonce=1, origin=0)
        handler.send(msg, ServerReference("10.0.0.1", 8000))

        logger.assert_called_once()
        assert "Failed to send" in logger.call_args[0][0]


    @patch("socket.socket")
    def test_handle_message_parses_protobuf_and_calls_callback(self, mock_socket_cls):
        callback = MagicMock()
        mock_socket_cls.return_value = MagicMock()
        handler = HubSocketHandler(9000, callback)

        msg = pb.GossipMessage(nonce=42, origin=1, forwarded_by=1)
        data = msg.SerializeToString()
        handler._handle_message(data, ("10.0.0.1", 8000))

        callback.assert_called_once()
        parsed_msg, sender = callback.call_args[0]
        assert parsed_msg.nonce == 42
        assert sender.address == "10.0.0.1"
        assert sender.port == 8000

    @patch("socket.socket")
    def test_handle_message_invalid_data_does_not_call_callback(self, mock_socket_cls):
        #Dati non-protobuf vengono gestiti senza crash, il callback non viene invocato.
        callback = MagicMock()
        mock_socket_cls.return_value = MagicMock()
        handler = HubSocketHandler(9000, callback)
        handler._handle_message(b"garbage_data_not_protobuf", ("10.0.0.1", 8000))
        callback.assert_not_called()

    @patch("socket.socket")
    def test_stop_closes_socket(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        handler = HubSocketHandler(9000, self._valid_callback)
        handler.stop()
        mock_sock.close.assert_called_once()
        assert handler._running is False


    @patch("socket.socket")
    def test_start_sets_running_flag(self, mock_socket_cls):
        mock_sock = mock_socket_cls.return_value
        mock_sock.recvfrom.return_value = ("127.0.0.1", 9999)
        handler = HubSocketHandler(9000, self._valid_callback)
        handler._socket = mock_sock
        handler.start()
        assert handler._running is True
        handler.stop()

    @patch("socket.socket")
    def test_send_to_many_handles_dns_error_per_addr(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = [socket.gaierror("DNS"), None]
        mock_socket_cls.return_value = mock_sock
        handler = HubSocketHandler(9000, self._valid_callback)
        msg = pb.GossipMessage(nonce=1, origin=0)
        addrs = [ServerReference("bad.host", 8000), ServerReference("10.0.0.2", 8001)]
        handler.send_to_many(msg, addrs)
        assert mock_sock.sendto.call_count == 2


    @patch("socket.socket")
    def test_send_to_many_handles_os_error_per_addr(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = [OSError("fail"), None]
        mock_sock.recvfrom.side_effect = [OSError("closed"), None]
        mock_socket_cls.return_value = mock_sock

        handler = HubSocketHandler(9000, self._valid_callback)
        msg = pb.GossipMessage(nonce=1, origin=0)
        addrs = [ServerReference("10.0.0.1", 8000), ServerReference("10.0.0.2", 8001)]
        handler.send_to_many(msg, addrs)
        assert mock_sock.sendto.call_count == 2


    @patch("bomberman.hub_server.HubSocketHandler.socket.socket")
    def test_listen_loop_breaks_on_os_error(self, mock_socket_cls):
        mock_sock = mock_socket_cls.return_value
        mock_sock.recvfrom.side_effect = OSError("closed")
        handler = HubSocketHandler(9000, self._valid_callback)
        assert handler._socket is mock_socket_cls.return_value
        handler._running = True
        handler._listen_loop()
        mock_sock.recvfrom.assert_called()
