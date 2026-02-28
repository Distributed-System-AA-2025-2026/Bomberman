import unittest
import threading
import socket
import time
import os
import sys
from unittest.mock import patch, MagicMock
from bomberman.room_server.RoomServer import RoomServer
from bomberman.room_server.gossip import bomberman_pb2
from bomberman.room_server.NetworkUtils import send_msg, recv_msg
from bomberman.room_server.GameEngine import GameState, Direction


class HeadlessClient:
    """
    A lightweight client that speaks the Bomberman protocol.
    Used to simulate players in integration tests.
    """

    def __init__(self, player_id, host, port):
        self.player_id = player_id
        self.host = host
        self.port = port
        self.sock = None
        self.is_connected = False
        self.latest_snapshot = None
        self.messages = []  # Stores server messages
        self._running = False
        self._receiver_thread = None
        self._lock = threading.Lock()
        self.connection_rejected = False
        self.rejection_reason = None

    def connect(self, timeout=5.0):
        """Connect to server with timeout"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((self.host, self.port))

            # Send Join Request
            packet = bomberman_pb2.Packet()
            packet.join_request.player_id = self.player_id
            send_msg(self.sock, packet.SerializeToString())

            # Receive Server Response
            data = recv_msg(self.sock)
            if not data:
                print(f"[{self.player_id}] Connection closed by server during handshake.")
                return False

            response = bomberman_pb2.Packet()
            response.ParseFromString(data)

            # Store the handshake message
            if response.HasField("server_response"):
                with self._lock:
                    self.messages.append(response.server_response.message)

                if not response.server_response.success:
                    self.connection_rejected = True
                    self.rejection_reason = response.server_response.message
                    self.sock.close()
                    self.sock = None
                    return False

            if response.HasField("server_response") and response.server_response.success:
                self.sock.settimeout(None)  # Remove timeout after successful connection
                self.is_connected = True
                self._running = True
                self._receiver_thread = threading.Thread(target=self._listen)
                self._receiver_thread.daemon = True
                self._receiver_thread.start()
                return True
            else:
                msg = (
                    response.server_response.message
                    if response.HasField("server_response")
                    else "Unknown"
                )
                print(f"[{self.player_id}] Join rejected: {msg}")
                return False
        except Exception as e:
            print(f"[{self.player_id}] Client connection error: {e}")
            return False

    def _listen(self):
        """Background thread to receive updates"""
        while self._running:
            try:
                if not self.sock:
                    break

                data = recv_msg(self.sock)
                if not data:
                    break

                packet = bomberman_pb2.Packet()
                packet.ParseFromString(data)

                with self._lock:
                    if packet.HasField("state_snapshot"):
                        self.latest_snapshot = packet.state_snapshot
                    elif packet.HasField("server_response"):
                        self.messages.append(packet.server_response.message)

            except:
                break

        self.is_connected = False

    def send_action(self, action_type):
        """Send an action to the server"""
        if not self.is_connected or not self.sock:
            return
        packet = bomberman_pb2.Packet()
        packet.client_action.player_id = self.player_id
        packet.client_action.action_type = action_type
        try:
            send_msg(self.sock, packet.SerializeToString())
        except:
            self.is_connected = False

    def get_snapshot_safe(self):
        """Safely get the latest snapshot"""
        with self._lock:
            return self.latest_snapshot

    def get_messages_safe(self):
        """Safely get all messages"""
        with self._lock:
            return self.messages.copy()

    def close(self):
        """Close connection"""
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass


class BaseIntegrationTest(unittest.TestCase):
    """Base class for integration tests"""

    def setUp(self):
        """Set up test environment"""
        # Find an available port for the server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self.server_port = s.getsockname()[1]
        s.close()
        self.server_host = "127.0.0.1"

        # Clean up any existing save file
        self.save_filename = "bomberman_save.pkl"
        if os.path.exists(self.save_filename):
            try:
                os.remove(self.save_filename)
            except OSError:
                pass

        # Patch sys.exit to prevent server from killing test runner
        self.exit_patcher = patch("sys.exit", side_effect=lambda x: None)
        self.mock_exit = self.exit_patcher.start()

        # Config patches to speed up tests
        self.patches = [
            patch("bomberman.room_server.RoomServer.HOST", self.server_host),
            patch("bomberman.room_server.RoomServer.PORT", self.server_port),
            patch("bomberman.room_server.RoomServer.API_PORT", self.server_port + 1),
            # Speed up game start (wait 1s instead of 30s)
            patch(
                "bomberman.room_server.GameEngine.MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE",
                1.0,
            ),
            # Speed up reconnection timeout
            patch("bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT", 3.0),
            # Mock Hub notifications
            patch("requests.post", MagicMock(return_value=MagicMock(status_code=200))),
        ]

        for p in self.patches:
            p.start()

        self.start_server()
        self.clients = []

    def start_server(self):
        """Start the server in a background thread"""
        # If server already exists, stop it gracefully
        self._stop_server_gracefully()

        # Ensure fresh global instance
        import bomberman.room_server.RoomServer as rs_module

        rs_module.server_instance = None

        self.server = RoomServer()

        # Wrapper to catch the Windows OSError when socket closes during accept()
        def safe_server_start():
            try:
                self.server.start()
            except OSError:
                pass  # Ignore socket closure errors during shutdown

        self.server_thread = threading.Thread(target=safe_server_start)
        self.server_thread.daemon = True
        self.server_thread.start()
        time.sleep(0.5)  # Allow server to start

    def tearDown(self):
        """Clean up after test"""
        # Close all clients first
        for client in self.clients:
            try:
                client.close()
            except:
                pass

        # Stop server gracefully
        self._stop_server_gracefully()

        # Stop patches
        self.exit_patcher.stop()
        for p in self.patches:
            try:
                p.stop()
            except:
                pass

        # Clean up save file
        if os.path.exists(self.save_filename):
            try:
                os.remove(self.save_filename)
            except:
                pass

        # Small delay to allow port to be released before next test
        time.sleep(0.2)

    def _stop_server_gracefully(self):
        """
        Helper to stop the server.
        Unblocks accept() by connecting a dummy client, then closes resources.
        """
        if hasattr(self, "server") and self.server and self.server.running:
            self.server.running = False

            # Connect a dummy socket to unblock server_socket.accept()
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                try:
                    s.connect((self.server_host, self.server_port))
                except:
                    pass
                finally:
                    s.close()
            except:
                pass

        # Wait for thread to finish
        if hasattr(self, "server_thread") and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)

        # Cleanup server resources
        if hasattr(self, "server") and self.server:
            try:
                with self.server.clients_lock:
                    for sock in self.server.clients.values():
                        try:
                            sock.close()
                        except:
                            pass
                    self.server.clients.clear()
            except:
                pass

            # Close server socket
            try:
                if self.server.server_socket:
                    self.server.server_socket.close()
            except:
                pass

    def _wait_for_game_start(self, timeout=5.0):
        """Helper to wait until server enters IN_PROGRESS state"""
        start = time.time()
        while time.time() - start < timeout:
            if self.server.engine.state == GameState.IN_PROGRESS:
                return True
            time.sleep(0.1)
        return False

    def _wait_for_game_over(self, timeout=5.0):
        """Helper to wait until server enters GAME_OVER state"""
        start = time.time()
        while time.time() - start < timeout:
            if self.server.engine.state == GameState.GAME_OVER:
                return True
            time.sleep(0.1)
        return False

    def _wait_for_snapshot(self, client, timeout=2.0):
        """Wait for client to receive a snapshot"""
        start = time.time()
        while time.time() - start < timeout:
            if client.get_snapshot_safe() is not None:
                return True
            time.sleep(0.05)
        return False

    def _wait_for_bombs(self, timeout=2.0):
        """Wait for at least one bomb to appear"""
        start = time.time()
        while time.time() - start < timeout:
            if len(self.server.engine.bombs) > 0:
                return True
            time.sleep(0.05)
        return False


# Basic Connection and Join Tests
class TestBasicConnectionFlow(BaseIntegrationTest):
    """Test basic client connection and join functionality"""

    def test_single_client_join(self):
        """Test that a single client can connect and appear in the game"""
        client = HeadlessClient("Enrico", self.server_host, self.server_port)
        self.clients.append(client)

        success = client.connect()
        self.assertTrue(success, "Client should connect successfully")

        # Wait for snapshot
        self._wait_for_snapshot(client)

        # Verify Server State
        self.assertEqual(len(self.server.engine.players), 1)
        self.assertEqual(self.server.engine.players[0].id, "Enrico")

        # Verify Snapshot Grid
        snapshot = client.get_snapshot_safe()
        self.assertIsNotNone(snapshot)
        self.assertIn("E", snapshot.ascii_grid)

    def test_multiple_clients_join(self):
        """Test multiple clients joining in waiting state"""
        names = ["Enrico", "Daniele", "Player"]
        clients = [HeadlessClient(name, self.server_host, self.server_port) for name in names]
        self.clients.extend(clients)

        # Connect all clients
        for client in clients:
            success = client.connect()
            self.assertTrue(success, f"Client {client.player_id} should connect")

        # Verify all players registered
        self.assertEqual(len(self.server.engine.players), 3)
        player_ids = {p.id for p in self.server.engine.players}
        self.assertEqual(player_ids, set(names))

    def test_duplicate_player_id_rejected(self):
        """Test that duplicate player IDs are rejected"""
        client1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        client2 = HeadlessClient("Enrico", self.server_host, self.server_port)
        self.clients.extend([client1, client2])

        self.assertTrue(client1.connect())

        self.assertFalse(client2.connect())
        self.assertTrue(client2.connection_rejected)


# Game State Transitions
class TestGameStateTransitions(BaseIntegrationTest):
    """Test game state transitions (WAITING -> IN_PROGRESS -> GAME_OVER)"""

    def test_game_start_with_two_players(self):
        """Test that game starts when 2 players join"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        # Connect both players
        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game to start
        started = self._wait_for_game_start(timeout=5.0)
        self.assertTrue(started, "Game should transition to IN_PROGRESS")

        # Verify clients received updates
        time.sleep(0.5)
        snapshot1 = p1.get_snapshot_safe()
        snapshot2 = p2.get_snapshot_safe()

        self.assertIsNotNone(snapshot1)
        self.assertIsNotNone(snapshot2)
        self.assertIn("IN_PROGRESS", snapshot1.ascii_grid)
        self.assertIn("IN_PROGRESS", snapshot2.ascii_grid)

    def test_game_rejection_when_in_progress(self):
        """Test that new players cannot join when game is IN_PROGRESS"""
        # Start game with 2 players
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game to start and stabilize
        started = self._wait_for_game_start(timeout=5.0)
        self.assertTrue(started, "Game must start for this test")

        # Try to connect a 3rd player
        p3 = HeadlessClient("Player", self.server_host, self.server_port)
        self.clients.append(p3)
        success = p3.connect()

        # Should be rejected
        self.assertFalse(success, "Should be rejected because game is IN_PROGRESS")
        self.assertTrue(p3.connection_rejected)
        # Check if rejection reason contains expected text
        if p3.rejection_reason:
            self.assertTrue("progress" in p3.rejection_reason.lower())

    def test_game_starts_only_with_minimum_players(self):
        """Test that game doesn't start with only 1 player"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        self.clients.append(p1)

        self.assertTrue(p1.connect())

        # Wait longer than the waiting timeout to ensure it doesn't start
        time.sleep(2.0)

        # Game should still be waiting
        self.assertEqual(self.server.engine.state, GameState.WAITING_FOR_PLAYERS)


# Player Actions and Gameplay
class TestPlayerActions(BaseIntegrationTest):
    """Test player actions during gameplay"""

    def test_player_movement(self):
        """Test that player movement updates position"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game start
        self._wait_for_game_start()
        time.sleep(0.5)

        # Manually move player to a valid spot (1,1)
        p1_obj = next(p for p in self.server.engine.players if p.id == "Enrico")
        p1_obj.position.x = 1
        p1_obj.position.y = 1

        # 1 start + 1 moves = 2
        p1.send_action(bomberman_pb2.GameAction.MOVE_RIGHT)
        # Sleep
        time.sleep(0.2)

        # Verify position changed to (2, 1)
        self.assertEqual(p1_obj.position.x, 2)
        self.assertEqual(p1_obj.position.y, 1)

    def test_bomb_placement(self):
        """Test that bomb placement creates a bomb"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game start and ensure it's IN_PROGRESS
        started = self._wait_for_game_start(timeout=5.0)
        self.assertTrue(started, "Game should start")
        time.sleep(0.5)  # Let game stabilize

        # Place bomb
        p1.send_action(bomberman_pb2.GameAction.PLACE_BOMB)

        # Wait for bomb to appear
        bomb_appeared = self._wait_for_bombs(timeout=2.0)
        self.assertTrue(bomb_appeared, "Bomb should appear after placing")

    def test_bomb_explosion_kills_player(self):
        """Test that bomb explosions can kill players"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game start
        self._wait_for_game_start()
        time.sleep(0.5)

        # Manually force positions to be adjacent
        bomber = next(p for p in self.server.engine.players if p.id == "Enrico")
        victim = next(p for p in self.server.engine.players if p.id == "Daniele")

        bomber.position.x = 1
        bomber.position.y = 1
        victim.position.x = 1
        victim.position.y = 2

        # Place bomb
        p1.send_action(bomberman_pb2.GameAction.PLACE_BOMB)
        time.sleep(0.2)

        # Verify bomb was placed
        initial_bomb_count = len(self.server.engine.bombs)
        self.assertGreater(initial_bomb_count, 0, "Bomb should be placed")

        # Wait for bomb to explode
        time.sleep(3.0)

        # Check that bomb exploded
        final_bomb_count = len(self.server.engine.bombs)
        self.assertEqual(final_bomb_count, 0)

        # Victim should be dead
        self.assertFalse(victim.is_alive)

    def test_concurrent_actions_from_multiple_players(self):
        """Test that multiple players can send actions simultaneously"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game start
        self._wait_for_game_start()
        time.sleep(0.5)

        # Send actions simultaneously
        p1.send_action(bomberman_pb2.GameAction.MOVE_UP)
        p2.send_action(bomberman_pb2.GameAction.MOVE_DOWN)
        time.sleep(0.3)

        # Both actions should be processed
        self.assertEqual(self.server.engine.state, GameState.IN_PROGRESS)


# Reconnection Logic
class TestReconnectionLogic(BaseIntegrationTest):
    """Test server restart and client reconnection"""

    def test_server_saves_state_on_shutdown(self):
        """Test that server saves state when shutting down during active game"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        # Wait for game to start
        self._wait_for_game_start()
        time.sleep(0.5)

        # Shutdown server
        self.server._shutdown()
        self.server_thread.join(timeout=1.0)

        # Verify save file exists
        self.assertTrue(
            os.path.exists(self.save_filename),
            f"Save file {self.save_filename} should exist after shutdown",
        )

    def test_server_loads_state_on_restart(self):
        """Test that server loads saved state on restart"""
        # Start game
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()

        # Shutdown
        self.server._shutdown()
        self.server_thread.join(timeout=1.0)
        p1.close()
        p2.close()

        # Get a new port for restart
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        new_port = s.getsockname()[1]
        s.close()

        # Update port patches
        for p in self.patches:
            try:
                p.stop()
            except:
                pass

        self.server_port = new_port
        self.patches = [
            patch("bomberman.room_server.RoomServer.HOST", self.server_host),
            patch("bomberman.room_server.RoomServer.PORT", self.server_port),
            patch("bomberman.room_server.RoomServer.API_PORT", self.server_port + 1),
            patch(
                "bomberman.room_server.GameEngine.MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE",
                1.0,
            ),
            patch("bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT", 3.0),
            patch("requests.post", MagicMock(return_value=MagicMock(status_code=200))),
        ]

        for p in self.patches:
            p.start()

        # Restart
        self.start_server()

        # Verify state loaded
        self.assertTrue(self.server.is_resumed_game)
        self.assertEqual(len(self.server.expected_players), 2)
        self.assertIn("Daniele", self.server.expected_players)

    def test_player_reconnection_success(self):
        """Test successful player reconnection after server restart"""
        # Start game
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()

        # Shutdown
        self.server._shutdown()
        self.server_thread.join(timeout=1.0)
        p1.close()
        p2.close()

        # Get a new port for restart
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        new_port = s.getsockname()[1]
        s.close()

        # Update port patches
        for p in self.patches:
            try:
                p.stop()
            except:
                pass

        self.server_port = new_port
        self.patches = [
            patch("bomberman.room_server.RoomServer.HOST", self.server_host),
            patch("bomberman.room_server.RoomServer.PORT", self.server_port),
            patch("bomberman.room_server.RoomServer.API_PORT", self.server_port + 1),
            patch(
                "bomberman.room_server.GameEngine.MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE",
                1.0,
            ),
            patch("bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT", 3.0),
            patch("requests.post", MagicMock(return_value=MagicMock(status_code=200))),
        ]

        for p in self.patches:
            p.start()

        # Restart server
        self.start_server()

        # Reconnect Daniele to new port
        p2_new = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.append(p2_new)

        success = p2_new.connect()
        self.assertTrue(success, "Player should be able to reconnect")

        # Verify reconnection message
        time.sleep(0.5)
        messages = p2_new.get_messages_safe()
        welcome_msg = any("back" in m.lower() or "resumed" in m.lower() for m in messages)
        self.assertTrue(welcome_msg, f"Should receive reconnection message. Got: {messages}")

    def test_reconnection_timeout_triggers_restart(self):
        """Test that server restarts if players don't reconnect in time"""
        # Start game
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()

        # Shutdown
        self.server._shutdown()
        self.server_thread.join(timeout=1.0)
        p1.close()
        p2.close()

        # Get a new port for restart
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        new_port = s.getsockname()[1]
        s.close()

        # Update port patches
        for p in self.patches:
            try:
                p.stop()
            except:
                pass

        self.server_port = new_port
        self.patches = [
            patch("bomberman.room_server.RoomServer.HOST", self.server_host),
            patch("bomberman.room_server.RoomServer.PORT", self.server_port),
            patch("bomberman.room_server.RoomServer.API_PORT", self.server_port + 1),
            patch(
                "bomberman.room_server.GameEngine.MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE",
                1.0,
            ),
            patch("bomberman.room_server.RoomServer.SERVER_RECONNECTION_TIMEOUT", 3.0),
            patch("requests.post", MagicMock(return_value=MagicMock(status_code=200))),
        ]

        for p in self.patches:
            p.start()

        # Restart server but don't reconnect players
        self.start_server()

        # Wait for reconnection timeout
        time.sleep(4.0)

        # Server should have restarted game
        self.assertEqual(self.server.engine.state, GameState.WAITING_FOR_PLAYERS)
        self.assertEqual(len(self.server.engine.players), 0)


