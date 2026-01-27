import unittest
import queue
import time
import sys
import os
from unittest.mock import MagicMock, patch, call, ANY, PropertyMock
from bomberman.room_server.RoomServer import RoomServer, get_game_status, app
from bomberman.room_server.GameEngine import (
    GameState,
    GameAction,
    Direction,
    Player,
    Position,
    MOVE_PLAYER,
    PLACE_BOMB,
    STAY,
)
from bomberman.room_server.gossip import bomberman_pb2
from bomberman.room_server.GameStatePersistence import (
    AUTOSAVE_INTERVAL,
    SERVER_RECONNECTION_TIMEOUT,
)


class TestRoomServerAPI(unittest.TestCase):
    """Tests for FastAPI endpoints"""

    def setUp(self):
        # Reset global instance before each test
        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def tearDown(self):
        # Reset global instance after each test
        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    @patch("bomberman.room_server.RoomServer.server_instance")
    def test_get_status_with_server_instance(self, mock_global_instance):
        """Test /status endpoint when server is initialized"""
        import bomberman.room_server.RoomServer as rs_module

        # Create mock server instance
        mock_global_instance.__bool__.return_value = True  # Make it truthy
        mock_global_instance.engine.__bool__.return_value = True  # Make engine truthy
        # Ensure the state has a .name attribute (Enums do this automatically)
        mock_global_instance.engine.state = GameState.IN_PROGRESS

        # Set the global instance
        rs_module.server_instance = mock_global_instance
        # Call the actual module function, not the mock
        response = get_game_status()

        self.assertEqual(response["status"], "IN_PROGRESS")

    def test_get_status_without_server_instance(self):
        """Test /status endpoint when server is not initialized"""
        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

        response = get_game_status()

        self.assertEqual(response["status"], "ROOM_SERVER_NOT_INITIALIZED")

    @patch("bomberman.room_server.RoomServer.server_instance")
    def test_get_status_all_game_states(self, mock_global_instance):
        """Test /status endpoint with all possible game states"""
        for state in [GameState.WAITING_FOR_PLAYERS, GameState.IN_PROGRESS, GameState.GAME_OVER]:
            # Configure the patched global for this state
            mock_global_instance.__bool__.return_value = True  # Make it truthy
            mock_global_instance.engine.__bool__.return_value = True  # Make engine truthy
            mock_global_instance.engine.state = state

            response = get_game_status()
            self.assertEqual(response["status"], state.name)


