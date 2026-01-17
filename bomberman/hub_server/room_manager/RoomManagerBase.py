from abc import ABC, abstractmethod
from typing import Callable

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.hublogging import print_console


class RoomManagerBase(ABC):
    POOL_SIZE = 3

    _hub_index: int
    _local_rooms: dict[str, Room]
    _on_room_activated: Callable[[Room], None]

    def __init__(
        self,
        hub_index: int,
        on_room_activated: Callable[[Room], None]
    ):
        self._external_domain = ""
        self._hub_index = hub_index
        self._local_rooms = {}
        self._on_room_activated = on_room_activated

    @abstractmethod
    def initialize_pool(self) -> None:
        """Crea il pool di room dormant"""
        pass

    @abstractmethod
    def _create_room(self, room_id: str, port: int) -> bool:
        """Crea la room (pod K8s o processo locale)"""
        pass

    @abstractmethod
    def _delete_room(self, room_id: str) -> None:
        """Elimina la room"""
        pass

    @abstractmethod
    def get_room_address(self, room: Room) -> str:
        """Ritorna l'indirizzo esterno della room"""
        pass

    def activate_room(self) -> Room | None:
        """Attiva una room dormant e notifica via gossip"""
        for room in self._local_rooms.values():
            if room.status == RoomStatus.DORMANT:
                room.status = RoomStatus.ACTIVE
                print_console(f"Activated room {room.room_id}", "RoomHandling")
                self._on_room_activated(room)
                return room

        print_console("No dormant rooms available", "Warning")
        return None

    def get_local_room(self, room_id: str) -> Room | None:
        return self._local_rooms.get(room_id)

    def get_all_local_rooms(self) -> list[Room]:
        return list(self._local_rooms.values())

    def set_room_status(self, room_id: str, status: RoomStatus) -> None:
        if room_id in self._local_rooms:
            self._local_rooms[room_id].status = status

    def cleanup(self) -> None:
        """Elimina tutte le room"""
        print_console("Cleaning up rooms", "RoomHandling")
        for room_id in list(self._local_rooms.keys()):
            self._delete_room(room_id)
        self._local_rooms.clear()

    @property
    def external_domain(self):
        return self._external_domain