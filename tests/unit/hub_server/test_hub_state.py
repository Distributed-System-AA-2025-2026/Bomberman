import pytest

from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.HubPeer import HubPeer
from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus


class TestHubStatePeerManagement:

    def _make_peer(self, index, addr="10.0.0.1", port=9000):
        return HubPeer(ServerReference(addr, port + index), index)

    def test_add_and_retrieve_peer(self):
        state = HubState()
        peer = self._make_peer(0)
        state.add_peer(peer)
        assert state.get_peer(0) is peer

    def test_get_nonexistent_peer_returns_none(self):
        state = HubState()
        assert state.get_peer(0) is None

    def test_get_peer_negative_index_raises(self):
        state = HubState()
        with pytest.raises(ValueError):
            state.get_peer(-1)

    def test_add_peer_with_gap_fills_with_none(self):
        state = HubState()
        peer = self._make_peer(3)
        state.add_peer(peer)
        assert state.get_peer(0) is None
        assert state.get_peer(1) is None
        assert state.get_peer(2) is None
        assert state.get_peer(3) is peer

    def test_add_peer_overwrites_existing(self):
        state = HubState()
        peer1 = self._make_peer(0, addr="1.1.1.1")
        peer2 = self._make_peer(0, addr="2.2.2.2")
        state.add_peer(peer1)
        state.add_peer(peer2)
        assert state.get_peer(0) is peer2

    def test_remove_peer_marks_as_dead(self):
        state = HubState()
        state.add_peer(self._make_peer(0))
        state.remove_peer(0)
        assert state.get_peer(0).status == 'dead'

    def test_remove_peer_out_of_range_raises(self):
        state = HubState()
        with pytest.raises(ValueError):
            state.remove_peer(0)

    def test_remove_peer_negative_index_raises(self):
        state = HubState()
        with pytest.raises(ValueError):
            state.remove_peer(-1)

    def test_remove_none_slot_raises(self):
        state = HubState()
        state.add_peer(self._make_peer(2))
        with pytest.raises(ValueError):
            state.remove_peer(0)

    def test_get_all_peers_excludes_none_slots(self):
        state = HubState()
        state.add_peer(self._make_peer(0))
        state.add_peer(self._make_peer(3))
        peers = state.get_all_peers()
        assert len(peers) == 2
        assert {p.index for p in peers} == {0, 3}

    def test_get_all_peers_with_exclusion(self):
        state = HubState()
        state.add_peer(self._make_peer(0))
        state.add_peer(self._make_peer(1))
        state.add_peer(self._make_peer(2))
        peers = state.get_all_peers(exclude=[1])
        assert {p.index for p in peers} == {0, 2}

    def test_get_all_not_dead_peers(self):
        state = HubState()
        state.add_peer(self._make_peer(0))
        state.add_peer(self._make_peer(1))
        state.add_peer(self._make_peer(2))
        state.set_peer_status(1, 'dead')
        alive = state.get_all_not_dead_peers()
        assert {p.index for p in alive} == {0, 2}

    def test_get_all_not_dead_peers_includes_suspected(self):
        state = HubState()
        state.add_peer(self._make_peer(0))
        state.add_peer(self._make_peer(1))
        state.set_peer_status(1, 'suspected')
        alive = state.get_all_not_dead_peers()
        assert len(alive) == 2

    def test_set_peer_status_on_nonexistent_is_noop(self):
        state = HubState()
        state.set_peer_status(99, 'dead')

    def test_mark_peer_explicitly_alive_updates_last_seen(self):
        state = HubState()
        peer = self._make_peer(0)
        peer.last_seen = 0.0
        peer.status = 'suspected'
        state.add_peer(peer)
        state.mark_peer_explicitly_alive(0)
        assert peer.status == 'alive'
        assert peer.last_seen > 0.0


class TestHubStateMarkForwardPeer:

    def _make_ref(self, addr="10.0.0.1", port=9000):
        return ServerReference(addr, port)

    def test_creates_new_peer_if_not_exists(self):
        state = HubState()
        ref = self._make_ref("5.5.5.5", 5000)
        state.mark_forward_peer_as_alive(2, ref)
        peer = state.get_peer(2)
        assert peer is not None
        assert peer.status == 'alive'
        assert peer.reference == ref

    def test_updates_existing_peer_last_seen_and_status(self):
        state = HubState()
        peer = HubPeer(self._make_ref(), 0)
        peer.status = 'suspected'
        peer.last_seen = 0.0
        state.add_peer(peer)
        state.mark_forward_peer_as_alive(0, self._make_ref())
        assert peer.status == 'alive'
        assert peer.last_seen > 0.0