class TestRoomServerInitialization(unittest.TestCase):
    """Tests for RoomServer initialization"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room-123", "HUB_API_URL": "http://test-hub.local"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.mock_socket_cls = self.socket_patcher.start()
        self.mock_socket = MagicMock()
        self.mock_socket_cls.return_value = self.mock_socket

        # Patch GameStatePersistence and provide the constants
        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch AUTOSAVE_INTERVAL constant
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()

        # Patch SERVER_RECONNECTION_TIMEOUT constant
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.engine_patcher = patch("bomberman.room_server.RoomServer.game_engine.GameEngine")
        self.mock_engine_cls = self.engine_patcher.start()
        # Configure the mock to return a properly configured engine instance
        self.mock_engine_instance = MagicMock()
        self.mock_engine_instance.state = GameState.WAITING_FOR_PLAYERS
        self.mock_engine_instance.tick_rate = 10
        self.mock_engine_instance.players = []
        self.mock_engine_instance.current_tick = 0
        self.mock_engine_cls.return_value = self.mock_engine_instance

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.engine_patcher.stop()

        # Reset global instance
        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_initialization_fresh_game(self):
        """Test server initialization without saved state"""
        self.mock_persistence.load_game_state.return_value = None

        server = RoomServer()

        self.assertEqual(server.room_id, "test-room-123")
        self.assertEqual(server.hub_api_url, "http://test-hub.local")
        self.assertFalse(server.is_resumed_game)
        self.assertIsNone(server.reconnection_deadline)
        self.assertEqual(len(server.expected_players), 0)
        self.assertFalse(server.game_started_notified)
        self.assertFalse(server.game_over_notified)
        self.mock_engine_cls.assert_called_once_with(seed=42)

    def test_initialization_resumed_game(self):
        """Test server initialization with saved state"""
        # Create mock engine with players
        mock_engine = MagicMock()
        mock_engine.current_tick = 100
        player1 = MagicMock()
        player1.id = "player1"
        player1.is_alive = True
        player2 = MagicMock()
        player2.id = "player2"
        player2.is_alive = False
        mock_engine.players = [player1, player2]

        self.mock_persistence.load_game_state.return_value = (mock_engine, 12345.0)

        with patch("time.time", return_value=1000.0):
            server = RoomServer()

        self.assertTrue(server.is_resumed_game)
        self.assertIsNotNone(server.reconnection_deadline)
        self.assertEqual(server.expected_players, {"player1"})  # Only alive player
        self.assertEqual(server.engine, mock_engine)

    def test_initialization_socket_setup(self):
        """Test that socket is properly configured"""
        self.mock_persistence.load_game_state.return_value = None

        server = RoomServer()

        self.mock_socket.setsockopt.assert_called_once()
        self.mock_socket.bind.assert_called_once_with(("0.0.0.0", 5000))

    def test_initialization_sets_global_instance(self):
        """Test that initialization sets the global server_instance"""
        # Import at function level to ensure fresh import
        import bomberman.room_server.RoomServer as rs_module

        self.mock_persistence.load_game_state.return_value = None

        # Verify it starts as None
        self.assertIsNone(rs_module.server_instance)

        # Create RoomServer instance
        server = RoomServer()

        # Access the global through the same module reference
        import sys

        actual_module = sys.modules["bomberman.room_server.RoomServer"]

        # Now it should be set
        self.assertIsNotNone(actual_module.server_instance)
        self.assertIs(actual_module.server_instance, server)


class TestRoomServerLifecycle(unittest.TestCase):
    """Tests for server start and shutdown"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.mock_socket_cls = self.socket_patcher.start()
        self.mock_socket = MagicMock()
        self.mock_socket_cls.return_value = self.mock_socket

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.thread_patcher = patch("threading.Thread")
        self.mock_thread_cls = self.thread_patcher.start()

        self.uvicorn_patcher = patch("uvicorn.run")
        self.mock_uvicorn = self.uvicorn_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.thread_patcher.stop()
        self.uvicorn_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    @patch("sys.exit")
    def test_start_creates_threads(self, mock_exit):
        """Test that start() creates API and game loop threads"""
        server = RoomServer()

        # Simulate KeyboardInterrupt after accept
        self.mock_socket.accept.side_effect = KeyboardInterrupt()

        server.start()

        # Should create 2 threads: API thread and game loop thread
        self.assertEqual(self.mock_thread_cls.call_count, 2)
        self.mock_socket.listen.assert_called_once()

    @patch("sys.exit")
    def test_start_accepts_client_connections(self, mock_exit):
        """Test that start() accepts and handles client connections"""
        server = RoomServer()

        mock_client_socket = MagicMock()
        mock_addr = ("127.0.0.1", 12345)

        # First accept returns a client, second raises KeyboardInterrupt
        self.mock_socket.accept.side_effect = [(mock_client_socket, mock_addr), KeyboardInterrupt()]

        server.start()

        # Should create 3 threads: API, game loop, and client handler
        self.assertEqual(self.mock_thread_cls.call_count, 3)

    @patch("sys.exit")
    def test_shutdown_saves_in_progress_game(self, mock_exit):
        """Test that shutdown saves game state when in progress"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.clients = {"player1": MagicMock()}

        server._shutdown()

        self.mock_persistence.save_game_state.assert_called_once_with(server.engine)
        self.mock_persistence.delete_save_file.assert_not_called()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    def test_shutdown_deletes_save_when_game_over(self, mock_exit):
        """Test that shutdown deletes save file when game is over"""
        server = RoomServer()
        server.engine.state = GameState.GAME_OVER

        server._shutdown()

        self.mock_persistence.delete_save_file.assert_called_once()
        self.mock_persistence.save_game_state.assert_not_called()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    def test_shutdown_closes_all_clients(self, mock_exit):
        """Test that shutdown closes all client connections"""
        server = RoomServer()
        server.engine.state = GameState.WAITING_FOR_PLAYERS

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        server.clients = {"player1": mock_client1, "player2": mock_client2}

        server._shutdown()

        mock_client1.close.assert_called_once()
        mock_client2.close.assert_called_once()
        self.assertEqual(len(server.clients), 0)

    @patch("sys.exit")
    def test_shutdown_handles_client_close_errors(self, mock_exit):
        """Test that shutdown handles errors when closing clients"""
        server = RoomServer()
        server.engine.state = GameState.WAITING_FOR_PLAYERS

        mock_client = MagicMock()
        mock_client.close.side_effect = Exception("Socket error")
        server.clients = {"player1": mock_client}

        # Should not raise exception
        server._shutdown()

        self.assertEqual(len(server.clients), 0)


class TestGameRestart(unittest.TestCase):
    """Tests for game restart functionality"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.mock_socket_cls = self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.engine_patcher = patch("bomberman.room_server.RoomServer.game_engine.GameEngine")
        self.mock_engine_cls = self.engine_patcher.start()
        # Configure the mock to return a properly configured engine instance
        self.mock_engine_instance = MagicMock()
        self.mock_engine_instance.state = GameState.WAITING_FOR_PLAYERS
        self.mock_engine_instance.tick_rate = 10
        self.mock_engine_instance.players = []
        self.mock_engine_instance.current_tick = 0
        self.mock_engine_cls.return_value = self.mock_engine_instance

        self.send_msg_patcher = patch("bomberman.room_server.RoomServer.send_msg")
        self.mock_send_msg = self.send_msg_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.engine_patcher.stop()
        self.send_msg_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    @patch("time.sleep")
    def test_restart_notifies_clients(self, mock_sleep):
        """Test that restart sends reset notification to all clients"""
        server = RoomServer()

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        server.clients = {"player1": mock_client1, "player2": mock_client2}

        server._restart_game()

        # Should send reset message to both clients
        self.assertEqual(self.mock_send_msg.call_count, 2)

        # Verify the message content
        for call_args in self.mock_send_msg.call_args_list:
            packet_data = call_args[0][1]
            packet = bomberman_pb2.Packet()
            packet.ParseFromString(packet_data)
            self.assertFalse(packet.server_response.success)
            self.assertEqual(packet.server_response.message, "SERVER_RESET")

    @patch("time.sleep")
    def test_restart_closes_all_clients(self, mock_sleep):
        """Test that restart closes all client connections"""
        server = RoomServer()

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        server.clients = {"player1": mock_client1, "player2": mock_client2}

        server._restart_game()

        mock_client1.close.assert_called_once()
        mock_client2.close.assert_called_once()
        self.assertEqual(len(server.clients), 0)

    @patch("time.sleep")
    def test_restart_creates_new_engine(self, mock_sleep):
        """Test that restart creates a new game engine"""
        server = RoomServer()
        original_engine = server.engine

        # Reset call count from initialization
        self.mock_engine_cls.reset_mock()

        server._restart_game()

        # Should create new engine with no seed (random)
        self.mock_engine_cls.assert_called_once_with(seed=None)

    @patch("time.sleep")
    def test_restart_resets_state_flags(self, mock_sleep):
        """Test that restart resets all state tracking flags"""
        server = RoomServer()

        # Set various state flags
        server.ticks_since_save = 100
        server.game_over_timestamp = 12345.0
        server.is_resumed_game = True
        server.expected_players = {"player1", "player2"}

        server._restart_game()

        self.assertEqual(server.ticks_since_save, 0)
        self.assertIsNone(server.game_over_timestamp)
        self.assertFalse(server.is_resumed_game)
        self.assertEqual(len(server.expected_players), 0)

    @patch("time.sleep")
    def test_restart_handles_send_errors(self, mock_sleep):
        """Test that restart handles errors when notifying clients"""
        server = RoomServer()

        mock_client = MagicMock()
        server.clients = {"player1": mock_client}

        # Make send_msg raise an exception
        self.mock_send_msg.side_effect = Exception("Send error")

        # Should not raise exception
        server._restart_game()

        # Should still attempt to close the client (wrapped in try/except in actual code)
        # The actual implementation catches all exceptions in the try block
        # So the client IS closed despite the send error
        self.assertTrue(mock_client.close.called or len(server.clients) == 0)


