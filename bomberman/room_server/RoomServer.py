import queue
import time
import GameEngine as game_engine
from gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg
import socket
import threading

HOST = "0.0.0.0"
PORT = 5000
MAX_CONNECTIONS = 4  # Maximum number of concurrent player connections


class RoomServer:
    def __init__(self):
        self.engine = game_engine.GameEngine(seed=42)
        self.server_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )  # Create IPv4 TCP socket
        self.server_socket.bind((HOST, PORT))

        # Action queue
        self.action_queue = queue.Queue()

        # Keep track of connected clients
        self.clients = []
        self.clients_lock = threading.Lock()
        self.running = True

    def start(self):
        self.server_socket.listen(MAX_CONNECTIONS)
        print(f"[*] Room Server listening on {HOST}:{PORT}")

        # Start GameLoop thread
        game_thread = threading.Thread(target=self.game_loop)
        game_thread.daemon = True  # Kills this thread if the main program exits
        game_thread.start()

        try:
            while self.running:
                client_socket, addr = self.server_socket.accept()
                print(f"[*] Connection from {addr}")

                with self.clients_lock:
                    self.clients.append(client_socket)

                # Handle client in a new thread
                client_thread = threading.Thread(
                    target=self.handle_client, args=(client_socket, addr)
                )
                client_thread.daemon = True  # Kills this thread if the main program exits
                client_thread.start()

        except KeyboardInterrupt:
            print("[*] Shutting down server...")
            self.running = False

            # Close all client connections
            with self.clients_lock:
                for client in self.clients:
                    try:
                        client.close()
                    except:
                        pass
    
            # Close server socket
            self.server_socket.close()

            # Exit program
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
                    try:
                        # Only allow joining if game is in WAITING_FOR_PLAYERS state
                        if self.engine.state == game_engine.GameState.WAITING_FOR_PLAYERS:
                            self.engine.add_player(player_id=player_id)
                            self._send_response(
                                client_socket, success=True, message=f"Welcome, {player_id}!"
                            )
                            print(f"[+] Player '{player_id}' added successfully. Player count: {len(self.engine.players)}")
                        else:
                            self._send_response(
                                client_socket,
                                success=False,
                                message="Cannot join, game already in progress.",
                            )
                            print("[!] Game already in progress, rejecting new join request.")
                    except Exception as e:
                        print(f"[!] Failed to add player '{player_id}': {e}")
                        self._send_response(client_socket, success=False, message=str(e))

                # Handle Player Action
                elif packet.HasField("client_action"):
                    # Enqueue action for game loop processing
                    action = packet.client_action
                    self.action_queue.put((player_id, action))

        except Exception as e:
            print(f"[ERROR] Exception while handling client {addr}: {e}")

        # Handle client disconnection
        finally:
            with self.clients_lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            client_socket.close()

            # Remove player from game if still in waiting state
            if player_id and self.engine.state == game_engine.GameState.WAITING_FOR_PLAYERS:
                try:
                    self.engine.remove_player(player_id, verbose=True)
                except:
                    pass
                
            print(f"[-] Client {addr} disconnected. Player count: {len(self.engine.players)}.")

    def _send_response(self, client_socket, success: bool, message: str = ""):
        response_packet = bomberman_pb2.Packet()
        response_packet.server_response.success = success
        response_packet.server_response.message = message
        response_packet.server_response.tick_rate = self.engine.tick_rate
        send_msg(client_socket, response_packet.SerializeToString())

    def game_loop(self):
        tick_interval = 1.0 / self.engine.tick_rate

        while self.running:
            start_time = time.time()

            # Process actions from queue
            actions_to_process = []
            while not self.action_queue.empty():
                player_id, proto_action = self.action_queue.get()
                engine_action = self._map_proto_to_engine(proto_action)
                if engine_action:
                    actions_to_process.append(engine_action)

            # Tick the game engine with all collected actions
            self.engine.tick(verbose=False, actions=actions_to_process)

            # Broadcast game state to all clients
            self.broadcast_game()

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
        data = packet.SerializeToString()

        with self.clients_lock:
            for client_socket in self.clients[:]:  # Copy to avoid modification during iteration
                try:
                    send_msg(client_socket, data)
                except Exception as e:
                    print(
                        f"[!] Failed to send game state to a client: {e}, endpoint may be disconnected. Player count: {len(self.engine.players)}"
                    )

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
