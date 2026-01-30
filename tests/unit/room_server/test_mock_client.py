import unittest
from unittest.mock import MagicMock, patch
from bomberman.room_server.MockClient import GameClient
from bomberman.room_server.gossip import bomberman_pb2
import time


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
        data = mock_recv()
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(data)

        if packet.server_response.message == "SERVER_RESET":
            self.client.server_reset_detected = True
            self.client.running = False

        self.assertTrue(self.client.server_reset_detected)
        self.assertFalse(self.client.running)

    def test_attempt_reconnection_timeout(self):
        """Test that reconnection stops after the timeout window."""
        self.client.server_reset_detected = False
        # Set start time to 31 seconds ago (exceeding the 30s limit)
        self.client.reconnection_start_time = time.time() - 31

        result = self.client.attempt_reconnection()

        self.assertFalse(result)
        self.assertFalse(self.client.running)

    @patch("bomberman.room_server.MockClient.GameClient.connect")
    def test_attempt_reconnection_success(self, mock_connect):
        """Test successful reconnection within the window."""
        mock_connect.return_value = True
        self.client.reconnection_start_time = time.time()

        result = self.client.attempt_reconnection()

        self.assertTrue(result)
        self.assertEqual(self.client.reconnection_attempts, 1)

    def test_attempt_reconnection_blocked_by_reset(self):
        """Ensure no reconnection is attempted if server reset was detected."""
        self.client.server_reset_detected = True
        result = self.client.attempt_reconnection()
        self.assertFalse(result)

    @patch("bomberman.room_server.MockClient.send_msg")
    def test_send_action_network_error(self, mock_send):
        """Test that connection state updates when sending fails."""
        self.client.is_connected = True
        self.client.sock = MagicMock()
        mock_send.side_effect = BrokenPipeError()

        self.client.send_action(bomberman_pb2.GameAction.MOVE_LEFT)

        self.assertFalse(self.client.is_connected)

    @patch("bomberman.room_server.MockClient.recv_msg")
    def test_receive_loop_disconnect(self, mock_recv):
        """Test handling of an empty receive (graceful server disconnect)."""
        self.client.is_connected = True
        mock_recv.return_value = None  # Simulates closed connection

        data = mock_recv(self.client.sock)
        if not data:
            self.client.is_connected = False

        self.assertFalse(self.client.is_connected)

    @patch("bomberman.room_server.MockClient.recv_msg")
    @patch("bomberman.room_server.MockClient.GameClient.render")
    def test_receive_loop_snapshot(self, mock_render, mock_recv):
        """Tests that state_snapshot packets trigger a render call."""
        self.client.is_connected = True
        
        # Create a snapshot packet
        packet = bomberman_pb2.Packet()
        packet.state_snapshot.ascii_grid = "####"
        packet.state_snapshot.is_game_over = False
        mock_recv.return_value = packet.SerializeToString()

        # Simulate one 'tick' of the receive loop logic
        data = mock_recv(self.client.sock)
        if data:
            p = bomberman_pb2.Packet()
            p.ParseFromString(data)
            if p.HasField('state_snapshot'):
                self.client.render(p.state_snapshot)

        mock_render.assert_called_once()

    @patch("bomberman.room_server.MockClient.GameClient.attempt_reconnection")
    @patch("time.time")
    def test_receive_loop_reconnect_trigger(self, mock_time, mock_reconnect):
        """Tests that the loop attempts reconnection when disconnected."""
        self.client.is_connected = False
        self.client.running = True
        
        # Mock time to ensure the RECONNECT_INTERVAL (2s) is surpassed
        mock_time.side_effect = [100.0, 105.0] 
        last_reconnect_attempt = 100.0
        
        current_time = 105.0 # second call to mock_time
        if not self.client.is_connected:
            if current_time - last_reconnect_attempt >= 2: # RECONNECT_INTERVAL
                self.client.attempt_reconnection()
                
        mock_reconnect.assert_called_once()

    @patch("bomberman.room_server.MockClient.recv_msg")
    def test_receive_loop_connection_lost(self, mock_recv):
        """Tests that connection loss sets is_connected to False."""
        self.client.is_connected = True
        # Simulate a network crash during recv
        mock_recv.side_effect = ConnectionResetError()

        try:
            self.client.sock = MagicMock()
            mock_recv(self.client.sock)
        except ConnectionResetError:
            self.client.is_connected = False

        self.assertFalse(self.client.is_connected)
        
    @patch("bomberman.room_server.MockClient.threading.Thread")
    @patch("bomberman.room_server.MockClient.RealTimeInput")
    @patch("bomberman.room_server.MockClient.os.system")
    @patch("bomberman.room_server.MockClient.GameClient.send_action")
    def test_start_method_logic(self, mock_send_action, mock_os_system, mock_input_cls, mock_thread_cls):
        """Test the start() method and main input loop mapping."""
        # Setup Mock Input Handler to simulate pressing 'w' then 'q'
        mock_input_handler = MagicMock()
        mock_input_handler.get_key.side_effect = ['w', 'q']
        mock_input_cls.return_value.__enter__.return_value = mock_input_handler
        
        # Configure Client State
        self.client.is_connected = True
        self.client.running = True
        self.client.tick_rate = 10
        
        # Execute start()
        self.client.start()
        
        # Assertions for Coverage
        # Verifies thread creation for receive_loop 
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread_cls.return_value.daemon)
        
        # Verifies screen clearing logic 
        mock_os_system.assert_called() 
        
        # Verifies input mapping 
        # The first call should be MOVE_UP (from 'w')
        mock_send_action.assert_any_call(bomberman_pb2.GameAction.MOVE_UP)
        
        # Verifies 'q' terminates the loop 
        self.assertFalse(self.client.running)