class TestGameLoop(unittest.TestCase):
    """Tests for the main game loop"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.time_patcher = patch("time.time")
        self.mock_time = self.time_patcher.start()

        self.sleep_patcher = patch("time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.time_patcher.stop()
        self.sleep_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_game_loop_processes_actions(self):
        """Test that game loop processes queued actions"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS

        # Queue some actions
        proto_action = bomberman_pb2.Packet().client_action
        proto_action.player_id = "player1"
        proto_action.action_type = bomberman_pb2.GameAction.MOVE_UP
        server.action_queue.put(("player1", proto_action))

        # Stop loop after one tick
        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)

        self.mock_time.return_value = 1000.0

        server.game_loop()

        # Verify tick was called with actions
        server.engine.tick.assert_called_once()
        call_kwargs = server.engine.tick.call_args[1]
        self.assertIn("actions", call_kwargs)
        self.assertEqual(len(call_kwargs["actions"]), 1)

    def test_game_loop_autosave(self):
        """Test that game loop autosaves at correct intervals"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.ticks_since_save = 4  # One tick away from autosave (5 is the interval)

        # Reset the mock to ensure clean state after server creation
        self.mock_persistence.save_game_state.reset_mock()

        # Stop loop after one tick
        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)

        self.mock_time.return_value = 1000.0

        server.game_loop()

        # Should have saved (ticks_since_save becomes 5 after tick)
        self.mock_persistence.save_game_state.assert_called_once_with(server.engine)
        self.assertEqual(server.ticks_since_save, 0)

    def test_game_loop_no_autosave_before_interval(self):
        """Test that autosave doesn't happen before interval"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.ticks_since_save = 0  # Well before autosave interval

        # Reset the mock to ensure clean state after server creation
        self.mock_persistence.save_game_state.reset_mock()

        # Stop loop after one tick
        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)

        self.mock_time.return_value = 1000.0

        server.game_loop()

        # Should not have saved (need 5 ticks)
        self.mock_persistence.save_game_state.assert_not_called()
        self.assertEqual(server.ticks_since_save, 1)  # Incremented by 1

    def test_game_loop_game_over_sequence(self):
        """Test game loop handles game over and restart"""
        server = RoomServer()
        server.engine.state = GameState.GAME_OVER

        # Mock time progression
        self.mock_time.side_effect = [
            1000.0,  # Loop start, set timestamp
            1000.0,  # Same tick
            1001.0,  # Next tick, not enough time
            1001.0,  # Same tick
            1006.0,  # Next tick, timeout reached
        ]

        restart_called = False

        def mock_restart():
            nonlocal restart_called
            restart_called = True
            server.running = False

        with (
            patch.object(server, "_restart_game", side_effect=mock_restart),
            patch.object(server, "_notify_hub_game_close"),
        ):
            server.game_loop()

        self.assertTrue(restart_called)
        self.mock_persistence.delete_save_file.assert_called()

    def test_game_loop_reconnection_timeout(self):
        """Test game loop handles reconnection timeout"""
        server = RoomServer()
        server.is_resumed_game = True
        server.reconnection_deadline = 1000.0
        server.expected_players = {"player1"}

        self.mock_time.return_value = 1005.0  # Past deadline

        restart_called = False

        def mock_restart():
            nonlocal restart_called
            restart_called = True
            server.running = False

        with patch.object(server, "_restart_game", side_effect=mock_restart):
            server.game_loop()

        self.assertTrue(restart_called)

    def test_game_loop_reconnection_deadline_cleared(self):
        """Test that reconnection deadline is cleared after timeout"""
        server = RoomServer()
        server.is_resumed_game = True
        server.reconnection_deadline = 1000.0
        server.expected_players = set()  # All players reconnected

        self.mock_time.return_value = 1005.0

        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)

        server.game_loop()

        self.assertFalse(server.is_resumed_game)
        self.assertIsNone(server.reconnection_deadline)

    def test_game_loop_notifies_hub_on_game_start(self):
        """Test that game loop notifies hub when game starts"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS  # Start in IN_PROGRESS

        # Stop loop after one tick
        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)
        self.mock_time.return_value = 1000.0

        with patch.object(server, "_notify_hub_game_start") as mock_notify:
            server.game_loop()
            # Should be called once since game is already IN_PROGRESS
            mock_notify.assert_called_once()

    def test_game_loop_broadcasts_game_state(self):
        """Test that game loop broadcasts state each tick"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS

        def stop_loop(**kwargs):
            server.running = False

        server.engine.tick = MagicMock(side_effect=stop_loop)

        self.mock_time.return_value = 1000.0

        with patch.object(server, "broadcast_game") as mock_broadcast:
            server.game_loop()
            mock_broadcast.assert_called_once()