# Game Over and Restart


class TestGameOverAndRestart(BaseIntegrationTest):
    """Test game over conditions and server restart"""

    def test_game_over_when_one_player_remains(self):
        """Test that game ends when only one player is alive"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()
        time.sleep(0.5)

        # Manually kill one player for testing
        self.server.engine.players[1].is_alive = False
        self.server.engine.check_game_over(verbose=True)

        # Game should be over
        self.assertEqual(self.server.engine.state, GameState.GAME_OVER)

    def test_server_restarts_after_game_over(self):
        """Test that server automatically restarts after game over"""
        # Patch restart interval to be very short
        with patch("bomberman.room_server.RoomServer.GAME_OVER_RESTART_INTERVAL", 0.5):
            p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
            p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
            self.clients.extend([p1, p2])

            self.assertTrue(p1.connect())
            self.assertTrue(p2.connect())

            self._wait_for_game_start()

            # Force game over
            self.server.engine.state = GameState.GAME_OVER

            # Wait for restart loop to catch up
            time.sleep(2.0)

            # Server should have restarted
            self.assertEqual(self.server.engine.state, GameState.WAITING_FOR_PLAYERS)
            self.assertEqual(len(self.server.engine.players), 0)


# Edge Cases and Error Handling
class TestEdgeCases(BaseIntegrationTest):
    """Test edge cases and error conditions"""

    def test_player_disconnect_during_waiting(self):
        """Test that player is removed if they disconnect during waiting"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        self.clients.append(p1)

        self.assertTrue(p1.connect())
        self.assertEqual(len(self.server.engine.players), 1)

        # Disconnect
        p1.close()
        time.sleep(0.5)

        # Player should be removed
        self.assertEqual(len(self.server.engine.players), 0)

    def test_player_disconnect_during_game_marks_dead(self):
        """Test that disconnecting during game marks player as dead"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()

        # Both alive
        self.assertTrue(all(p.is_alive for p in self.server.engine.players))

        # Disconnect one player
        p1.close()
        time.sleep(0.5)

        # Disconnected player should be dead
        quitter = next((p for p in self.server.engine.players if p.id == "Enrico"), None)
        self.assertIsNotNone(quitter)
        self.assertFalse(quitter.is_alive)

    def test_invalid_move_is_ignored(self):
        """Test that invalid moves (into walls) are ignored"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()
        time.sleep(0.5)

        # Try to move into a wall multiple times
        for _ in range(10):
            p1.send_action(bomberman_pb2.GameAction.MOVE_UP)
            time.sleep(0.1)

        # Game should still be running (no crashes)
        self.assertEqual(self.server.engine.state, GameState.IN_PROGRESS)

    def test_multiple_bombs_same_location_prevented(self):
        """Test that multiple bombs cannot be placed at same location"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()
        time.sleep(0.5)

        # Try to place multiple bombs quickly
        p1.send_action(bomberman_pb2.GameAction.PLACE_BOMB)
        p1.send_action(bomberman_pb2.GameAction.PLACE_BOMB)
        time.sleep(0.3)

        # Should only have one bomb
        self.assertLessEqual(len(self.server.engine.bombs), 1)

    def test_quit_action_disconnects_player(self):
        """Test that QUIT action properly disconnects player"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()

        # Send quit action
        p1.send_action(bomberman_pb2.GameAction.QUIT)
        time.sleep(0.5)

        # Player should be disconnected and dead
        self.assertFalse(p1.is_connected)
        quitter = next((p for p in self.server.engine.players if p.id == "Enrico"), None)
        if quitter:
            self.assertFalse(quitter.is_alive)


