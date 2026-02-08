import pytest
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus


class TestRoom:

    def _make_room(self, status=RoomStatus.ACTIVE, player_count=0, max_players=4):
        return Room(
            room_id="room-1",
            owner_hub_index=0,
            status=status,
            external_port=10001,
            internal_service="room-1-svc.local",
            player_count=player_count,
            max_players=max_players,
        )

    @pytest.mark.parametrize("status,player_count,expected", [
        (RoomStatus.ACTIVE, 0, True),
        (RoomStatus.ACTIVE, 3, True),
        (RoomStatus.ACTIVE, 4, False),
        (RoomStatus.DORMANT, 0, False),
        (RoomStatus.PLAYING, 0, False),
        (RoomStatus.CLOSED, 0, False),
    ])
    def test_is_joinable(self, status, player_count, expected):
        room = self._make_room(status=status, player_count=player_count)
        assert room.is_joinable is expected

    def test_is_joinable_at_boundary(self):
        room = self._make_room(player_count=3, max_players=4)
        assert room.is_joinable is True

    def test_is_joinable_exactly_full(self):
        room = self._make_room(player_count=4, max_players=4)
        assert room.is_joinable is False

    def test_validation_on_player_count_exceeding_max(self):
        with pytest.raises(ValueError):
            self._make_room(player_count=10, max_players=4)


    def test_validation_on_negative_player_count(self):
        with pytest.raises(ValueError):
            self._make_room(player_count=-1, max_players=4, status=RoomStatus.ACTIVE)

    def test_max_players_zero_room_never_joinable(self):
        room = self._make_room(player_count=0, max_players=0, status=RoomStatus.ACTIVE)
        assert room.is_joinable is False

    def test_status_transition_affects_joinability(self):
        room = self._make_room(status=RoomStatus.ACTIVE, player_count=0)
        assert room.is_joinable is True
        room.status = RoomStatus.PLAYING
        assert room.is_joinable is False
        room.status = RoomStatus.ACTIVE
        assert room.is_joinable is True