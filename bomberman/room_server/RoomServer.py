import queue
import bomberman.room_server.GameEngine as game_engine
from bomberman.room_server.gossip import bomberman_pb2
from bomberman.room_server.NetworkUtils import send_msg, recv_msg
from bomberman.room_server.GameStatePersistence import *
import time
import socket
import threading
import sys
from fastapi import FastAPI 
import uvicorn
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file 
load_dotenv()

HOST = "0.0.0.0"
PORT = 5000
API_PORT = 8080  # Port for the HTTP API
MAX_CONNECTIONS = 4  # Maximum number of concurrent player connections
GAME_OVER_RESTART_INTERVAL = 5.0  # Seconds to wait before restart

app = FastAPI()
server_instance = None  # Global reference to access the RoomServer instance

@app.get("/status")
def get_game_status():
    """Returns the current status of the GameEngine."""
    if server_instance and server_instance.engine:
        return {
            "status": server_instance.engine.state.name,  # e.g., "WAITING_FOR_PLAYERS"
        }
    return {"status": "ROOM_SERVER_NOT_INITIALIZED"}


class RoomServer:
    def __init__(self):
        global server_instance
        server_instance = self  # Set global reference

        # Hub API Configuration
        # Read from environment variables, hubs already set these when creating the room pods
        self.room_id = os.environ.get("ROOM_ID", "hub0-0")
        self.hub_api_url = os.environ.get(
            "HUB_API_URL", 
            f"https://bomberman.romanellas.cloud"
        )

        print(f"[*] Hub API URL: {self.hub_api_url}")
        print(f"[*] Room ID: {self.room_id}")
        
        self.game_started_notified = False
        self.game_over_notified = False 

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
        
        # Restart tracking
        self.game_over_timestamp = None
        
        # Expected players (for reconnection tracking)
        self.expected_players = set(p.id for p in self.engine.players) if self.is_resumed_game else set()

        # Remove dead expected players (not alive)
        self.expected_players = {pid for pid in self.expected_players if any(p.id == pid and p.is_alive for p in self.engine.players)}

    def start(self):
        self.server_socket.listen(MAX_CONNECTIONS)
        print(f"[*] Room Server listening on {HOST}:{PORT}")

        # Start API server in a separate thread
        api_thread = threading.Thread(
            target=uvicorn.run, 
            kwargs={"app": app, "host": HOST, "port": API_PORT, "log_level": "error"}
        )
        api_thread.daemon = True
        api_thread.start()
        print(f"[*] API Server listening on {HOST}:{API_PORT}")
        
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
        sys.exit(0)

    def _restart_game(self):
        """
        Reset the game server to a fresh state.
        Disconnect all current players.
        """
        print("[*] Restarting server - flushing all connections...")
        
        # Send reset notification to all clients before disconnecting them
        reset_packet = bomberman_pb2.Packet()
        reset_packet.server_response.success = False
        reset_packet.server_response.message = "SERVER_RESET"
        reset_data = reset_packet.SerializeToString()
        
        with self.clients_lock:
            for player_id, sock in list(self.clients.items()):
                try:
                    send_msg(sock, reset_data)
                    time.sleep(0.1)  # Give client time to receive the message
                    sock.close()
                except:
                    pass
            self.clients.clear()
        
        # Create a new game engine
        self.engine = game_engine.GameEngine(seed=None)
        
        # Reset state flags
        self.ticks_since_save = 0
        self.game_over_timestamp = None
        self.is_resumed_game = False
        self.expected_players.clear()
        self.game_started_notified = False
        self.game_over_notified = False  
        
        # Delete the old save file
        GameStatePersistence.delete_save_file()
        print("[*] Server reset complete. Waiting for new players...")

    def handle_client(self, client_socket, addr):
        player_id = None

        # Track if the player successfully joined
        joined_successfully = False 

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
                            
                            # Player joined successfully
                            joined_successfully = True
                            
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
                            
                            # Player joined successfully
                            joined_successfully = True 
                            
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
                        break
                    
                    # Enqueue other actions
                    self.action_queue.put((player_id, action))

        # Handle specific connection errors quietly 
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            pass  
        
        except Exception as e:
            print(f"[ERROR] Exception while handling client {addr}: {e}")

        # Handle client disconnection
        finally:
            with self.clients_lock:
                # Only remove clients if client actually joined successfully
                if joined_successfully and player_id and player_id in self.clients:
                    # Ensure socket matches before deletion
                    if self.clients[player_id] == client_socket:
                        del self.clients[player_id]
            
            try:
                client_socket.close()
            except:
                pass

            # Process disconnection effects on game state
            if joined_successfully and player_id:
                # If in WAITING_FOR_PLAYERS then remove the player entirely
                if self.engine.state == game_engine.GameState.WAITING_FOR_PLAYERS:
                    try:
                        self.engine.remove_player(player_id, verbose=True)
                    except:
                        pass
                
                # If in IN_PROGRESS, mark player as dead
                elif self.engine.state == game_engine.GameState.IN_PROGRESS:
                    try:
                        player = next((p for p in self.engine.players if p.id == player_id), None)
                        if player and player.is_alive:
                            player.is_alive = False
                            print(f"[*] Player '{player_id}' killed due to disconnection.")
                            # Check if this death ends the game
                            self.engine.check_game_over(verbose=True)
                    except Exception as e:
                        print(f"[!] Error processing disconnect for {player_id}: {e}")

            print(f"[-] Client {addr} ({player_id}) disconnected. Active players: {len(self.clients)}")

    def _send_response(self, client_socket, success: bool, message: str = ""):
        """Send a server response to a client."""
        response_packet = bomberman_pb2.Packet()
        response_packet.server_response.success = success
        response_packet.server_response.message = message
        response_packet.server_response.tick_rate = self.engine.tick_rate
        try:
            send_msg(client_socket, response_packet.SerializeToString())
        except:
            pass

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

            # Handle game over and restart
            if self.engine.state == game_engine.GameState.GAME_OVER:
                # Notify hub of game over 
                if not self.game_over_notified:
                    self._notify_hub_game_close()

                # If game over delete save and restart timer
                if self.game_over_timestamp is None:
                    self.game_over_timestamp = time.time()
                    GameStatePersistence.delete_save_file()
                
                # Wait before restarting
                elif time.time() - self.game_over_timestamp > GAME_OVER_RESTART_INTERVAL:
                    self._restart_game()
                    continue 

            # Check reconnection deadline for resumed games
            if self.is_resumed_game and self.reconnection_deadline:
                if time.time() > self.reconnection_deadline:
                    if self.expected_players:
                        print(f"[!] Reconnection timeout. {len(self.expected_players)} players didn't reconnect.")
                        print(f"[!] Starting fresh game...")
                        self._restart_game() 
                        continue
                    
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

            # Check if game started, notify hub if not done already
            if self.engine.state == game_engine.GameState.IN_PROGRESS and not self.game_started_notified:
                self._notify_hub_game_start()

            # Broadcast game state to all clients
            self.broadcast_game()

            # Autosave logic
            self.ticks_since_save += 1
            if self.engine.state == game_engine.GameState.IN_PROGRESS and self.ticks_since_save >= AUTOSAVE_INTERVAL:
                GameStatePersistence.save_game_state(self.engine)
                self.ticks_since_save = 0

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
    
    def _notify_hub_game_start(self):
        """Notifies the Hub Server that the game has started. Attempts only once, hubs already have a fallback mechanism for this."""
        if self.game_started_notified:
            return

        print(f"[*] Game started! Notifying Hub at {self.hub_api_url}...")
        
        # Mark as notified immediately (or in finally) to prevent retries on failure
        self.game_started_notified = True 
        
        try:
            url = f"{self.hub_api_url}/room/{self.room_id}/start"
            # Short timeout to avoid blocking the game loop for too long
            response = requests.post(url, timeout=2) 
            
            if response.status_code == 200:
                print(f"[+] Hub notified successfully (start).")
            else:
                print(f"[!] Hub notification failed with status: {response.status_code}. Ignoring.")
                
        except Exception as e:
            print(f"[!] Error notifying Hub: {e}. Ignoring.")

    def _notify_hub_game_close(self):
        """Notifies the Hub Server that the game has ended. Attempts only once."""
        if self.game_over_notified:
            return

        print(f"[*] Game Over! Notifying Hub at {self.hub_api_url}...")
        
        # Mark as notified immediately to prevent retries on failure
        self.game_over_notified = True 
        
        try:
            url = f"{self.hub_api_url}/room/{self.room_id}/close"
            # Short timeout to avoid blocking the game loop for too long
            response = requests.post(url, timeout=2) 
            
            if response.status_code == 200:
                print(f"[+] Hub notified successfully (close).")
            else:
                print(f"[!] Hub notification (close) failed with status: {response.status_code}. Ignoring.")
                
        except Exception as e:
            print(f"[!] Error notifying Hub (close): {e}. Ignoring.")


if __name__ == "__main__":
    server = RoomServer()
    server.start()