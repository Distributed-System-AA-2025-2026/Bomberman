import socket
import threading
import sys
import os
import time
from gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg
from GameInputHelper import RealTimeInput

HOST = '127.0.0.1'
PORT = 5000

class GameClient:
    def __init__(self, player_id):
        self.player_id = player_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.tick_rate = None

    def connect(self):
        try:
            self.sock.connect((HOST, PORT))
            print(f"[*] Connected to {HOST}:{PORT}")
            
            # Send Join Request
            packet = bomberman_pb2.Packet()
            packet.join_request.player_id = self.player_id
            send_msg(self.sock, packet.SerializeToString())

            # Wait for Server Acceptance/Rejection
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
                
                # Successful join
                # Update tick rate from server
                self.tick_rate = resp_packet.server_response.tick_rate
                print(f"[*] Joined successfully: {resp_packet.server_response.message}")
                return True
            return False
        except Exception as e:
            print(f"[!] Connection error: {e}")
            return False

    def receive_loop(self):
        """Thread that listens for updates from the server and prints them."""
        try:
            while self.running:
                data = recv_msg(self.sock)
                if not data:
                    print("\n[!] Server disconnected.")
                    self.running = False
                    # Force exit to kill the input loop
                    os._exit(0)
                
                packet = bomberman_pb2.Packet()
                packet.ParseFromString(data)

                if packet.HasField('state_snapshot'):
                    self.render(packet.state_snapshot)
                    
        except Exception as e:
            if self.running:
                print(f"[!] Receive error: {e}")

    def render(self, snapshot):
        """Clears terminal and prints the new grid."""
        output_buffer = "\033[H"  # ANSI escape codes to clear screen, first part, prevents flickering

        # Append the grid
        output_buffer += snapshot.ascii_grid
        
        if snapshot.is_game_over:
            output_buffer += "\nGAME OVER"
            self.running = False
        else:
            output_buffer += f"Player: {self.player_id} | Controls: WASD (Move), E (Bomb), Q (Quit)"

        print(output_buffer)
        

        output_buffer += "\033[2J"  # ANSI escape codes to clear screen, second part, prevents flickering

    def send_action(self, action_type):
        """Helper to create and send an action packet."""
        packet = bomberman_pb2.Packet()
        packet.client_action.player_id = self.player_id
        packet.client_action.action_type = action_type
        
        try:
            send_msg(self.sock, packet.SerializeToString())
        except OSError:
            self.running = False

    def start(self):
        # Start the Receiver Thread (Background)
        t = threading.Thread(target=self.receive_loop)
        t.daemon = True # Kills this thread if the main program exits
        t.start()

        start_time = time.time()

        # Start the Input Loop (Main Thread - Blocking)
        print("Starting input loop...")
        with RealTimeInput() as input_handler:
            while self.running:
                # Wait a tiny bit for input (1/TICK_RATE seconds)
                key = input_handler.get_key(timeout=1.0/self.tick_rate)

                if not key:
                    continue

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
                    print("Quitting...")
                    self.running = False
                    break
                
                if action is not None:
                    self.send_action(action)
                
                # Sleep briefly to prevent flooding the server if keys are mashing
                elapsed_time = time.time() - start_time
                sleep_duration = max(0, (1.0 / self.tick_rate) - elapsed_time)
                time.sleep(sleep_duration)
        
        self.sock.close()

if __name__ == "__main__":
    player_name = input("Enter Player ID: ")
    client = GameClient(player_name)
    
    if client.connect():
        client.start()