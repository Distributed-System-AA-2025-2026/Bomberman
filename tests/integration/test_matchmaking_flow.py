import os
import socket
import time
import pytest

from bomberman.hub_server.gossip import messages_pb2 as pb
from bomberman.common.RoomState import RoomStatus


def make_server(gossip_port: int):
    os.environ["GOSSIP_PORT"] = str(gossip_port)
    os.environ["HOSTNAME"] = "hub-0.local"
    os.environ["HUB_FANOUT"] = "4"
    os.environ["HUB_DISCOVERY_MODE"] = "manual"

    from bomberman.hub_server.HubServer import HubServer
    server = HubServer("manual")
    time.sleep(0.1)
    return server


def udp_send(msg: pb.GossipMessage, port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(msg.SerializeToString(), ("127.0.0.1", port))
    finally:
        s.close()
    time.sleep(1)

class TestRoomFilledViaGossip:
    """
    ROOM_PLAYER_JOINED messages arrive via UDP (as they would from the room
    server reporting players joining). Once player_count reaches max_players,
    the room is no longer joinable and matchmaking must activate a new one.
    """

    def test_room_full_via_gossip_triggers_new_room_activation(self):
        """
        Send max_players ROOM_PLAYER_JOINED messages for room hub0-0 via UDP.
        The next get_or_activate_room() call must return a different room
        because hub0-0 is now full (player_count == max_players).
        """
        server = make_server(19460)
        try:
            # Activate the first room so it's in HubState
            first_room = server.get_or_activate_room()
            assert first_room is not None
            first_room_id = first_room.room_id
            # get_or_activate_room already incremented player_count by 1
            players_already_counted = 1
            max_players = first_room.max_players

            # Send ROOM_PLAYER_JOINED to fill the room via gossip
            # Each message must have a unique nonce (deduplication)
            for i in range(players_already_counted, max_players):
                msg = pb.GossipMessage(
                    nonce=100 + i, origin=1, forwarded_by=1,
                    timestamp=time.time(),
                    event_type=pb.ROOM_PLAYER_JOINED,
                    room_player_joined=pb.RoomPlayerJoined(room_id=first_room_id),
                )
                udp_send(msg, 19460)

            time.sleep(1)

            assert not first_room.is_joinable, (
                f"Room {first_room_id} should be full after {max_players} players, "
                f"got player_count={first_room.player_count}"
            )

            # Next matchmaking call must activate a new room
            next_room = server.get_or_activate_room()
            assert next_room is not None, "A new room must be activated when current is full"
            assert next_room.room_id != first_room_id, (
                f"Matchmaking returned the full room {first_room_id} instead of activating a new one. "
                "get_or_activate_room() may not be checking is_joinable correctly after gossip updates."
            )
        finally:
            server.stop()

    def test_player_count_incremented_by_each_gossip_message(self):
        """
        Each distinct ROOM_PLAYER_JOINED message (unique nonce) must increment
        player_count by exactly 1. Verifies the gossip → state update chain
        produces the correct count, not just a boolean full/not-full.
        """
        server = make_server(19461)
        try:
            first_room = server.get_or_activate_room()
            room_id = first_room.room_id
            count_after_matchmaking = first_room.player_count  # already 1

            # Send 2 more distinct ROOM_PLAYER_JOINED
            for i in range(2):
                msg = pb.GossipMessage(
                    nonce=200 + i, origin=1, forwarded_by=1,
                    timestamp=time.time(),
                    event_type=pb.ROOM_PLAYER_JOINED,
                    room_player_joined=pb.RoomPlayerJoined(room_id=room_id),
                )
                udp_send(msg, 19461)
                time.sleep(0.2)

            time.sleep(0.2)

            expected = count_after_matchmaking + 2
            assert first_room.player_count == expected, (
                f"Expected player_count={expected}, got {first_room.player_count}. "
                "Each ROOM_PLAYER_JOINED gossip must increment the counter exactly once."
            )
        finally:
            server.stop()

    def test_duplicate_gossip_does_not_double_count_player(self):
        """
        The same ROOM_PLAYER_JOINED nonce arriving twice (two forwarders)
        must increment player_count only once — deduplication must apply
        to player counting too, not just to peer state updates.
        """
        server = make_server(19462)
        try:
            first_room = server.get_or_activate_room()
            room_id = first_room.room_id
            count_after_matchmaking = first_room.player_count

            # Same nonce, two different forwarders — simulates gossip fanout
            for forwarder in (2, 3):
                msg = pb.GossipMessage(
                    nonce=300, origin=1, forwarded_by=forwarder,
                    timestamp=time.time(),
                    event_type=pb.ROOM_PLAYER_JOINED,
                    room_player_joined=pb.RoomPlayerJoined(room_id=room_id),
                )
                udp_send(msg, 19462)

            time.sleep(0.2)

            assert first_room.player_count == count_after_matchmaking + 1, (
                f"Duplicate ROOM_PLAYER_JOINED (same nonce, two forwarders) counted twice. "
                f"Expected {count_after_matchmaking + 1}, got {first_room.player_count}."
            )
        finally:
            server.stop()

class TestRemoteRoomAvailableForMatchmaking:
    """
    A remote hub broadcasts ROOM_ACTIVATED via UDP. The local hub must add
    that room to HubState, making it available for local matchmaking.
    This verifies the gossip-based room sharing works end-to-end.
    """

    def test_remote_room_received_via_gossip_is_returned_by_matchmaking(self):
        """
        No local rooms are activated. A remote ROOM_ACTIVATED arrives via UDP.
        The local matchmaking must return that remote room.
        """
        server = make_server(19470)
        try:
            # Confirm no joinable room exists yet
            assert server._state.get_active_room() is None

            msg = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.ROOM_ACTIVATED,
                room_activated=pb.RoomActivatedPayload(
                    room_id="hub1-0",
                    owner_hub=1,
                    external_port=30001,
                    external_address="10.0.0.1",
                ),
            )
            udp_send(msg, 19470)
            time.sleep(0.15)

            room = server._state.get_active_room()
            assert room is not None, (
                "Remote ROOM_ACTIVATED received via gossip must add the room to HubState "
                "and make it available for matchmaking."
            )
            assert room.room_id == "hub1-0"
            assert room.owner_hub_index == 1
            assert room.status == RoomStatus.ACTIVE
        finally:
            server.stop()

    def test_remote_room_is_joinable_for_matchmaking(self):
        """
        get_or_activate_room() must return the remote room when it's the only
        joinable room. Confirms the matchmaking endpoint would serve remote rooms.
        """
        server = make_server(19471)
        try:
            msg = pb.GossipMessage(
                nonce=1, origin=1, forwarded_by=1,
                timestamp=time.time(),
                event_type=pb.ROOM_ACTIVATED,
                room_activated=pb.RoomActivatedPayload(
                    room_id="hub1-0",
                    owner_hub=1,
                    external_port=30001,
                    external_address="10.0.0.1",
                ),
            )
            udp_send(msg, 19471)
            time.sleep(0.15)

            result = server.get_or_activate_room()
            assert result is not None, "get_or_activate_room() must return the remote room"
            assert result.room_id == "hub1-0", (
                f"Expected remote room hub1-0, got {result.room_id}. "
                "Matchmaking is not considering gossip-activated remote rooms."
            )
        finally:
            server.stop()