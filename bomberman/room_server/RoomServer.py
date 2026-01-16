import GameEngine as game_engine
from gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg
import socket
import threading

HOST = '0.0.0.0'
PORT = 5000

MAX_CONNECTIONS = 4 # Maximum number of concurrent player connections

class RoomServer:
    def __init__(self):
        self.engine = game_engine.GameEngine(seed=42)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Create IPv4 TCP socket
        self.server_socket.bind((HOST, PORT))

    def start(self):
        self.server_socket.listen(MAX_CONNECTIONS)
        print(f"[*] Room Server listening on {HOST}:{PORT}")

        while True:
            client_socket, addr = self.server_socket.accept()
            print(f"[*] Accepted connection from {addr}")
            client_thread = threading.Thread(target=self.handle_client, args=(client_socket,addr))
            client_thread.start()

    def handle_client(self, client_socket, addr):
        print(f"[*] New Connection from {addr}")

        try:
            data = recv_msg(client_socket)

            if not data:
                print(f"[!] No data received from {addr}. Closing connection.")
                return
            
            # Parse incoming packet
            packet = bomberman_pb2.Packet()
            packet.ParseFromString(data)

            if packet.HasField('join_request'):
                player_id = packet.join_request.player_id
                print(f"[*] Join request from player '{player_id}'")

                try:
                    # Attempt to add player to the game
                    self.engine.add_player(player_id)

                    # Send success response
                    response_packet = bomberman_pb2.Packet()
                    response_packet.server_response.success = True
                    response_packet.server_response.message = f"Welcome, {player_id}!"
                    send_msg(client_socket, response_packet.SerializeToString())

                    print(f"[+] Player '{player_id}' added successfully.")

                except Exception as e:
                    print(f"[!] Failed to add player '{player_id}': {e}")
                    response_packet = bomberman_pb2.Packet()
                    response_packet.server_response.success = False
                    response_packet.server_response.error = str(e)
                    send_msg(client_socket, response_packet.SerializeToString())
                    return                   
        except Exception as e:
            print(f"[ERROR] Exception while handling client {addr}: {e}")
        finally:
            client_socket.close()


   

if __name__ == "__main__":
    server = RoomServer()
    server.start()
    