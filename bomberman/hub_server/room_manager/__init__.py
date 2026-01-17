from typing import Literal, Callable

from bomberman.hub_server.Room import Room
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase
from bomberman.hub_server.room_manager.K8sRoomManager import K8sRoomManager
from bomberman.hub_server.room_manager.LocalRoomManager import LocalRoomManager


def create_room_manager(
        discovery_mode: Literal['manual', 'k8s'],
        hub_index: int,
        on_room_activated: Callable[[Room], None]
) -> RoomManagerBase:
    """Factory per creare il RoomManager appropriato in base al discovery_mode"""

    if discovery_mode == 'k8s':
        return K8sRoomManager(
            hub_index=hub_index,
            on_room_activated=on_room_activated
        )
    else:
        return LocalRoomManager(
            hub_index=hub_index,
            on_room_activated=on_room_activated
        )