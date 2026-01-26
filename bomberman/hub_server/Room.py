from dataclasses import dataclass
from bomberman.common.RoomState import RoomStatus


@dataclass
class Room:
    room_id: str
    owner_hub_index: int
    status: RoomStatus
    external_port: int
    internal_service: str  # room-{id}-svc.bomberman.svc.cluster.local
    player_count: int = 0
    max_players: int = 4

    @property
    def is_joinable(self) -> bool:
        return self.status == RoomStatus.ACTIVE and self.player_count < self.max_players