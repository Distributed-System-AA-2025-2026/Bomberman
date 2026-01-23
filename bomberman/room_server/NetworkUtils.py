import struct
import socket
from typing import Optional


def send_msg(sock: socket.socket, msg_bytes: bytes):
    """Prefixes message with 4-byte big-endian length and then sends it."""
    # >I means big-endian unsigned int (4 bytes)
    length_prefix = struct.pack(">I", len(msg_bytes))
    sock.sendall(length_prefix + msg_bytes)


def recv_msg(sock: socket.socket) -> Optional[bytes]:
    """Reads 4 bytes for length, then reads the payload."""
    # Read the length prefix
    raw_len = _recv_all(sock, 4)
    if not raw_len:
        return None

    msg_len = struct.unpack(">I", raw_len)[0]

    # Read the actual message data
    return _recv_all(sock, msg_len)


def _recv_all(sock: socket.socket, n: int) -> Optional[bytes]:
    """Helper to ensure we get exactly n bytes."""
    data = b""
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data += packet
    return data
