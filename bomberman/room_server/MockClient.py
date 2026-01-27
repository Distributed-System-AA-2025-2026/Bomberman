import socket
import threading
import sys
import os
import time
from bomberman.room_server.gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg
from bomberman.room_server.GameInputHelper import RealTimeInput
from bomberman.room_server.GameStatePersistence import SERVER_RECONNECTION_TIMEOUT

HOST = 'bomberman.romanellas.cloud'  # Server address
PORT = 32612
RECONNECT_INTERVAL = 2  # Seconds between reconnection attempts


class GameClient:
    def __init__(self, player_id):
        self.player_id = player_id
        self.sock = None
        self.running = True
        self.tick_rate = 10  # Default, will be updated by server on connection
        self.is_connected = False
        self.reconnection_attempts = 0
        self.max_reconnection_time = SERVER_RECONNECTION_TIMEOUT
        self.reconnection_start_time = None
        self.server_reset_detected = False  # Track if server is resetting

        # Force Windows terminal to interpret ANSI escape codes
        if os.name == 'nt':
            os.system('')  # Enables ANSI escape codes in Windows terminal

    def connect(self):
        """Attempt to connect to the server."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Create IPv4 TCP socket
            self.sock.settimeout(5.0)  # 5 second timeout for connection
            self.sock.connect((HOST, PORT))
            self.sock.settimeout(None)  # Remove timeout after connection
            print(f"[*] Connected to {HOST}:{PORT}")
            
            # Send Join Request
            packet = bomberman_pb2.Packet()
            packet.join_request.player_id = self.player_id
            send_msg(self.sock, packet.SerializeToString())

            # Wait for Server Response
            data = recv_msg(self.sock)
            if not data:
                print("[!] Server closed connection during handshake.")
                return False

            resp_packet = bomberman_pb2.Packet()
            resp_packet.ParseFromString(data)
            
            if resp_packet.HasField('server_response'):
                if not resp_packet.server_response.success:
                    print(f"[!] Join failed: {resp_packet.server_response.message}")
                    return False
                
                # Successful join/rejoin
                self.tick_rate = resp_packet.server_response.tick_rate
                print(f"[*] {resp_packet.server_response.message}")
                self.is_connected = True
                self.reconnection_attempts = 0
                self.reconnection_start_time = None
                self.server_reset_detected = False  # Reset the flag on successful connection
                
                return True
            return False
            
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print(f"[!] Connection failed: {e}")
            return False

    def attempt_reconnection(self) -> bool:
        """Try to reconnect to the server within the timeout window. Returns True on success, False on timeout."""
        # Server reset detected, do not attempt reconnection
        if self.server_reset_detected:
            print("[!] Server is resetting. Exiting...")
            self.running = False
            return False
        
        if self.reconnection_start_time is None:
            self.reconnection_start_time = time.time()
        
        elapsed = time.time() - self.reconnection_start_time
        
        # Check if timeout exceeded
        if elapsed > self.max_reconnection_time:
            print(f"\n[!] Reconnection timeout ({self.max_reconnection_time}s) exceeded.")
            print("[!] Server appears to be permanently down. Exiting...")
            self.running = False
            return False
        
        remaining = self.max_reconnection_time - elapsed
        self.reconnection_attempts += 1
        print(f"[*] Reconnection attempt #{self.reconnection_attempts} ({remaining:.1f}s remaining)...")
        
        if self.connect():
            print("[*] Successfully reconnected!")
            return True
        
        return False

    def receive_loop(self):
        """Thread that listens for updates from the server."""
        last_reconnect_attempt = 0
        
        try:
            while self.running:
                if not self.is_connected:
                    # Try to reconnect periodically
                    current_time = time.time()
                    if current_time - last_reconnect_attempt >= RECONNECT_INTERVAL:
                        last_reconnect_attempt = current_time
                        if self.attempt_reconnection():
                            continue
                    
                    time.sleep(0.1)
                    continue
                
                try:
                    data = recv_msg(self.sock)
                    if not data:
                        if self.running:  # Only print if still running
                            print("\n[!] Server disconnected.")
                            print(f"[*] Will attempt reconnection for {self.max_reconnection_time}s...")
                        self.is_connected = False
                        continue
                    
                    packet = bomberman_pb2.Packet()
                    packet.ParseFromString(data)

                    # Handle server response (disconnect notifications, etc)
                    if packet.HasField('server_response'):
                        # Check for server reset notification
                        if packet.server_response.message == "SERVER_RESET":
                            print("\n" + "="*60)
                            print("[!] SERVER IS RESTARTING - GAME RESET")
                            print("[!] Please restart your client to join the new game if you wish to play again.")
                            print("="*60)
                            self.server_reset_detected = True
                            self.running = False
                            continue
                        
                        if not packet.server_response.success:
                            if self.running:
                                print(f"\n[!] Server message: {packet.server_response.message}")
                            continue

                    if packet.HasField('state_snapshot'):
                        if self.running:  # Only render if still running
                            self.render(packet.state_snapshot)
                        
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    if self.running:  # Only print if still running
                        print(f"\n[!] Connection lost: {e}")
                        # Only print reconnection message when server is not resetting
                        if not self.server_reset_detected:
                            print(f"[*] Will attempt reconnection for {self.max_reconnection_time}s...")
                    self.is_connected = False
                    
        except Exception as e:
            if self.running:
                print(f"[!] Receive error: {e}")
                self.running = False

    def render(self, snapshot):
        """Clears terminal and prints the game state."""
        output_buffer = "\033[H"  # Move cursor to top-left

        output_buffer += snapshot.ascii_grid
        output_buffer = output_buffer.replace("\n", "\n\033[K") # Clear to end of line after each line
        
        if snapshot.is_game_over:
            output_buffer += "\nGAME OVER - SERVER WILL RESET SOON...\n"
        else:
            status = "[ONLINE]" if self.is_connected else "[RECONNECTING...]"
            output_buffer += f"Player: {self.player_id} | {status} | Controls: WASD (Move), E (Bomb), Q (Quit)\n"

        output_buffer += "\033[J"  # Clear to end of screen
        
        sys.stdout.write(output_buffer)
        sys.stdout.flush()

    def send_action(self, action_type):
        """Send an action to the server (only if connected)."""
        if not self.is_connected:
            return
        
        packet = bomberman_pb2.Packet()
        packet.client_action.player_id = self.player_id
        packet.client_action.action_type = action_type
        
        try:
            send_msg(self.sock, packet.SerializeToString())
        except (BrokenPipeError, OSError):
            self.is_connected = False
            if not self.server_reset_detected:
                print("\n[!] Failed to send action - connection lost")

    def start(self):
        """Start the game client."""
        # Start the Receiver Thread
        receiver_thread = threading.Thread(target=self.receive_loop)
        receiver_thread.daemon = True
        receiver_thread.start()

        # Clear screen
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')

        # Main input loop
        try:
            with RealTimeInput() as input_handler:
                while self.running:
                    # Get input
                    key = input_handler.get_key(timeout=1.0 / self.tick_rate)

                    if not key:
                        continue

                    # Map key to action
                    action = None
                    if key == 'w':
                        action = bomberman_pb2.GameAction.MOVE_UP
                    elif key == 's':
                        action = bomberman_pb2.GameAction.MOVE_DOWN
                    elif key == 'a':
                        action = bomberman_pb2.GameAction.MOVE_LEFT
                    elif key == 'd':
                        action = bomberman_pb2.GameAction.MOVE_RIGHT
                    elif key == 'e':
                        action = bomberman_pb2.GameAction.PLACE_BOMB
                    elif key == 'q':
                        if self.is_connected:
                            self.send_action(bomberman_pb2.GameAction.QUIT)
                        print("\nQuitting...")
                        self.running = False
                        break
                    
                    # Send action
                    if action is not None:
                        self.send_action(action)
        finally:
            # Ensure cleanup happens
            self.running = False
            
            # Give receiver thread a moment to exit cleanly
            time.sleep(0.2)
            
            # Cleanup socket
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass


if __name__ == "__main__":
    player_name = input("Enter Player ID: ")
    client = GameClient(player_name)
    
    if client.connect():
        client.start()
    else:
        print("[!] Could not connect to server. Exiting...")