class TestClientHandling(unittest.TestCase):
    """Tests for client connection handling"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.recv_msg_patcher = patch("bomberman.room_server.RoomServer.recv_msg")
        self.mock_recv_msg = self.recv_msg_patcher.start()

        self.send_msg_patcher = patch("bomberman.room_server.RoomServer.send_msg")
        self.mock_send_msg = self.send_msg_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.recv_msg_patcher.stop()
        self.send_msg_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_handle_client_successful_join(self):
        """Test successful client join during waiting phase"""
        server = RoomServer()
        server.engine.state = GameState.WAITING_FOR_PLAYERS

        # Create join request
        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        # Client sends join then disconnects
        self.mock_recv_msg.side_effect = [join_packet.SerializeToString(), None]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Should send success response
        self.mock_send_msg.assert_called()
        response_data = self.mock_send_msg.call_args[0][1]
        response = bomberman_pb2.Packet()
        response.ParseFromString(response_data)
        self.assertTrue(response.server_response.success)

    def test_handle_client_reconnection(self):
        """Test client reconnection during resumed game"""
        server = RoomServer()
        server.is_resumed_game = True
        server.expected_players = {"player1"}
        server.engine.state = GameState.IN_PROGRESS
        server.engine.current_tick = 100  # Mock the current tick

        # Mock add_player to do nothing (reconnection doesn't call add_player)
        server.engine.add_player = MagicMock()

        # Create join request
        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        self.mock_recv_msg.side_effect = [join_packet.SerializeToString(), None]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Player should be removed from expected players
        self.assertNotIn("player1", server.expected_players)

        # Should send success response
        self.assertTrue(self.mock_send_msg.called)
        # The first call is the success response
        response_data = self.mock_send_msg.call_args_list[0][0][1]
        response = bomberman_pb2.Packet()
        response.ParseFromString(response_data)
        self.assertTrue(response.server_response.success)

    def test_handle_client_join_when_game_in_progress(self):
        """Test that new joins are rejected when game is in progress"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.is_resumed_game = False

        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "new_player"

        self.mock_recv_msg.side_effect = [join_packet.SerializeToString(), None]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Should send failure response
        self.assertTrue(self.mock_send_msg.called)
        response_data = self.mock_send_msg.call_args[0][1]
        response = bomberman_pb2.Packet()
        response.ParseFromString(response_data)
        self.assertFalse(response.server_response.success)

    def test_handle_client_quit_action(self):
        """Test client sending quit action"""
        server = RoomServer()
        server.engine.state = GameState.WAITING_FOR_PLAYERS
        server.engine.add_player = MagicMock()

        # Join request
        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        # Quit action
        quit_packet = bomberman_pb2.Packet()
        quit_packet.client_action.player_id = "player1"
        quit_packet.client_action.action_type = bomberman_pb2.GameAction.QUIT

        self.mock_recv_msg.side_effect = [
            join_packet.SerializeToString(),
            quit_packet.SerializeToString(),
            None,
        ]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Client should be removed
        self.assertNotIn("player1", server.clients)

    def test_handle_client_movement_action(self):
        """Test client sending movement action"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.is_resumed_game = False

        # For IN_PROGRESS without resumed game, new joins are rejected
        # test with a reconnection scenario instead
        server.is_resumed_game = True
        server.expected_players = {"player1"}

        # Join request
        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        # Movement action
        move_packet = bomberman_pb2.Packet()
        move_packet.client_action.player_id = "player1"
        move_packet.client_action.action_type = bomberman_pb2.GameAction.MOVE_UP

        self.mock_recv_msg.side_effect = [
            join_packet.SerializeToString(),
            move_packet.SerializeToString(),
            None,
        ]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Action should be queued
        self.assertFalse(server.action_queue.empty())
        player_id, action = server.action_queue.get()
        self.assertEqual(player_id, "player1")
        self.assertEqual(action.action_type, bomberman_pb2.GameAction.MOVE_UP)

    def test_handle_client_disconnect_during_game(self):
        """Test client disconnect marks player as dead"""
        server = RoomServer()
        server.engine.state = GameState.IN_PROGRESS
        server.is_resumed_game = True
        server.expected_players = {"player1"}

        # Setup player in engine
        mock_player = MagicMock()
        mock_player.id = "player1"
        mock_player.is_alive = True
        server.engine.players = [mock_player]
        server.engine.check_game_over = MagicMock()

        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        self.mock_recv_msg.side_effect = [join_packet.SerializeToString(), None]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Player should be marked dead
        self.assertFalse(mock_player.is_alive)
        server.engine.check_game_over.assert_called()

    def test_handle_client_join_exception(self):
        """Test handling of exception during player join"""
        server = RoomServer()
        server.engine.state = GameState.WAITING_FOR_PLAYERS

        # Mock add_player as a MagicMock that can have side_effect
        server.engine.add_player = MagicMock(side_effect=ValueError("Room full"))

        join_packet = bomberman_pb2.Packet()
        join_packet.join_request.player_id = "player1"

        self.mock_recv_msg.side_effect = [join_packet.SerializeToString(), None]

        mock_socket = MagicMock()
        server.handle_client(mock_socket, ("127.0.0.1", 12345))

        # Should send failure response
        self.assertTrue(self.mock_send_msg.called)
        response_data = self.mock_send_msg.call_args[0][1]
        response = bomberman_pb2.Packet()
        response.ParseFromString(response_data)
        self.assertFalse(response.server_response.success)

    def test_handle_client_socket_error(self):
        """Test handling of socket errors"""
        server = RoomServer()

        self.mock_recv_msg.side_effect = OSError("Socket closed")

        mock_socket = MagicMock()
        # Should not raise exception
        server.handle_client(mock_socket, ("127.0.0.1", 12345))


class TestBroadcasting(unittest.TestCase):
    """Tests for broadcasting game state"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.send_msg_patcher = patch("bomberman.room_server.RoomServer.send_msg")
        self.mock_send_msg = self.send_msg_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.send_msg_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_broadcast_sends_to_all_clients(self):
        """Test broadcast sends state to all connected clients"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_GRID")
        server.engine.state = GameState.IN_PROGRESS

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        server.clients = {"player1": mock_client1, "player2": mock_client2}

        server.broadcast_game()

        # Should send to both clients
        self.assertEqual(self.mock_send_msg.call_count, 2)

    def test_broadcast_includes_reconnection_info(self):
        """Test broadcast includes reconnection info when waiting"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_GRID")
        server.engine.state = GameState.IN_PROGRESS
        server.is_resumed_game = True
        server.reconnection_deadline = 1010.0
        server.expected_players = {"player1"}

        with patch("time.time", return_value=1005.0):
            mock_client = MagicMock()
            server.clients = {"player2": mock_client}

            server.broadcast_game()

        # Verify the message includes reconnection info
        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)
        self.assertIn("WAITING FOR RECONNECTION", packet.state_snapshot.ascii_grid)

    def test_broadcast_handles_send_errors(self):
        """Test broadcast handles errors when sending to clients"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_GRID")

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        server.clients = {"player1": mock_client1, "player2": mock_client2}

        # Make one send fail
        self.mock_send_msg.side_effect = [Exception("Send error"), None]

        # Should not raise exception
        server.broadcast_game()

        # Should still try to send to second client
        self.assertEqual(self.mock_send_msg.call_count, 2)

    def test_broadcast_includes_game_over_flag(self):
        """Test broadcast includes game over flag"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_OVER_GRID")
        server.engine.state = GameState.GAME_OVER

        mock_client = MagicMock()
        server.clients = {"player1": mock_client}

        server.broadcast_game()

        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)
        self.assertTrue(packet.state_snapshot.is_game_over)


