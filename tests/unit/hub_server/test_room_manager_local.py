import pytest
from unittest.mock import Mock, patch, call

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.LocalRoomManager import LocalRoomManager


class TestLocalRoomManagerInitialization:
    """Test suite for LocalRoomManager initialization"""

    def test_initialization_with_valid_parameters(self):
        """Test normal initialization"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=5, on_room_activated=callback)

        assert manager._hub_index == 5
        assert manager._on_room_activated is callback
        assert manager._local_rooms == {}
        assert manager.STARTING_POOL_SIZE == 3
        assert manager.ROOM_PORT_START == 20001

    @pytest.mark.parametrize("hub_index", [0, 1, 5, 10, 99, 999])
    def test_initialization_with_various_hub_indices(self, hub_index: int):
        """Test initialization with different hub indices"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=hub_index, on_room_activated=callback)

        assert manager._hub_index == hub_index

    def test_room_port_start_constant(self):
        """Test that ROOM_PORT_START is correctly defined"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())
        assert manager.ROOM_PORT_START == 20001


class TestLocalRoomManagerInitializePool:
    """Test suite for initialize_pool method"""

    def test_initialize_pool_creates_correct_number_of_rooms(self):
        """Test that initialize_pool creates STARTING_POOL_SIZE rooms"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        assert len(manager._local_rooms) == 3

    def test_initialize_pool_creates_rooms_with_correct_ids(self):
        """Test that room IDs follow the pattern hub{index}-{i}"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=5, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        expected_ids = ["hub5-0", "hub5-1", "hub5-2"]
        assert set(manager._local_rooms.keys()) == set(expected_ids)

    def test_initialize_pool_calculates_ports_correctly(self):
        """Test port calculation formula: ROOM_PORT_START + (hub_index * 100) + i"""
        callback = Mock()
        hub_index = 3
        manager = LocalRoomManager(hub_index=hub_index, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        expected_ports = [20001 + (hub_index * 100) + i for i in range(3)]
        actual_ports = [room.external_port for room in manager._local_rooms.values()]

        assert sorted(actual_ports) == sorted(expected_ports)

    @pytest.mark.parametrize("hub_index,expected_first_port", [
        (0, 20001),
        (1, 20101),
        (5, 20501),
        (10, 21001),
        (99, 29901),
    ])
    def test_initialize_pool_port_ranges(self, hub_index: int, expected_first_port: int):
        """Test that different hub indices produce correct port ranges"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=hub_index, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        ports = sorted([room.external_port for room in manager._local_rooms.values()])
        assert ports[0] == expected_first_port
        assert ports == [expected_first_port + i for i in range(3)]

    def test_initialize_pool_creates_dormant_rooms(self):
        """Test that all created rooms have DORMANT status"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        for room in manager._local_rooms.values():
            assert room.status == RoomStatus.DORMANT

    def test_initialize_pool_sets_correct_owner_hub_index(self):
        """Test that rooms have correct owner_hub_index"""
        callback = Mock()
        hub_index = 7
        manager = LocalRoomManager(hub_index=hub_index, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        for room in manager._local_rooms.values():
            assert room.owner_hub_index == hub_index

    def test_initialize_pool_sets_internal_service_correctly(self):
        """Test that internal_service follows pattern localhost:{port}"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        for room in manager._local_rooms.values():
            expected_service = f"localhost:{room.external_port}"
            assert room.internal_service == expected_service

    def test_initialize_pool_multiple_calls(self):
        """Test calling initialize_pool multiple times"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()
            initial_count = len(manager._local_rooms)

            manager.initialize_pool()
            final_count = len(manager._local_rooms)

        # Second call rewrites the existing rooms
        assert final_count == initial_count


class TestLocalRoomManagerCreateRoom:
    """Test suite for _create_room method"""

    def test_create_room_always_returns_true(self):
        """Test that _create_room always succeeds in local mode"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            result = manager._create_room("test-room", 8000)

        assert result is True

    @pytest.mark.parametrize("room_id,port", [
        ("room-1", 8000),
        ("hub5-3", 20503),
        ("special-room", 9999),
        ("", 1),
        ("room-with-long-name-12345", 65535),
    ])
    def test_create_room_with_various_parameters(self, room_id: str, port: int):
        """Test _create_room with various room IDs and ports"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            result = manager._create_room(room_id, port)

        assert result is True

    def test_create_room_logs_correct_message(self):
        """Test that _create_room logs simulation message"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console') as mock_print:
            manager._create_room("test-room", 8000)

        mock_print.assert_called_once_with(
            "[LOCAL] Simulating room creation: test-room",
            "RoomHandling"
        )

    def test_create_room_does_not_actually_create_process(self):
        """Test that _create_room doesn't create real processes (simulation only)"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            # Should not call any system functions
            with patch('subprocess.Popen') as mock_popen:
                manager._create_room("test-room", 8000)
                mock_popen.assert_not_called()


class TestLocalRoomManagerDeleteRoom:
    """Test suite for _delete_room method"""

    def test_delete_room_logs_message(self):
        """Test that _delete_room logs simulation message"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console') as mock_print:
            manager._delete_room("test-room")

        mock_print.assert_called_once_with(
            "[LOCAL] Simulating room deletion: test-room",
            "RoomHandling"
        )

    @pytest.mark.parametrize("room_id", [
        "room-1",
        "hub0-0",
        "special-room-name",
        "",
        "room-with-very-long-id-12345678",
    ])
    def test_delete_room_with_various_ids(self, room_id: str):
        """Test _delete_room with various room IDs"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console') as mock_print:
            manager._delete_room(room_id)

        expected_message = f"[LOCAL] Simulating room deletion: {room_id}"
        mock_print.assert_called_once_with(expected_message, "RoomHandling")

    def test_delete_room_does_not_raise_exception(self):
        """Test that _delete_room never raises exceptions"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            # Should not raise any exception
            manager._delete_room("nonexistent-room")
            manager._delete_room(None)  # Even with None

    def test_delete_room_does_not_actually_kill_process(self):
        """Test that _delete_room doesn't kill real processes"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            with patch('os.kill') as mock_kill:
                manager._delete_room("test-room")
                mock_kill.assert_not_called()


class TestLocalRoomManagerGetRoomAddress:
    """Test suite for get_room_address method"""

    def test_get_room_address_returns_localhost(self):
        """Test that get_room_address always returns 'localhost'"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id="test-room",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8000,
            internal_service="localhost:8000"
        )

        result = manager.get_room_address(room)
        assert result == "localhost"

    @pytest.mark.parametrize("room_id,port", [
        ("room-1", 8000),
        ("room-2", 9999),
        ("hub5-3", 20503),
    ])
    def test_get_room_address_independent_of_room_properties(self, room_id: str, port: int):
        """Test that get_room_address always returns localhost regardless of room"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id=room_id,
            owner_hub_index=1,
            status=RoomStatus.ACTIVE,
            external_port=port,
            internal_service=f"localhost:{port}"
        )

        result = manager.get_room_address(room)
        assert result == "localhost"

    def test_get_room_address_with_different_hub_indices(self):
        """Test that get_room_address returns localhost for any hub_index"""
        for hub_index in [0, 1, 5, 10]:
            manager = LocalRoomManager(hub_index=hub_index, on_room_activated=Mock())

            room = Room(
                room_id="test",
                owner_hub_index=hub_index,
                status=RoomStatus.ACTIVE,
                external_port=8000,
                internal_service="localhost:8000"
            )

            assert manager.get_room_address(room) == "localhost"


class TestLocalRoomManagerIntegrationWithBase:
    """Test suite for integration with RoomManagerBase methods"""

    def test_activate_room_inherited_functionality(self):
        """Test that activate_room works correctly (inherited from base)"""
        callback = Mock()
        manager = LocalRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
            room = manager.activate_room()

        assert room is not None
        assert room.status == RoomStatus.ACTIVE
        callback.assert_called_once_with(room)

    def test_get_local_room_inherited_functionality(self):
        """Test that get_local_room works correctly"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        room = manager.get_local_room("hub1-0")
        assert room is not None
        assert room.room_id == "hub1-0"

    def test_set_room_status_inherited_functionality(self):
        """Test that set_room_status works correctly"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        manager.set_room_status("hub1-0", RoomStatus.PLAYING)
        room = manager.get_local_room("hub1-0")
        assert room.status == RoomStatus.PLAYING

    def test_cleanup_calls_delete_room_for_each_room(self):
        """Test that cleanup calls _delete_room for each room"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        with patch.object(manager, '_delete_room') as mock_delete:
            with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
                manager.cleanup()

            assert mock_delete.call_count == 3
            expected_calls = [call("hub1-0"), call("hub1-1"), call("hub1-2")]
            mock_delete.assert_has_calls(expected_calls, any_order=True)

    def test_cleanup_clears_local_rooms(self):
        """Test that cleanup clears the _local_rooms dictionary"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()
            assert len(manager._local_rooms) == 3

            manager.cleanup()
            assert len(manager._local_rooms) == 0


class TestLocalRoomManagerEdgeCases:
    """Test suite for edge cases and error conditions"""

    def test_initialize_pool_with_modified_pool_size(self):
        """Test initialize_pool when STARTING_POOL_SIZE is modified"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())
        manager.STARTING_POOL_SIZE = 5

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        assert len(manager._local_rooms) == 5

    def test_port_overflow_for_high_hub_index(self):
        """Test port calculation with very high hub index"""
        # Port = 20001 + (hub_index * 100) + i
        # For hub_index=999, ports would be 119901, 119902, 119903
        # This exceeds typical port range (1-65535) but code doesn't validate
        manager = LocalRoomManager(hub_index=999, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        # Code doesn't validate port range, so it will create invalid ports
        ports = [room.external_port for room in manager._local_rooms.values()]
        assert all(port > 65535 for port in ports)

    def test_negative_hub_index_port_calculation(self):
        """Test port calculation with negative hub index"""
        manager = LocalRoomManager(hub_index=-1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            manager.initialize_pool()

        # Port = 20001 + (-1 * 100) + 0 = 19901
        expected_first_port = 20001 - 100
        actual_ports = sorted([room.external_port for room in manager._local_rooms.values()])
        assert actual_ports[0] == expected_first_port

    def test_create_room_with_invalid_port_type(self):
        """Test _create_room behavior with invalid port type"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        # Python will accept any type, but won't validate
        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console'):
            result = manager._create_room("test", "invalid_port")

        assert result is True  # Still returns True (simulation mode)

    def test_delete_room_with_none(self):
        """Test _delete_room with None as room_id"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        with patch('bomberman.hub_server.room_manager.LocalRoomManager.print_console') as mock_print:
            manager._delete_room(None)

        # Should log with None in message
        mock_print.assert_called_once()
        assert "None" in str(mock_print.call_args[0][0])


class TestLocalRoomManagerConcurrency:
    """Test suite for thread safety (documentation of current behavior)"""

    def test_initialize_pool_not_thread_safe(self):
        """Document that initialize_pool is not thread-safe"""
        # This test documents that the current implementation
        # does not use locks and is not thread-safe
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        # No locks are used in the implementation
        assert not hasattr(manager, '_lock')

    def test_local_rooms_dict_not_protected(self):
        """Document that _local_rooms dict is not protected by locks"""
        manager = LocalRoomManager(hub_index=1, on_room_activated=Mock())

        # Direct access to _local_rooms is possible and not protected
        manager._local_rooms["test"] = Mock()
        assert "test" in manager._local_rooms