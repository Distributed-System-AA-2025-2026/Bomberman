import time
import threading
import pytest

from bomberman.hub_server.HubSocketHandler import HubSocketHandler
from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.common.ServerReference import ServerReference

BASE_PORT = 19100
A_PORT = BASE_PORT + 1
B_PORT = BASE_PORT + 2
DELIVERY_TIMEOUT = 2.0


# Useful functions for this tests (used by tests)

def make_handler(port: int, received_messages: list, received_senders: list) -> HubSocketHandler:
    """Creates a HubSocketHandler that appends every received message to the given lists."""

    def on_message(msg: pb.GossipMessage, sender: ServerReference):
        received_messages.append(msg)
        received_senders.append(sender)

    handler = HubSocketHandler(port=port, on_message=on_message)
    handler.start()
    return handler


def wait_for_messages(messages: list, expected_count: int, timeout: float = DELIVERY_TIMEOUT) -> bool:
    """Blocks until the list contains expected_count items or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(messages) >= expected_count:
            return True
        time.sleep(0.01)
    return False


def peer_join_message(origin: int, nonce: int) -> pb.GossipMessage:
    return pb.GossipMessage(
        nonce=nonce,
        origin=origin,
        forwarded_by=origin,
        timestamp=time.time(),
        event_type=pb.PEER_JOIN,
        peer_join=pb.PeerJoinPayload(joining_peer=origin)
    )


@pytest.fixture(scope="module")
def node_a():
    messages, senders = [], []
    h = make_handler(BASE_PORT, messages, senders)
    yield h, messages, senders
    h.stop()


@pytest.fixture(scope="module")
def node_b():
    messages, senders = [], []
    h = make_handler(A_PORT, messages, senders)
    yield h, messages, senders
    h.stop()


@pytest.fixture(scope="module")
def node_c():
    messages, senders = [], []
    h = make_handler(B_PORT, messages, senders)
    yield h, messages, senders
    h.stop()


@pytest.fixture(autouse=True)
def clear_messages(node_a, node_b, node_c):
    """Clears received message lists before each test to ensure isolation."""
    _, msgs_a, sndrs_a = node_a
    _, msgs_b, sndrs_b = node_b
    _, msgs_c, sndrs_c = node_c
    msgs_a.clear();
    sndrs_a.clear()
    msgs_b.clear();
    sndrs_b.clear()
    msgs_c.clear();
    sndrs_c.clear()
    yield


class TestMessageDelivery:

    def test_message_sent_by_a_arrives_at_b(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        msg = peer_join_message(origin=0, nonce=1)
        handler_a.send(msg, ServerReference("127.0.0.1", A_PORT))

        assert wait_for_messages(received_b, 1), "Message never arrived at node B"

    def test_received_message_has_correct_nonce(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        msg = peer_join_message(origin=0, nonce=42)
        handler_a.send(msg, ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        assert received_b[0].nonce == 42

    def test_received_message_has_correct_origin(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        msg = peer_join_message(origin=7, nonce=1)
        handler_a.send(msg, ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        assert received_b[0].origin == 7

    def test_received_message_has_correct_event_type(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        msg = peer_join_message(origin=0, nonce=1)
        handler_a.send(msg, ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        assert received_b[0].event_type == pb.PEER_JOIN

    def test_sender_address_is_loopback(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, senders_b = node_b

        handler_a.send(peer_join_message(0, 1), ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        assert senders_b[0].address == "127.0.0.1"

    def test_sender_port_is_source_port_of_socket(self, node_a, node_b):
        """
        The sender port in the callback is the ephemeral source port of the UDP
        datagram — NOT the listening port of node_a. This is expected UDP behavior.
        We verify that a ServerReference is provided (not None) and the port is > 0.
        """
        handler_a, _, _ = node_a
        _, received_b, senders_b = node_b

        handler_a.send(peer_join_message(0, 1), ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        assert senders_b[0] is not None
        assert senders_b[0].port > 0


class TestProtobufRoundTrip:

    @pytest.mark.parametrize("message,expected_type", [
        (
                pb.GossipMessage(
                    nonce=1, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.PEER_JOIN,
                    peer_join=pb.PeerJoinPayload(joining_peer=0)
                ),
                pb.PEER_JOIN
        ),
        (
                pb.GossipMessage(
                    nonce=2, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.PEER_LEAVE,
                    peer_leave=pb.PeerLeavePayload(leaving_peer=0)
                ),
                pb.PEER_LEAVE
        ),
        (
                pb.GossipMessage(
                    nonce=3, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.PEER_ALIVE,
                    peer_alive=pb.PeerAlivePayload(alive_peer=0)
                ),
                pb.PEER_ALIVE
        ),
        (
                pb.GossipMessage(
                    nonce=4, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.PEER_SUSPICIOUS,
                    peer_suspicious=pb.PeerSuspiciousPayload(suspicious_peer=2)
                ),
                pb.PEER_SUSPICIOUS
        ),
        (
                pb.GossipMessage(
                    nonce=5, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.PEER_DEAD,
                    peer_dead=pb.PeerDeadPayload(dead_peer=3)
                ),
                pb.PEER_DEAD
        ),
        (
                pb.GossipMessage(
                    nonce=6, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.ROOM_ACTIVATED,
                    room_activated=pb.RoomActivatedPayload(
                        room_id="hub0-0", owner_hub=0, external_port=30001, external_address="example.com"
                    )
                ),
                pb.ROOM_ACTIVATED
        ),
        (
                pb.GossipMessage(
                    nonce=7, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.ROOM_STARTED,
                    room_started=pb.RoomStartedPayload(room_id="hub0-0")
                ),
                pb.ROOM_STARTED
        ),
        (
                pb.GossipMessage(
                    nonce=8, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.ROOM_CLOSED,
                    room_closed=pb.RoomClosedPayload(room_id="hub0-0")
                ),
                pb.ROOM_CLOSED
        ),
        (
                pb.GossipMessage(
                    nonce=9, origin=0, forwarded_by=0, timestamp=time.time(),
                    event_type=pb.ROOM_PLAYER_JOINED,
                    room_player_joined=pb.RoomPlayerJoined(room_id="hub0-0")
                ),
                pb.ROOM_PLAYER_JOINED
        ),
    ])
    def test_event_type_survives_udp_transport(self, node_a, node_b, message, expected_type):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        handler_a.send(message, ServerReference("127.0.0.1", A_PORT))

        assert wait_for_messages(received_b, 1), f"Message of type {expected_type} never arrived"
        assert received_b[0].event_type == expected_type

    def test_room_activated_payload_fields_survive_transport(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        msg = pb.GossipMessage(
            nonce=1, origin=0, forwarded_by=0, timestamp=time.time(),
            event_type=pb.ROOM_ACTIVATED,
            room_activated=pb.RoomActivatedPayload(
                room_id="hub3-7",
                owner_hub=3,
                external_port=31234,
                external_address="bomberman.example.com"
            )
        )
        handler_a.send(msg, ServerReference("127.0.0.1", A_PORT))

        wait_for_messages(received_b, 1)
        payload = received_b[0].room_activated
        assert payload.room_id == "hub3-7"
        assert payload.owner_hub == 3
        assert payload.external_port == 31234
        assert payload.external_address == "bomberman.example.com"


class TestSendToMany:

    def test_message_delivered_to_all_recipients(self, node_a, node_b, node_c):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b
        _, received_c, _ = node_c

        msg = peer_join_message(origin=0, nonce=1)
        handler_a.send_to_many(msg, [
            ServerReference("127.0.0.1", A_PORT),
            ServerReference("127.0.0.1", B_PORT),
        ])

        assert wait_for_messages(received_b, 1), "Node B did not receive message"
        assert wait_for_messages(received_c, 1), "Node C did not receive message"

    def test_send_to_many_with_empty_list_does_not_raise(self, node_a):
        handler_a, _, _ = node_a
        # Should complete silently — no peers, no error
        handler_a.send_to_many(peer_join_message(0, 1), [])

    def test_each_recipient_gets_exactly_one_copy(self, node_a, node_b, node_c):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b
        _, received_c, _ = node_c

        handler_a.send_to_many(peer_join_message(0, 99), [
            ServerReference("127.0.0.1", A_PORT),
            ServerReference("127.0.0.1", B_PORT),
        ])

        wait_for_messages(received_b, 1)
        wait_for_messages(received_c, 1)
        time.sleep(0.1)  # Extra wait to catch spurious duplicates

        assert len(received_b) == 1
        assert len(received_c) == 1


class TestMalformedDataResilience:

    def test_garbage_bytes_do_not_crash_handler(self, node_a, node_b):
        """
        Node A sends raw garbage bytes directly via socket (not through HubSocketHandler.send,
        which always serializes valid protobuf). Node B must not crash.
        """
        import socket

        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        # Send garbage directly via raw socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"\xff\xfe\xfd\x00\x01\x02garbage", ("127.0.0.1", A_PORT))
        sock.close()

        time.sleep(0.2)
        assert received_b == [], "Garbage should not be interpreted as a valid message"

    def test_handler_processes_valid_message_after_receiving_garbage(self, node_a, node_b):
        """
        This is the critical resilience test: after receiving malformed data,
        the handler must continue working normally.
        """
        import socket

        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        # Step 1: inject garbage
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"this is not protobuf", ("127.0.0.1", A_PORT))
        sock.close()
        time.sleep(0.1)

        # Step 2: send a valid message
        handler_a.send(peer_join_message(0, 1), ServerReference("127.0.0.1", A_PORT))

        assert wait_for_messages(received_b, 1), \
            "Handler stopped working after receiving malformed data"

    def test_empty_datagram_is_parsed_as_default_message(self, node_a, node_b):
        """
        Empty datagram should be rejected
        """
        import socket

        _, received_b, _ = node_b

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"", ("127.0.0.1", BASE_PORT + 1))
        sock.close()

        time.sleep(0.2)
        assert received_b == [], (
            "Empty datagram must not reach the callback — "
            "if this fails, the nonce=0 ghost message bug is back"
        )


class TestConcurrentDelivery:

    def test_multiple_rapid_messages_all_arrive(self, node_a, node_b):
        handler_a, _, _ = node_a
        _, received_b, _ = node_b

        count = 20
        for nonce in range(1, count + 1):
            handler_a.send(peer_join_message(0, nonce), ServerReference("127.0.0.1", A_PORT))

        assert wait_for_messages(received_b, count, timeout=3.0), \
            f"Only {len(received_b)}/{count} messages arrived"

    def test_messages_from_multiple_senders_all_arrive(self, node_a, node_b, node_c):
        """
        B and C both send to A concurrently. A must receive from both.
        """
        handler_a, received_a, _ = node_a
        handler_b, _, _ = node_b
        handler_c, _, _ = node_c

        dest = ServerReference("127.0.0.1", BASE_PORT)

        t1 = threading.Thread(target=lambda: handler_b.send(peer_join_message(1, 1), dest))
        t2 = threading.Thread(target=lambda: handler_c.send(peer_join_message(2, 1), dest))
        t1.start();
        t2.start()
        t1.join();
        t2.join()

        assert wait_for_messages(received_a, 2), \
            f"Node A only received {len(received_a)}/2 messages from concurrent senders"
        origins = {m.origin for m in received_a}
        assert origins == {1, 2}