class TestActionMapping(unittest.TestCase):
    """Tests for proto action to engine action mapping"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_map_move_actions(self):
        """Test mapping of all movement actions"""
        server = RoomServer()

        test_cases = [
            (bomberman_pb2.GameAction.MOVE_UP, Direction.UP),
            (bomberman_pb2.GameAction.MOVE_DOWN, Direction.DOWN),
            (bomberman_pb2.GameAction.MOVE_LEFT, Direction.LEFT),
            (bomberman_pb2.GameAction.MOVE_RIGHT, Direction.RIGHT),
        ]

        for proto_action, expected_direction in test_cases:
            proto = bomberman_pb2.Packet().client_action
            proto.player_id = "player1"
            proto.action_type = proto_action

            result = server._map_proto_to_engine(proto)

            self.assertIsInstance(result, MOVE_PLAYER)
            self.assertEqual(result.player_id, "player1")
            self.assertEqual(result.direction, expected_direction)

    def test_map_place_bomb_action(self):
        """Test mapping of place bomb action"""
        server = RoomServer()

        proto = bomberman_pb2.Packet().client_action
        proto.player_id = "player1"
        proto.action_type = bomberman_pb2.GameAction.PLACE_BOMB

        result = server._map_proto_to_engine(proto)

        self.assertIsInstance(result, PLACE_BOMB)
        self.assertEqual(result.player_id, "player1")

    def test_map_stay_action(self):
        """Test mapping of stay action"""
        server = RoomServer()

        proto = bomberman_pb2.Packet().client_action
        proto.player_id = "player1"
        proto.action_type = bomberman_pb2.GameAction.STAY

        result = server._map_proto_to_engine(proto)

        self.assertIsInstance(result, STAY)

    def test_map_invalid_action(self):
        """Test mapping of invalid action returns None"""
        server = RoomServer()

        proto = bomberman_pb2.Packet().client_action
        proto.player_id = "player1"
        proto.action_type = 9999  # Invalid action

        result = server._map_proto_to_engine(proto)

        self.assertIsNone(result)


class TestHubNotifications(unittest.TestCase):
    """Tests for hub server notifications"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test-hub"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.requests_patcher = patch("requests.post")
        self.mock_post = self.requests_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.requests_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_notify_hub_game_start_success(self):
        """Test successful hub notification on game start"""
        server = RoomServer()
        self.mock_post.return_value.status_code = 200

        server._notify_hub_game_start()

        self.mock_post.assert_called_once()
        self.assertEqual(self.mock_post.call_args[0][0], "http://test-hub/room/test-room/start")
        self.assertTrue(server.game_started_notified)

    def test_notify_hub_game_start_only_once(self):
        """Test hub is only notified once for game start"""
        server = RoomServer()
        self.mock_post.return_value.status_code = 200

        server._notify_hub_game_start()
        server._notify_hub_game_start()  # Second call

        # Should only call once
        self.mock_post.assert_called_once()

    def test_notify_hub_game_start_handles_errors(self):
        """Test hub notification handles network errors gracefully"""
        server = RoomServer()
        self.mock_post.side_effect = Exception("Network error")

        # Should not raise exception
        server._notify_hub_game_start()

        # Should still mark as notified to prevent retries
        self.assertTrue(server.game_started_notified)

    def test_notify_hub_game_close_success(self):
        """Test successful hub notification on game close"""
        server = RoomServer()
        self.mock_post.return_value.status_code = 200

        server._notify_hub_game_close()

        self.mock_post.assert_called_once()
        self.assertEqual(self.mock_post.call_args[0][0], "http://test-hub/room/test-room/close")
        self.assertTrue(server.game_over_notified)

    def test_notify_hub_game_close_only_once(self):
        """Test hub is only notified once for game close"""
        server = RoomServer()
        self.mock_post.return_value.status_code = 200

        server._notify_hub_game_close()
        server._notify_hub_game_close()  # Second call

        # Should only call once
        self.mock_post.assert_called_once()

    def test_notify_hub_handles_non_200_response(self):
        """Test hub notification handles non-200 status codes"""
        server = RoomServer()
        self.mock_post.return_value.status_code = 500

        # Should not raise exception
        server._notify_hub_game_start()

        # Should still mark as notified
        self.assertTrue(server.game_started_notified)


