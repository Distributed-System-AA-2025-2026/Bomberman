import pytest
from unittest.mock import MagicMock, patch

from bomberman.hub_server.RoomManager import RoomManager
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus


class TestRoomManagerPortAllocation:

    def _create_manager(self, hub_index=0):
        with patch("bomberman.hub_server.RoomManager.config"), \
             patch("bomberman.hub_server.RoomManager.client"):
            mgr = RoomManager(
                hub_index=hub_index,
                on_room_activated=MagicMock(),
            )
        return mgr

    def test_allocate_first_port(self):
        mgr = self._create_manager()
        port = mgr._allocate_port()
        assert port == RoomManager.ROOM_PORT_START

    def test_allocate_port_skips_used(self):
        mgr = self._create_manager()
        room = Room("r1", 0, RoomStatus.DORMANT, RoomManager.ROOM_PORT_START, "svc")
        mgr._local_rooms["r1"] = room
        port = mgr._allocate_port()
        assert port == RoomManager.ROOM_PORT_START + 1

    def test_allocate_port_returns_none_when_exhausted(self):
        mgr = self._create_manager()
        for i in range(RoomManager.ROOM_PORT_START, RoomManager.ROOM_PORT_END + 1):
            room = Room(f"r{i}", 0, RoomStatus.DORMANT, i, "svc")
            mgr._local_rooms[f"r{i}"] = room
        assert mgr._allocate_port() is None


class TestRoomManagerActivation:

    def _create_manager(self):
        with patch("bomberman.hub_server.RoomManager.config"), \
             patch("bomberman.hub_server.RoomManager.client"):
            mgr = RoomManager(hub_index=0, on_room_activated=MagicMock())
        return mgr

    def test_activate_room_picks_dormant(self):
        mgr = self._create_manager()
        dormant = Room("r1", 0, RoomStatus.DORMANT, 10001, "svc")
        active = Room("r2", 0, RoomStatus.ACTIVE, 10002, "svc")
        mgr._local_rooms = {"r1": dormant, "r2": active}
        result = mgr.activate_room()
        assert result is dormant
        assert dormant.status == RoomStatus.ACTIVE

    def test_activate_room_none_when_no_dormant(self):
        mgr = self._create_manager()
        mgr._local_rooms = {"r1": Room("r1", 0, RoomStatus.ACTIVE, 10001, "svc")}
        assert mgr.activate_room() is None

    def test_get_local_room(self):
        mgr = self._create_manager()
        room = Room("r1", 0, RoomStatus.DORMANT, 10001, "svc")
        mgr._local_rooms["r1"] = room
        assert mgr.get_local_room("r1") is room
        assert mgr.get_local_room("nope") is None

    def test_set_room_status(self):
        mgr = self._create_manager()
        room = Room("r1", 0, RoomStatus.DORMANT, 10001, "svc")
        mgr._local_rooms["r1"] = room
        mgr.set_room_status("r1", RoomStatus.PLAYING)
        assert room.status == RoomStatus.PLAYING

    def test_cleanup_clears_all(self):
        mgr = self._create_manager()
        mgr._k8s_core = MagicMock()
        room = Room("r1", 0, RoomStatus.ACTIVE, 10001, "svc")
        mgr._local_rooms["r1"] = room
        mgr.cleanup()
        assert len(mgr._local_rooms) == 0