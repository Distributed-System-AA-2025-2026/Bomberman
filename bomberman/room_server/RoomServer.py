import queue
import time
import GameEngine as game_engine
from gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg
from GameStatePersistence import *
import socket
import threading

HOST = "0.0.0.0"
PORT = 5000
MAX_CONNECTIONS = 4  # Maximum number of concurrent player connections


class RoomServer:
    def __init__(self):
        # Try to load saved game state
        loaded_state = GameStatePersistence.load_game_state()
        
        # Initialize game engine
        # Check if the game can be resumed
        if loaded_state:
            self.engine, self.last_save_timestamp = loaded_state
            print(f"[*] Resumed game from tick {self.engine.current_tick}")
            self.is_resumed_game = True
            self.reconnection_deadline = time.time() + SERVER_RECONNECTION_TIMEOUT
        else:
            self.engine = game_engine.GameEngine(seed=42)
            self.last_save_timestamp = time.time()
            self.is_resumed_game = False
            self.reconnection_deadline = None

        # Setup server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Create IPv4 TCP socket
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORT))

        # Action queue
        self.action_queue = queue.Queue()

        # Keep track of connected clients and their player ids
        self.clients = {}  # {player_id: client_socket}
        self.clients_lock = threading.Lock()
        self.running = True
        
        # Autosave tracking
        self.ticks_since_save = 0
        
        # Expected players (for reconnection tracking)
        self.expected_players = set(p.id for p in self.engine.players) if self.is_resumed_game else set()

    def start(self):
        self.server_socket.listen(MAX_CONNECTIONS)
        print(f"[*] Room Server listening on {HOST}:{PORT}")
        
        if self.is_resumed_game:
            print(f"[*] Waiting {SERVER_RECONNECTION_TIMEOUT}s for {len(self.expected_players)} players to reconnect...")
            print(f"[*] Expected players: {self.expected_players}")

        # Start GameLoop thread
        game_thread = threading.Thread(target=self.game_loop)
        game_thread.daemon = True
        game_thread.start()

        try:
            while self.running:
                client_socket, addr = self.server_socket.accept()
                print(f"[*] Connection from {addr}")

                # Handle client in a new thread
                client_thread = threading.Thread(
                    target=self.handle_client, args=(client_socket, addr)
                )
                client_thread.daemon = True
                client_thread.start()

        except KeyboardInterrupt:
            print("[*] Shutting down server...")
            self._shutdown()

    def _shutdown(self):
        """Graceful shutdown with state saving."""
        self.running = False
        
        # Save current game state if game is in progress
        if self.engine.state == game_engine.GameState.IN_PROGRESS:
            print("[*] Saving game state before shutdown...")
            GameStatePersistence.save_game_state(self.engine)
        else:
            # Delete save file if game is over or waiting
            GameStatePersistence.delete_save_file()

        # Close all client connections
        with self.clients_lock:
            for player_id, client_socket in list(self.clients.items()):
                try:
                    client_socket.close()
                except:
                    pass
            self.clients.clear()

        # Close server socket
        self.server_socket.close()

        import sys
        sys.exit(0)

    def handle_client(self, client_socket, addr):
        player_id = None

        try:
            while self.running:
                data = recv_msg(client_socket)
                if not data:
                    print(f"[!] No data received from {addr}.")
                    break

                # Parse incoming packet
                packet = bomberman_pb2.Packet()
                packet.ParseFromString(data)

                # Handle Join Request
                if packet.HasField("join_request"):
                    player_id = packet.join_request.player_id
                    
                    # Check if this is a reconnection
                    is_reconnection = player_id in self.expected_players
                    
                    try:
                        if is_reconnection:
                            # Reconnecting player
                            with self.clients_lock:
                                self.clients[player_id] = client_socket
                            self.expected_players.discard(player_id)
                            
                            self._send_response(
                                client_socket, 
                                success=True, 
                                message=f"Welcome back, {player_id}! Game resumed at tick {self.engine.current_tick}."
                            )
                            print(f"[+] Player '{player_id}' reconnected. Waiting for {len(self.expected_players)} more players.")
                            
                            # Send current game state immediately to the reconnecting player
                            self._send_game_state(client_socket)
                            
                        # New player joining during waiting state
                        elif self.engine.state == game_engine.GameState.WAITING_FOR_PLAYERS:
                            self.engine.add_player(player_id=player_id)
                            
                            with self.clients_lock:
                                self.clients[player_id] = client_socket
                            
                            self._send_response(
                                client_socket, 
                                success=True, 
                                message=f"Welcome, {player_id}!"
                            )
                            print(f"[+] Player '{player_id}' joined. Player count: {len(self.engine.players)}")
                            
                        # Game in progress, new player cannot join
                        else:
                            self._send_response(
                                client_socket,
                                success=False,
                                message="Cannot join, game already in progress.",
                            )
                            print(f"[!] Rejected '{player_id}': game in progress")
                            return  # Close connection
                            
                    except Exception as e:
                        print(f"[!] Failed to add player '{player_id}': {e}")
                        self._send_response(client_socket, success=False, message=str(e))
                        return

                # Handle Player Action
                elif packet.HasField("client_action"):
                    action = packet.client_action
                    
                    # Handle QUIT action
                    if action.action_type == bomberman_pb2.GameAction.QUIT:
                        print(f"[*] Player '{player_id}' quit the game")
                        
                        # Mark player as dead if game is in progress
                        if self.engine.state == game_engine.GameState.IN_PROGRESS:
                            player = next((p for p in self.engine.players if p.id == player_id), None)
                            if player:
                                player.is_alive = False
                                print(f"[*] Player '{player_id}' marked as dead")
                                
                                # Check if game should end
                                is_game_over = self.engine.check_game_over(verbose=True)

                                # Check if game over TODO: restart server
                                if is_game_over:
                                    # Broadcast final state
                                    self.broadcast_game()
                                    print("[*] Game ended.")
                        
                        break
                    
                    # Enqueue other actions
                    self.action_queue.put((player_id, action))

        except Exception as e:
            print(f"[ERROR] Exception while handling client {addr}: {e}")

        # Handle client disconnection
        finally:
            with self.clients_lock:
                if player_id and player_id in self.clients:
                    del self.clients[player_id]
            
            try:
                client_socket.close()
            except:
                pass

            # Remove player from game if still in waiting state
            if player_id and self.engine.state == game_engine.GameState.WAITING_FOR_PLAYERS:
                try:
                    self.engine.remove_player(player_id, verbose=True)
                except:
                    pass

            print(f"[-] Client {addr} ({player_id}) disconnected. Active players: {len(self.clients)}")

    def _send_response(self, client_socket, success: bool, message: str = ""):
        """Send a server response to a client."""
        response_packet = bomberman_pb2.Packet()
        response_packet.server_response.success = success
        response_packet.server_response.message = message
        response_packet.server_response.tick_rate = self.engine.tick_rate
        send_msg(client_socket, response_packet.SerializeToString())

    def _send_game_state(self, client_socket):
        """Send current game state to a specific client."""
        snapshot = self.engine.get_ascii_snapshot(verbose=False)
        packet = bomberman_pb2.Packet()
        packet.state_snapshot.ascii_grid = snapshot
        packet.state_snapshot.is_game_over = self.engine.state == game_engine.GameState.GAME_OVER
        
        try:
            send_msg(client_socket, packet.SerializeToString())
        except Exception as e:
            print(f"[!] Failed to send game state: {e}")

    def game_loop(self):
        """Main game loop running at tick_rate."""
        tick_interval = 1.0 / self.engine.tick_rate

        while self.running:
            start_time = time.time()

            # Check reconnection deadline for resumed games
            if self.is_resumed_game and self.reconnection_deadline:
                if time.time() > self.reconnection_deadline:
                    if self.expected_players:
                        print(f"[!] Reconnection timeout. {len(self.expected_players)} players didn't reconnect.")
                        print(f"[!] Starting fresh game...")
                        
                        # Reset to fresh game
                        self.engine = game_engine.GameEngine(seed=42)
                        self.expected_players.clear()
                        GameStatePersistence.delete_save_file()
                        
                        # Disconnect all current clients
                        with self.clients_lock:
                            for player_id, sock in list(self.clients.items()):
                                try:
                                    sock.close()
                                except:
                                    pass
                            self.clients.clear()
                    
                    self.is_resumed_game = False
                    self.reconnection_deadline = None

            # Process actions from queue (unique per player)
            actions_to_process = {}
            while not self.action_queue.empty():
                player_id, proto_action = self.action_queue.get()
                engine_action = self._map_proto_to_engine(proto_action)
                if engine_action:
                    actions_to_process[player_id] = engine_action

            # Tick the game engine
            self.engine.tick(verbose=False, actions=list(actions_to_process.values()))

            # Broadcast game state to all clients
            self.broadcast_game()

            # Autosave logic
            self.ticks_since_save += 1
            if self.engine.state == game_engine.GameState.IN_PROGRESS and self.ticks_since_save >= AUTOSAVE_INTERVAL:
                GameStatePersistence.save_game_state(self.engine)
                self.ticks_since_save = 0

            # Delete save file when game ends
            if self.engine.state == game_engine.GameState.GAME_OVER:
                GameStatePersistence.delete_save_file()

            # Maintain tick rate
            elapsed = time.time() - start_time
            sleep_time = max(0, tick_interval - elapsed)
            time.sleep(sleep_time)

    def broadcast_game(self):
        """Sends the current game snapshot to all connected clients."""
        snapshot = self.engine.get_ascii_snapshot(verbose=False)
        packet = bomberman_pb2.Packet()
        packet.state_snapshot.ascii_grid = snapshot
        packet.state_snapshot.is_game_over = self.engine.state == game_engine.GameState.GAME_OVER
        
        # Add reconnection info if waiting
        if self.is_resumed_game and self.reconnection_deadline and self.expected_players:
            remaining = max(0, self.reconnection_deadline - time.time())
            reconnect_msg = f"\n[WAITING FOR RECONNECTION] {len(self.expected_players)} player(s) missing. Timeout in {remaining:.1f}s\n"
            packet.state_snapshot.ascii_grid += reconnect_msg
        
        data = packet.SerializeToString()

        with self.clients_lock:
            for player_id, client_socket in list(self.clients.items()):
                try:
                    send_msg(client_socket, data)
                except Exception as e:
                    print(f"[!] Failed to send to '{player_id}': {e}")

    def _map_proto_to_engine(self, proto_action) -> game_engine.GameAction | None:
        """Maps a protobuf ClientAction to a GameEngine action."""
        player_id = proto_action.player_id
        action_type = proto_action.action_type

        if action_type == bomberman_pb2.GameAction.MOVE_UP:
            return game_engine.MOVE_PLAYER(player_id, game_engine.Direction.UP)
        elif action_type == bomberman_pb2.GameAction.MOVE_DOWN:
            return game_engine.MOVE_PLAYER(player_id, game_engine.Direction.DOWN)
        elif action_type == bomberman_pb2.GameAction.MOVE_LEFT:
            return game_engine.MOVE_PLAYER(player_id, game_engine.Direction.LEFT)
        elif action_type == bomberman_pb2.GameAction.MOVE_RIGHT:
            return game_engine.MOVE_PLAYER(player_id, game_engine.Direction.RIGHT)
        elif action_type == bomberman_pb2.GameAction.PLACE_BOMB:
            return game_engine.PLACE_BOMB(player_id)
        elif action_type == bomberman_pb2.GameAction.STAY:
            return game_engine.STAY()
        return None


if __name__ == "__main__":
    server = RoomServer()
    server.start()