import pytest
from unittest.mock import MagicMock

from bomberman.hub_server.room_manager.LocalRoomManager import LocalRoomManager
from bomberman.common.RoomState import RoomStatus


class TestLocalRoomManager:

    def test_initialize_pool_creates_correct_number_of_rooms(self):
        callback = MagicMock()
        mgr = LocalRoomManager(hub_index=0, on_room_activated=callback)
        mgr.initialize_pool()
        assert len(mgr._local_rooms) == mgr.STARTING_POOL_SIZE

    def test_all_rooms_start_dormant(self):
        mgr = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr.initialize_pool()
        for room in mgr._local_rooms.values():
            assert room.status == RoomStatus.DORMANT

    def test_room_ids_follow_naming_convention(self):
        mgr = LocalRoomManager(hub_index=2, on_room_activated=MagicMock())
        mgr.initialize_pool()
        expected_ids = {f"hub2-{i}" for i in range(mgr.STARTING_POOL_SIZE)}
        assert set(mgr._local_rooms.keys()) == expected_ids

    def test_ports_are_unique_per_hub(self):
        mgr = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr.initialize_pool()
        ports = [room.external_port for room in mgr._local_rooms.values()]
        assert len(ports) == len(set(ports))

    def test_different_hubs_have_different_port_ranges(self):
        mgr0 = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr1 = LocalRoomManager(hub_index=1, on_room_activated=MagicMock())
        mgr0.initialize_pool()
        mgr1.initialize_pool()

        ports0 = {r.external_port for r in mgr0._local_rooms.values()}
        ports1 = {r.external_port for r in mgr1._local_rooms.values()}
        assert ports0.isdisjoint(ports1)

    def test_port_formula_is_correct(self):
        mgr = LocalRoomManager(hub_index=1, on_room_activated=MagicMock())
        mgr.initialize_pool()
        expected_base = mgr.ROOM_PORT_START + (1 * 100)
        ports = sorted(r.external_port for r in mgr._local_rooms.values())
        assert ports == [expected_base + i for i in range(mgr.STARTING_POOL_SIZE)]

    def test_owner_hub_index_is_set_correctly(self):
        mgr = LocalRoomManager(hub_index=5, on_room_activated=MagicMock())
        mgr.initialize_pool()
        for room in mgr._local_rooms.values():
            assert room.owner_hub_index == 5

    def test_activate_then_no_more_dormant(self):
        mgr = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr.initialize_pool()
        for _ in range(mgr.STARTING_POOL_SIZE):
            room = mgr.activate_room()
            assert room is not None
        assert mgr.activate_room() is None

    def test_get_room_address_returns_localhost(self):
        mgr = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr.initialize_pool()
        room = list(mgr._local_rooms.values())[0]
        assert mgr.get_room_address(room) == "localhost"

    def test_cleanup_empties_local_rooms(self):
        mgr = LocalRoomManager(hub_index=0, on_room_activated=MagicMock())
        mgr.initialize_pool()
        mgr.cleanup()
        assert len(mgr._local_rooms) == 0