class TestHubStateHeartbeatCheck:

    def _setup_state_with_peer(self, index=0, heartbeat=5, status='alive'):
        state = HubState()
        peer = HubPeer(ServerReference("10.0.0.1", 9000), index)
        peer.heartbeat = heartbeat
        peer.status = status
        state.add_peer(peer)
        return state, peer

    def test_newer_heartbeat_is_accepted(self):
        state, peer = self._setup_state_with_peer(heartbeat=5)
        result = state.execute_heartbeat_check(0, 10)
        assert result is True
        assert peer.heartbeat == 10
        assert peer.status == 'alive'

    def test_older_heartbeat_is_rejected(self):
        state, peer = self._setup_state_with_peer(heartbeat=10)
        result = state.execute_heartbeat_check(0, 5)
        assert result is False
        assert peer.heartbeat == 10

    def test_equal_heartbeat_is_rejected(self):
        state, peer = self._setup_state_with_peer(heartbeat=10)
        result = state.execute_heartbeat_check(0, 10)
        assert result is False

    def test_nonexistent_peer_returns_false(self):
        state = HubState()
        assert state.execute_heartbeat_check(99, 1) is False

    def test_peer_leave_marks_as_dead(self):
        state, peer = self._setup_state_with_peer(heartbeat=5)
        result = state.execute_heartbeat_check(0, 10, is_peer_leaving=True)
        assert result is True
        assert peer.status == 'dead'

    def test_dead_peer_leave_message_is_blocked(self):
        """Un peer gia' morto non deve propagare ulteriori messaggi di leave."""
        state, peer = self._setup_state_with_peer(heartbeat=5, status='dead')
        result = state.execute_heartbeat_check(0, 10, is_peer_leaving=True)
        assert result is False

    def test_dead_peer_returns_alive_on_normal_heartbeat(self):
        """Un peer morto che manda un heartbeat normale deve tornare alive."""
        state, peer = self._setup_state_with_peer(heartbeat=5, status='dead')
        result = state.execute_heartbeat_check(0, 10)
        assert result is True
        assert peer.status == 'alive'
        assert peer.heartbeat == 10

    def test_dead_peer_returns_even_with_lower_heartbeat(self):
        state, peer = self._setup_state_with_peer(heartbeat=10, status='dead')
        result = state.execute_heartbeat_check(0, 3)
        assert result is True
        assert peer.heartbeat == 3

    def test_heartbeat_check_does_not_update_last_seen(self):
        state, peer = self._setup_state_with_peer(heartbeat=5)
        peer.last_seen = 1000.0
        state.execute_heartbeat_check(0, 10)
        assert peer.last_seen == 1000.0

    def test_update_heartbeat_sets_value(self):
        state, peer = self._setup_state_with_peer(heartbeat=0)
        state.update_heartbeat(0, 42)
        assert peer.heartbeat == 42

    def test_update_heartbeat_nonexistent_peer_is_noop(self):
        state = HubState()
        state.update_heartbeat(99, 42)


class TestHubStateRoomManagement:

    def _make_room(self, room_id="room-1", status=RoomStatus.ACTIVE, player_count=0):
        return Room(
            room_id=room_id,
            owner_hub_index=0,
            status=status,
            external_port=10001,
            internal_service="room-svc.local",
            player_count=player_count,
        )

    def test_add_and_get_room(self):
        state = HubState()
        room = self._make_room()
        state.add_room(room)
        assert state.get_room("room-1") is room

    def test_get_nonexistent_room_returns_none(self):
        state = HubState()
        assert state.get_room("nope") is None

    def test_get_active_room_returns_joinable(self):
        state = HubState()
        state.add_room(self._make_room("room-1", RoomStatus.ACTIVE, player_count=0))
        room = state.get_active_room()
        assert room is not None
        assert room.room_id == "room-1"

    def test_get_active_room_skips_non_joinable(self):
        state = HubState()
        state.add_room(self._make_room("room-full", RoomStatus.ACTIVE, player_count=4))
        state.add_room(self._make_room("room-playing", RoomStatus.PLAYING))
        state.add_room(self._make_room("room-ok", RoomStatus.ACTIVE, player_count=1))
        room = state.get_active_room()
        assert room.room_id == "room-ok"

    def test_get_active_room_returns_none_when_no_joinable(self):
        state = HubState()
        state.add_room(self._make_room("r1", RoomStatus.PLAYING))
        state.add_room(self._make_room("r2", RoomStatus.CLOSED))
        assert state.get_active_room() is None

    def test_set_room_status(self):
        state = HubState()
        state.add_room(self._make_room("room-1", RoomStatus.ACTIVE))
        state.set_room_status("room-1", RoomStatus.PLAYING)
        assert state.get_room("room-1").status == RoomStatus.PLAYING

    def test_set_room_status_nonexistent_is_noop(self):
        state = HubState()
        state.set_room_status("nope", RoomStatus.CLOSED)

    def test_remove_room(self):
        state = HubState()
        state.add_room(self._make_room("room-1"))
        state.remove_room("room-1")
        assert state.get_room("room-1") is None

    def test_remove_nonexistent_room_is_noop(self):
        state = HubState()
        state.remove_room("nope")

    def test_get_all_rooms(self):
        state = HubState()
        state.add_room(self._make_room("r1"))
        state.add_room(self._make_room("r2"))
        rooms = state.get_all_rooms()
        assert len(rooms) == 2

    def test_add_room_overwrites_existing(self):
        state = HubState()
        room1 = self._make_room("room-1", RoomStatus.ACTIVE)
        room2 = self._make_room("room-1", RoomStatus.PLAYING)
        state.add_room(room1)
        state.add_room(room2)
        assert state.get_room("room-1").status == RoomStatus.PLAYING