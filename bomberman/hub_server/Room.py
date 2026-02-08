from bomberman.common.RoomState import RoomStatus


class Room:
    def __init__(
            self,
            room_id: str,
            owner_hub_index: int,
            status: RoomStatus,
            external_port: int,
            internal_service: str,
            player_count: int = 0,
            max_players: int = 4
    ):
        self.room_id = room_id
        self.owner_hub_index = owner_hub_index
        self.status = status
        self.external_port = external_port
        self.internal_service = internal_service
        self.max_players = max_players
        self.player_count = player_count

        if self.player_count > max_players:
            raise ValueError("Max players exceeded")

    @property
    def player_count(self) -> int:
        return self._player_count

    @player_count.setter
    def player_count(self, value: int):
        if value < 0:
            raise ValueError("Negative values are not allowed")
        self._player_count = value

    @property
    def is_joinable(self) -> bool:
        return self.status == RoomStatus.ACTIVE and self.player_count < self.max_players

    def __repr__(self):
        return (f"Room(room_id={self.room_id!r}, player_count={self.player_count}, "
                f"status={self.status}, max_players={self.max_players})")

    def increment_player_count(self):
        if self.player_count < self.max_players:
            self.player_count = self.player_count + 1