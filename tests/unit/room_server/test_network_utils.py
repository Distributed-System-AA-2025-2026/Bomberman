import unittest
from unittest.mock import MagicMock
import struct
import socket
from bomberman.room_server.NetworkUtils import send_msg, recv_msg

class TestNetworkUtils(unittest.TestCase):
    def test_send_msg(self):
        """Test that send_msg prefixes data with 4-byte length."""
        mock_sock = MagicMock(spec=socket.socket)
        message = b"hello"
        
        send_msg(mock_sock, message)
        
        # Expected: 4 bytes of length (5) + "hello"
        expected_payload = struct.pack(">I", 5) + b"hello"
        mock_sock.sendall.assert_called_once_with(expected_payload)

    def test_recv_msg_success(self):
        """Test receiving a complete message."""
        mock_sock = MagicMock(spec=socket.socket)
        # Mock receiving length (5) then data ("hello")
        mock_sock.recv.side_effect = [struct.pack(">I", 5), b"hello"]
        
        result = recv_msg(mock_sock)
        self.assertEqual(result, b"hello")

    def test_recv_msg_partial_header(self):
        """Test receiving incomplete header returns None."""
        mock_sock = MagicMock(spec=socket.socket)
        # Simulate partial header (2 bytes) then connection close (b"")
        mock_sock.recv.side_effect = [b"\x00\x00", b""] 
        
        result = recv_msg(mock_sock)
        self.assertIsNone(result)

    def test_recv_msg_connection_closed(self):
        """Test that None is returned when connection closes."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b"" 
        
        result = recv_msg(mock_sock)
        self.assertIsNone(result)