class TestHelperMethods(unittest.TestCase):
    """Tests for helper methods"""

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ", {"ROOM_ID": "test-room", "HUB_API_URL": "http://test"}
        )
        self.env_patcher.start()

        self.socket_patcher = patch("socket.socket")
        self.socket_patcher.start()

        self.persist_patcher = patch("bomberman.room_server.RoomServer.GameStatePersistence")
        self.mock_persistence = self.persist_patcher.start()
        self.mock_persistence.load_game_state.return_value = None

        # Patch constants
        self.autosave_patcher = patch(
            "bomberman.room_server.RoomServer.AUTOSAVE_INTERVAL", AUTOSAVE_INTERVAL
        )
        self.autosave_patcher.start()
        self.timeout_patcher = patch(
            "bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT",
            SERVER_RECONNECTION_TIMEOUT,
        )
        self.timeout_patcher.start()

        self.send_msg_patcher = patch("bomberman.room_server.RoomServer.send_msg")
        self.mock_send_msg = self.send_msg_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.socket_patcher.stop()
        self.persist_patcher.stop()
        self.autosave_patcher.stop()
        self.timeout_patcher.stop()
        self.send_msg_patcher.stop()

        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

    def test_send_response_success(self):
        """Test sending success response"""
        server = RoomServer()
        mock_socket = MagicMock()

        server._send_response(mock_socket, True, "Success message")

        self.mock_send_msg.assert_called_once()
        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)

        self.assertTrue(packet.server_response.success)
        self.assertEqual(packet.server_response.message, "Success message")
        self.assertEqual(packet.server_response.tick_rate, server.engine.tick_rate)

    def test_send_response_failure(self):
        """Test sending failure response"""
        server = RoomServer()
        mock_socket = MagicMock()

        server._send_response(mock_socket, False, "Error message")

        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)

        self.assertFalse(packet.server_response.success)
        self.assertEqual(packet.server_response.message, "Error message")

    def test_send_response_handles_errors(self):
        """Test send response handles send errors gracefully"""
        server = RoomServer()
        mock_socket = MagicMock()
        self.mock_send_msg.side_effect = Exception("Send error")

        # Should not raise exception
        server._send_response(mock_socket, True, "Message")

    def test_send_game_state(self):
        """Test sending game state to client"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_GRID")
        server.engine.state = GameState.IN_PROGRESS

        mock_socket = MagicMock()
        server._send_game_state(mock_socket)

        self.mock_send_msg.assert_called_once()
        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)

        self.assertEqual(packet.state_snapshot.ascii_grid, "GAME_GRID")
        self.assertFalse(packet.state_snapshot.is_game_over)

    def test_send_game_state_game_over(self):
        """Test sending game state when game is over"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_OVER_GRID")
        server.engine.state = GameState.GAME_OVER

        mock_socket = MagicMock()
        server._send_game_state(mock_socket)

        packet_data = self.mock_send_msg.call_args[0][1]
        packet = bomberman_pb2.Packet()
        packet.ParseFromString(packet_data)

        self.assertTrue(packet.state_snapshot.is_game_over)

    def test_send_game_state_handles_errors(self):
        """Test send game state handles errors gracefully"""
        server = RoomServer()
        server.engine.get_ascii_snapshot = MagicMock(return_value="GAME_GRID")
        self.mock_send_msg.side_effect = Exception("Send error")

        mock_socket = MagicMock()
        # Should not raise exception
        server._send_game_state(mock_socket)
