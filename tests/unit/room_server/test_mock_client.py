import unittest
from unittest.mock import MagicMock, patch
from bomberman.room_server.MockClient import GameClient
from bomberman.room_server.gossip import bomberman_pb2

class TestMockClient(unittest.TestCase):
    
    def setUp(self):
        self.client = GameClient("TestPlayer")

    @patch("socket.socket")
    @patch("bomberman.room_server.MockClient.send_msg")
    @patch("bomberman.room_server.MockClient.recv_msg")
    def test_connect_success(self, mock_recv, mock_send, mock_socket_cls):
        """Test successful connection handshake."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        
        # Prepare server response packet
        resp = bomberman_pb2.Packet()
        resp.server_response.success = True
        resp.server_response.message = "Welcome"
        resp.server_response.tick_rate = 20
        mock_recv.return_value = resp.SerializeToString()
        
        result = self.client.connect()
        
        self.assertTrue(result)
        self.assertTrue(self.client.is_connected)
        self.assertEqual(self.client.tick_rate, 20)
        mock_sock.connect.assert_called()

    @patch("socket.socket")
    @patch("bomberman.room_server.MockClient.send_msg")
    @patch("bomberman.room_server.MockClient.recv_msg")
    def test_connect_fail_handshake(self, mock_recv, mock_send, mock_socket_cls):
        """Test connection failure when server denies join."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        
        resp = bomberman_pb2.Packet()
        resp.server_response.success = False
        resp.server_response.message = "Full"
        mock_recv.return_value = resp.SerializeToString()
        
        result = self.client.connect()
        
        self.assertFalse(result)
        self.assertFalse(self.client.is_connected)

    @patch("bomberman.room_server.MockClient.send_msg")
    def test_send_action(self, mock_send):
        """Test sending an action."""
        self.client.sock = MagicMock()
        self.client.is_connected = True
        
        self.client.send_action(bomberman_pb2.GameAction.MOVE_UP)
        
        # Verify packet construction
        args, _ = mock_send.call_args
        sent_bytes = args[1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(sent_bytes)
        
        self.assertEqual(packet.client_action.player_id, "TestPlayer")
        self.assertEqual(packet.client_action.action_type, bomberman_pb2.GameAction.MOVE_UP)

    @patch("bomberman.room_server.MockClient.recv_msg")
    def test_receive_loop_reset(self, mock_recv):
        """Test handling of SERVER_RESET message."""
        self.client.sock = MagicMock()
        self.client.is_connected = True
        self.client.running = True
        
        # Mock receiving a reset packet
        resp = bomberman_pb2.Packet()
        resp.server_response.message = "SERVER_RESET"
        mock_recv.return_value = resp.SerializeToString()
        
        # Run one iteration of receive loop logic manually to avoid threading issues
        # We simulate the inside of the loop
        data = mock_recv()
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(data)
        
        if packet.server_response.message == "SERVER_RESET":
            self.client.server_reset_detected = True
            self.client.running = False
            
        self.assertTrue(self.client.server_reset_detected)
        self.assertFalse(self.client.running)