# Broadcast and State Synchronization
class TestBroadcastAndSync(BaseIntegrationTest):
    """Test that game state is properly broadcast to all clients"""

    def test_all_clients_receive_updates(self):
        """Test that all connected clients receive game state updates"""
        names = ["Enrico", "Daniele", "Player"]
        clients = [HeadlessClient(name, self.server_host, self.server_port) for name in names]
        self.clients.extend(clients)

        # Connect all
        for c in clients:
            self.assertTrue(c.connect())

        # Wait for snapshots
        time.sleep(1.0)

        # All should have received updates
        for c in clients:
            snapshot = c.get_snapshot_safe()
            self.assertIsNotNone(snapshot, f"{c.player_id} should receive snapshot")

    def test_state_consistency_across_clients(self):
        """Test that all clients see the same game state"""
        p1 = HeadlessClient("Enrico", self.server_host, self.server_port)
        p2 = HeadlessClient("Daniele", self.server_host, self.server_port)
        self.clients.extend([p1, p2])

        self.assertTrue(p1.connect())
        self.assertTrue(p2.connect())

        self._wait_for_game_start()
        time.sleep(0.5)

        # Get snapshots
        snap1 = p1.get_snapshot_safe()
        snap2 = p2.get_snapshot_safe()

        self.assertIsNotNone(snap1)
        self.assertIsNotNone(snap2)

        # Both should see the same grid and state
        self.assertIn("IN_PROGRESS", snap1.ascii_grid)
        self.assertIn("IN_PROGRESS", snap2.ascii_grid)

        self.assertEqual(snap1.ascii_grid, snap2.ascii_grid, "Both clients should see the same grid")
