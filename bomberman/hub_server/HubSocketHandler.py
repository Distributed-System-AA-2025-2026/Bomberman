import socket
import threading
from typing import Callable, Literal

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.hub_server.hublogging import print_console

BUFFER_SIZE = 65535  # max UDP datagram size

# Type alias per il callback
MessageHandler = Callable[[pb.GossipMessage, ServerReference], None]
LoggingFunction = Callable[[str, Literal['Error', 'Gossip', 'Info', 'FailureDetector', 'Error']], None]


class HubSocketHandler:
    _socket: socket.socket
    _port: int
    _on_message: MessageHandler
    _running: bool
    _listener_thread: threading.Thread
    _logging: LoggingFunction

    def __init__(self, port: int, on_message: MessageHandler, logging: LoggingFunction = print_console):
        self._on_message = on_message
        self._running = False
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("0.0.0.0", port))
        self._logging = logging

    def start(self):
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop(self):
        self._running = False
        self._socket.close()

    def _listen_loop(self):
        while self._running:
            try:
                data, addr = self._socket.recvfrom(BUFFER_SIZE)
                handler_thread = threading.Thread(
                    target=self._handle_message,
                    args=(data, addr),
                    daemon=True
                )
                handler_thread.start()
            except OSError:
                break

    def _handle_message(self, data: bytes, addr: tuple[str, int]):
        """Parsing and callback """

        if self._on_message is None:
            raise TypeError

        try:
            message = pb.GossipMessage()
            message.ParseFromString(data)
            sender = ServerReference(addr[0], addr[1])
            self._on_message(message, sender)
        except Exception as e:
            print(f"[HubSocketHandler] Invalid message from {addr}: {e}")

    def send(self, message: pb.GossipMessage, addr: ServerReference):
        """Invia un messaggio a un peer"""
        try:
            data: bytes = message.SerializeToString()
            dest = (addr.address, addr.port)
            self._socket.sendto(data, dest)
        except socket.gaierror as e:
            self._logging(f"DNS resolution failed for {addr.address}: {e}", 'Error')
        except OSError as e:
            self._logging(f"Failed to send to {addr.address}:{addr.port}", 'Error')

    def send_to_many(self, message: pb.GossipMessage, addrs: list[ServerReference]):
        """Invia un messaggio a più peer"""
        data = message.SerializeToString()
        for addr in addrs:
            try:
                dest = (addr.address, addr.port)
                self._socket.sendto(data, dest)
            except socket.gaierror as e:
                print(f"[HubSocketHandler][Warning] DNS resolution failed for {addr.address}: {e}")
            except OSError as e:
                print(f"[HubSocketHandler][Warning] Failed to send to {addr.address}:{addr.port}: {e}")