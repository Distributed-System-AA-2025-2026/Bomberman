"""
Integration tests for gossip deduplication.

Mock boundary: nothing. Real HubServer, real HubSocketHandler, real UDP.

Unit tests verify the deduplication gate (execute_heartbeat_check returns False
for old nonces, _process_message is not called). What they don't test is the
end-to-end effect when the same nonce arrives via multiple real UDP paths —
the typical gossip scenario where fanout creates duplicate deliveries.

The integration value: same nonce+origin sent from two different UDP sockets
(simulating two different forwarders) must produce exactly one state mutation,
not two.
"""

import os
import socket
import time
import pytest

from bomberman.hub_server.gossip import messages_pb2 as pb


def make_server(gossip_port: int):
    os.environ["GOSSIP_PORT"] = str(gossip_port)
    os.environ["HOSTNAME"] = "hub-0.local"
    os.environ["HUB_FANOUT"] = "4"
    os.environ["HUB_DISCOVERY_MODE"] = "manual"

    from bomberman.hub_server.HubServer import HubServer
    server = HubServer("manual")
    # Bind is synchronous in HubSocketHandler.__init__, so the socket is already
    # occupied when HubServer() returns. UDP packets sent before recvfrom starts
    # are kernel-buffered no need to probe the port. A short sleep is enough
    # to let the listener thread reach recvfrom before the test sends traffic.
    time.sleep(0.1)
    return server


def udp_send(msg: pb.GossipMessage, port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(msg.SerializeToString(), ("127.0.0.1", port))
    finally:
        s.close()


def wait_for(condition, timeout: float = 2.0, interval: float = 0.05):
    """
    Poll until condition() returns truthy or timeout expires.

    Replaces fixed time.sleep() before assertions: the listener loop spawns
    a handler thread per message, and on slow schedulers (Windows) that thread
    may not complete within a fixed sleep. Polling makes the test wait exactly
    as long as needed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


class TestDeduplicationViaRealUDP:

    def test_same_nonce_from_two_forwarders_adds_peer_only_once(self):
        """
        PEER_JOIN with the same nonce arrives from forwarder-2 and forwarder-3
        (two different UDP paths, as happens naturally in gossip fanout).
        Peer-1 must appear in HubState exactly once — not duplicated or
        overwritten with corrupted state.
        """
        server = make_server(19450)
        try:
            msg_via_2 = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=2,
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(joining_peer=1),
            )
            msg_via_3 = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=3,  # same nonce, different forwarder
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(joining_peer=1),
            )

            udp_send(msg_via_2, 19450)
            udp_send(msg_via_3, 19450)

            assert wait_for(lambda: server._state.get_peer(1) is not None), \
                "Peer-1 must be registered after PEER_JOIN"

            # Extra wait: let both handler threads complete before checking heartbeat
            time.sleep(0.1)

            peer = server._state.get_peer(1)
            assert peer.heartbeat == 1, (
                f"Heartbeat must be 1 (recorded once), got {peer.heartbeat}. "
                "Duplicate processing may have corrupted state."
            )
        finally:
            server.stop()

    def test_same_nonce_room_activated_adds_room_only_once(self):
        """
        ROOM_ACTIVATED with the same nonce from two forwarders must add the
        room to HubState exactly once. If processed twice, the room would be
        added twice or its state overwritten inconsistently.
        """
        server = make_server(19451)
        try:
            for forwarder in (2, 3):
                msg = pb.GossipMessage(
                    nonce=1, origin=1, forwarded_by=forwarder,
                    timestamp=time.time(),
                    event_type=pb.ROOM_ACTIVATED,
                    room_activated=pb.RoomActivatedPayload(
                        room_id="hub1-0",
                        owner_hub=1,
                        external_port=30001,
                        external_address="example.com",
                    ),
                )
                udp_send(msg, 19451)

            assert wait_for(lambda: server._state.get_room("hub1-0") is not None), \
                "Room must be registered after ROOM_ACTIVATED"

            # Extra wait: let both handler threads complete before counting rooms
            time.sleep(0.1)

            all_rooms = server._state.get_all_rooms()
            room_ids = [r.room_id for r in all_rooms if r.room_id == "hub1-0"]
            assert len(room_ids) == 1, (
                f"Room hub1-0 appears {len(room_ids)} times in state — "
                "duplicate ROOM_ACTIVATED messages were processed more than once."
            )
        finally:
            server.stop()

    def test_higher_nonce_from_same_origin_is_processed(self):
        """
        Deduplication must not block legitimate new messages. A second message
        from the same origin with a higher nonce must be processed normally.
        This confirms the deduplication gate is nonce-based, not origin-based.
        """
        server = make_server(19452)
        try:
            msg1 = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(joining_peer=1),
            )
            msg2 = pb.GossipMessage(
                nonce=2, origin=1, forwarded_by=1,  # higher nonce — must pass
                timestamp=time.time(),
                event_type=pb.PEER_ALIVE,
                peer_alive=pb.PeerAlivePayload(alive_peer=1),
            )

            udp_send(msg1, 19452)
            # Wait for msg1 to be processed before sending msg2, so the peer
            # exists when PEER_ALIVE arrives (otherwise heartbeat check fails)
            assert wait_for(lambda: server._state.get_peer(1) is not None), \
                "Peer-1 must exist after PEER_JOIN before sending PEER_ALIVE"

            udp_send(msg2, 19452)

            assert wait_for(
                lambda: (p := server._state.get_peer(1)) is not None and p.heartbeat == 2
            ), (
                f"Expected heartbeat=2 after two sequential messages, "
                f"got {getattr(server._state.get_peer(1), 'heartbeat', None)}. "
                "The deduplication gate may be blocking valid new messages."
            )
        finally:
            server.stop()

    def test_lower_nonce_duplicate_does_not_overwrite_state(self):
        """
        A stale duplicate (lower nonce) arriving after a newer message must
        be fully dropped — it must not overwrite the heartbeat recorded from
        the newer message.
        """
        server = make_server(19453)
        try:
            msg_new = pb.GossipMessage(
                nonce=10, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(joining_peer=1),
            )
            msg_stale = pb.GossipMessage(
                nonce=3, origin=1, forwarded_by=2,  # stale, lower nonce
                timestamp=time.time(),
                event_type=pb.PEER_JOIN,
                peer_join=pb.PeerJoinPayload(joining_peer=1),
            )

            udp_send(msg_new, 19453)
            assert wait_for(lambda: server._state.get_peer(1) is not None), \
                "Peer-1 must exist after msg_new"

            udp_send(msg_stale, 19453)
            # Give the stale message time to be processed (and wrongly overwrite, if broken)
            time.sleep(0.2)

            peer = server._state.get_peer(1)
            assert peer.heartbeat == 10, (
                f"Stale duplicate overwrote heartbeat. Expected 10, got {peer.heartbeat}. "
                "The deduplication gate is not rejecting lower nonces correctly."
            )
        finally:
            server.stop()