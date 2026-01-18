from typing import Callable

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase, print_console


class LocalRoomManager(RoomManagerBase):
    """
    Room manager per testing locale.
    Non crea processi reali, simula le room in memoria.
    """
    ROOM_PORT_START = 20001

    def __init__(
        self,
        hub_index: int,
        on_room_activated: Callable[[Room], None]
    ):
        super().__init__(hub_index, on_room_activated)

    def initialize_pool(self) -> None:
        print_console(f"Initializing LOCAL room pool with {self.STARTING_POOL_SIZE} rooms (simulated)", "RoomHandling")

        for i in range(self.STARTING_POOL_SIZE):
            room_id = f"hub{self._hub_index}-{i}"
            port = self.ROOM_PORT_START + (self._hub_index * 100) + i

            if self._create_room(room_id, port):
                room = Room(
                    room_id=room_id,
                    owner_hub_index=self._hub_index,
                    status=RoomStatus.DORMANT,
                    external_port=port,
                    internal_service=f"localhost:{port}"
                )
                self._local_rooms[room_id] = room
                print_console(f"Created simulated room {room_id} on port {port}", "RoomHandling")

    def _create_room(self, room_id: str, port: int) -> bool:
        print_console(f"[LOCAL] Simulating room creation: {room_id}", "RoomHandling")
        return True

    def _delete_room(self, room_id: str) -> None:
        print_console(f"[LOCAL] Simulating room deletion: {room_id}", "RoomHandling")

    def get_room_address(self, room: Room) -> str:
        return "localhost"