import socket
from gossip import bomberman_pb2
from NetworkUtils import send_msg, recv_msg

HOST = '127.0.0.1'
PORT = 5000

def run_client(player_name):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # Create IPv4 TCP socket
        sock.connect((HOST, PORT))
        print(f"[*] Connected to server at {HOST}:{PORT}")

        # Create Join Request
        packet = bomberman_pb2.Packet()
        packet.join_request.player_id = player_name

        # Send (Serialize -> Add Length Header -> Send)
        send_msg(sock, packet.SerializeToString())
        print(f"[*] Sent join request for '{player_name}'...")

        # Receive Response
        response_data = recv_msg(sock)
        if response_data:
            resp_packet = bomberman_pb2.Packet()
            resp_packet.ParseFromString(response_data)

            if resp_packet.HasField('server_response'):
                resp = resp_packet.server_response
                if resp.success:
                    print(f"[SUCCESS] Server says: {resp.message}")
                else:
                    print(f"[FAILED] Server Error: {resp.error}")
        
        sock.close()

    except ConnectionRefusedError:
        print("[!] Could not connect. Is the server running?")

if __name__ == "__main__":
    name = input("Enter your Player ID: ")
    run_client(name)