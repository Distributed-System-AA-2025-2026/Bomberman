import os
import socket
import time
import pytest

from bomberman.hub_server.gossip import messages_pb2 as pb


def make_server(gossip_port: int):
    """Instantiate a real HubServer. No mocks."""
    os.environ["GOSSIP_PORT"] = str(gossip_port)
    os.environ["HOSTNAME"] = "hub-0.local"
    os.environ["HUB_FANOUT"] = "4"
    os.environ["HUB_DISCOVERY_MODE"] = "manual"

    from bomberman.hub_server.HubServer import HubServer
    server = HubServer("manual")
    time.sleep(0.1)  # let the listener thread bind and start
    return server


def udp_send(msg: pb.GossipMessage, port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(msg.SerializeToString(), ("127.0.0.1", port))
    finally:
        s.close()


class TestSelfDefenseFlow:
    """
    When hub-0 receives a PEER_SUSPICIOUS message naming itself as suspicious,
    it must respond with a PEER_ALIVE broadcast. We verify this by checking
    that last_used_nonce increases (every broadcast consumes a nonce).
    """

    def test_suspicious_for_self_triggers_alive_broadcast(self):
        server = make_server(19400)
        try:
            nonce_before = server.last_used_nonce

            msg = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.PEER_SUSPICIOUS,
                peer_suspicious=pb.PeerSuspiciousPayload(suspicious_peer=0),
            )
            udp_send(msg, 19400)
            time.sleep(0.15)

            assert server.last_used_nonce > nonce_before, (
                "PEER_SUSPICIOUS for self must trigger a PEER_ALIVE broadcast "
                "(nonce must increase). Check HubServer._handle_peer_suspicious "
                "index comparison or _broadcast_peer_alive wiring."
            )
        finally:
            server.stop()

    def test_suspicious_for_other_peer_does_not_trigger_broadcast(self):
        """
        Hub-0 must NOT respond when the suspicious peer is someone else.
        Only the accused hub defends itself.
        """
        server = make_server(19401)
        try:
            nonce_before = server.last_used_nonce

            msg = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.PEER_SUSPICIOUS,
                peer_suspicious=pb.PeerSuspiciousPayload(suspicious_peer=5),
            )
            udp_send(msg, 19401)
            time.sleep(0.15)

            assert server.last_used_nonce == nonce_before, (
                "PEER_SUSPICIOUS for another peer must NOT trigger a broadcast "
                "from hub-0. Check the index comparison in _handle_peer_suspicious."
            )
        finally:
            server.stop()


class TestLastSeenUpdatedByGossip:
    """
    A peer that sends gossip should have its last_seen refreshed.
    FailureDetector must then see the peer as healthy and not suspect it.
    """
    def test_peer_sending_gossip_is_not_suspected(self):
        server = make_server(19410)
        try:
            # Simulate peer-1 sending a PEER_ALIVE gossip to hub-0
            msg = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.PEER_ALIVE,
                peer_alive=pb.PeerAlivePayload(alive_peer=1),
            )
            udp_send(msg, 19410)
            time.sleep(0.1)

            peer = server._state.get_peer(1)
            assert peer is not None, "Peer-1 must be registered after sending gossip"

            # last_seen must be recent (within last second)
            assert time.time() - peer.last_seen < 1.0, (
                "last_seen was not updated by incoming gossip. "
                "Check HubState.mark_forward_peer_as_alive wiring in "
                "HubServer._on_gossip_message."
            )

            # Run the failure detector manually — peer must NOT be suspected
            server._failure_detector._check_peers()

            assert peer.status != "suspected", (
                "A peer that just sent gossip was suspected by FailureDetector. "
                "last_seen is not being updated correctly from incoming gossip."
            )
        finally:
            server.stop()

    def test_peer_that_stops_sending_gossip_eventually_gets_suspected(self):
        """
        Verify the positive case: if last_seen is stale, FailureDetector
        does suspect the peer. This confirms the detector is actually running
        and that the previous test is meaningful (not vacuously passing).
        """
        server = make_server(19411)
        try:
            # Register peer-1 manually with a stale last_seen
            server._ensure_peer_exists(1)
            stale_time = time.time() - (server._failure_detector.SUSPECT_TIMEOUT + 5)
            server._state.get_peer(1).last_seen = stale_time

            server._failure_detector._check_peers()

            assert server._state.get_peer(1).status == "suspected", (
                "A peer with stale last_seen should have been suspected. "
                "The failure detector or last_seen tracking may be broken."
            )
        finally:
            server.stop()