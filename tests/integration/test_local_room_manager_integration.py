"""
Pochi test perché un integration test qui darebbe poco valore aggiunto in quanto: stiamo programmando in locale, quindi non è mission critical.
Sono stati svolti solo gli integration test che possono dare valore aggiunto. Gli altri sono stati scartati
"""
import pytest
from bomberman.hub_server.room_manager.LocalRoomManager import LocalRoomManager
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.Room import Room


class TestLocalRoomManagerCallbackContract:

    def test_callback_receives_room_in_active_state(self):
        """
        Core contract: by the time the callback is invoked, the room status
        must already be ACTIVE. The caller (HubServer) relies on this to add
        a joinable room to HubState — receiving a DORMANT room would be a bug.
        """
        received: list[Room] = []
        manager = LocalRoomManager(hub_index=0, on_room_activated=received.append)
        manager.initialize_pool()

        manager.activate_room()

        assert len(received) == 1
        assert received[0].status == RoomStatus.ACTIVE, (
            f"Callback received room with status {received[0].status!r} — "
            "expected ACTIVE. The status transition must happen before the callback."
        )

    def test_callback_is_not_invoked_when_no_dormant_rooms_remain(self):
        """
        When all rooms are already active, activate_room() must return None
        and must NOT invoke the callback — calling it with no room to offer
        would push a spurious entry into HubState.
        """
        received: list[Room] = []
        manager = LocalRoomManager(hub_index=0, on_room_activated=received.append)
        manager.initialize_pool()

        # Exhaust all dormant rooms
        for _ in range(manager.STARTING_POOL_SIZE):
            manager.activate_room()

        received.clear()

        result = manager.activate_room()

        assert result is None
        assert received == [], (
            "Callback was invoked even though no dormant room was available."
        )