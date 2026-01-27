import pytest
from unittest.mock import Mock, patch, call
from typing import Callable

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase


# Concrete implementation for testing abstract class
class ConcreteRoomManager(RoomManagerBase):
    """Minimal concrete implementation for testing"""

    def initialize_pool(self) -> None:
        """Test implementation"""
        pass

    def _create_room(self, room_id: str, port: int) -> bool:
        """Test implementation"""
        return True

    def _delete_room(self, room_id: str) -> None:
        """Test implementation"""
        pass

    def get_room_address(self, room: Room) -> str:
        """Test implementation"""
        return "test-address"


class TestRoomManagerBaseInitialization:
    """Test suite for RoomManagerBase initialization"""

    def test_initialization_with_valid_parameters(self):
        """Test normal initialization with valid hub_index and callback"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=5, on_room_activated=callback)

        assert manager._hub_index == 5
        assert manager._on_room_activated is callback
        assert manager._local_rooms == {}
        assert manager._external_domain == ""
        assert manager.STARTING_POOL_SIZE == 3

    @pytest.mark.parametrize("hub_index", [0, 1, 10, 100, 999, 99999])
    def test_initialization_with_various_hub_indices(self, hub_index: int):
        """Test initialization with different valid hub indices"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=hub_index, on_room_activated=callback)

        assert manager._hub_index == hub_index

    @pytest.mark.parametrize("invalid_hub_index", [-1, -100, "string", None, 3.14, [], {}])
    def test_initialization_with_invalid_hub_index_types(self, invalid_hub_index):
        """Test that initialization accepts any type (Python duck typing)"""
        # Python doesn't enforce type hints at runtime, so this won't fail
        # but we document the expected behavior
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=invalid_hub_index, on_room_activated=callback)
        assert manager._hub_index == invalid_hub_index

    def test_initialization_with_none_callback(self):
        """Test initialization with None callback (will fail on activation)"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=None)
        assert manager._on_room_activated is None

    @pytest.mark.parametrize("invalid_callback", ["string", 123, [], {}, 3.14])
    def test_initialization_with_invalid_callback_types(self, invalid_callback):
        """Test initialization with non-callable types (will fail on call)"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=invalid_callback)
        assert manager._on_room_activated == invalid_callback


class TestRoomManagerBaseActivateRoom:
    """Test suite for activate_room method"""

    def test_activate_first_dormant_room(self):
        """Test activating the first dormant room found"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=callback)

        # Create dormant room
        room = Room(
            room_id="test-room-1",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="test-svc"
        )
        manager._local_rooms["test-room-1"] = room

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console') as mock_print:
            result = manager.activate_room()

        assert result is room
        assert room.status == RoomStatus.ACTIVE
        callback.assert_called_once_with(room)
        mock_print.assert_called_once_with("Activated room test-room-1", "RoomHandling")

    def test_activate_room_with_multiple_dormant_rooms(self):
        """Test that only the first dormant room is activated"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=callback)

        # Create multiple dormant rooms
        rooms = []
        for i in range(3):
            room = Room(
                room_id=f"room-{i}",
                owner_hub_index=1,
                status=RoomStatus.DORMANT,
                external_port=8000 + i,
                internal_service=f"svc-{i}"
            )
            manager._local_rooms[f"room-{i}"] = room
            rooms.append(room)

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
            result = manager.activate_room()

        # First room should be activated
        activated_count = sum(1 for r in rooms if r.status == RoomStatus.ACTIVE)
        assert activated_count == 1
        assert result.status == RoomStatus.ACTIVE
        callback.assert_called_once()

    def test_activate_room_no_dormant_available(self):
        """Test activation when no dormant rooms exist"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=callback)

        # Create rooms with non-dormant statuses
        statuses = [RoomStatus.ACTIVE, RoomStatus.PLAYING, RoomStatus.CLOSED]
        for i, status in enumerate(statuses):
            room = Room(
                room_id=f"room-{i}",
                owner_hub_index=1,
                status=status,
                external_port=8000 + i,
                internal_service=f"svc-{i}"
            )
            manager._local_rooms[f"room-{i}"] = room

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console') as mock_print:
            result = manager.activate_room()

        assert result is None
        callback.assert_not_called()
        mock_print.assert_called_once_with("No dormant rooms available", "Warning")

    def test_activate_room_empty_room_list(self):
        """Test activation when room list is empty"""
        callback = Mock()
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=callback)

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console') as mock_print:
            result = manager.activate_room()

        assert result is None
        callback.assert_not_called()
        mock_print.assert_called_once_with("No dormant rooms available", "Warning")

    def test_activate_room_callback_exception_propagates(self):
        """Test that callback exceptions propagate to caller"""
        callback = Mock(side_effect=RuntimeError("Callback error"))
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=callback)

        room = Room(
            room_id="test-room",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="test-svc"
        )
        manager._local_rooms["test-room"] = room

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
            with pytest.raises(RuntimeError, match="Callback error"):
                manager.activate_room()

        # Room should still be activated even if callback fails
        assert room.status == RoomStatus.ACTIVE


class TestRoomManagerBaseGetLocalRoom:
    """Test suite for get_local_room method"""

    def test_get_existing_room(self):
        """Test retrieving an existing room"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id="test-room",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="test-svc"
        )
        manager._local_rooms["test-room"] = room

        result = manager.get_local_room("test-room")
        assert result is room

    def test_get_nonexistent_room(self):
        """Test retrieving a room that doesn't exist"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        result = manager.get_local_room("nonexistent")
        assert result is None

    @pytest.mark.parametrize("room_id", ["", " ", "room-123", "hub0-5", "special-chars!@#"])
    def test_get_room_with_various_ids(self, room_id: str):
        """Test get_local_room with various room ID formats"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id=room_id,
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="test-svc"
        )
        manager._local_rooms[room_id] = room

        result = manager.get_local_room(room_id)
        assert result is room

    def test_get_room_with_invalid_type(self):
        """Test get_local_room with invalid key types"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        # Dict.get() will handle type conversion
        # These won't raise errors but will return None
        assert manager.get_local_room(None) is None
        assert manager.get_local_room(123) is None


class TestRoomManagerBaseSetRoomStatus:
    """Test suite for set_room_status method"""

    def test_set_status_existing_room(self):
        """Test setting status of an existing room"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id="room-1",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="svc-1"
        )
        manager._local_rooms["room-1"] = room

        manager.set_room_status("room-1", RoomStatus.ACTIVE)
        assert room.status == RoomStatus.ACTIVE

    @pytest.mark.parametrize("old_status,new_status", [
        (RoomStatus.DORMANT, RoomStatus.ACTIVE),
        (RoomStatus.ACTIVE, RoomStatus.PLAYING),
        (RoomStatus.PLAYING, RoomStatus.CLOSED),
        (RoomStatus.CLOSED, RoomStatus.DORMANT),
        (RoomStatus.ACTIVE, RoomStatus.ACTIVE),  # Same status
    ])
    def test_set_status_transitions(self, old_status: RoomStatus, new_status: RoomStatus):
        """Test various status transitions"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id="room-1",
            owner_hub_index=1,
            status=old_status,
            external_port=8001,
            internal_service="svc-1"
        )
        manager._local_rooms["room-1"] = room

        manager.set_room_status("room-1", new_status)
        assert room.status == new_status

    def test_set_status_nonexistent_room(self):
        """Test setting status of a room that doesn't exist (should do nothing)"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        # Should not raise an error
        manager.set_room_status("nonexistent", RoomStatus.ACTIVE)
        assert len(manager._local_rooms) == 0

    def test_set_status_invalid_type(self):
        """Test setting status with invalid status type"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        room = Room(
            room_id="room-1",
            owner_hub_index=1,
            status=RoomStatus.DORMANT,
            external_port=8001,
            internal_service="svc-1"
        )
        manager._local_rooms["room-1"] = room

        # Python doesn't enforce enums, so this will actually work
        manager.set_room_status("room-1", "invalid")
        assert room.status == "invalid"


class TestRoomManagerBaseCleanup:
    """Test suite for cleanup method"""

    def test_cleanup_single_room(self):
        """Test cleanup with a single room"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        manager._delete_room = Mock()

        room = Room(
            room_id="room-1",
            owner_hub_index=1,
            status=RoomStatus.ACTIVE,
            external_port=8001,
            internal_service="svc-1"
        )
        manager._local_rooms["room-1"] = room

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console') as mock_print:
            manager.cleanup()

        manager._delete_room.assert_called_once_with("room-1")
        assert len(manager._local_rooms) == 0
        mock_print.assert_called_once_with("Cleaning up rooms", "RoomHandling")

    def test_cleanup_multiple_rooms(self):
        """Test cleanup with multiple rooms"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        manager._delete_room = Mock()

        room_ids = ["room-1", "room-2", "room-3"]
        for room_id in room_ids:
            room = Room(
                room_id=room_id,
                owner_hub_index=1,
                status=RoomStatus.ACTIVE,
                external_port=8001,
                internal_service="svc-1"
            )
            manager._local_rooms[room_id] = room

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
            manager.cleanup()

        assert manager._delete_room.call_count == 3
        expected_calls = [call(room_id) for room_id in room_ids]
        manager._delete_room.assert_has_calls(expected_calls, any_order=True)
        assert len(manager._local_rooms) == 0

    def test_cleanup_empty_rooms(self):
        """Test cleanup when no rooms exist"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        manager._delete_room = Mock()

        with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console') as mock_print:
            manager.cleanup()

        manager._delete_room.assert_not_called()
        assert len(manager._local_rooms) == 0
        mock_print.assert_called_once_with("Cleaning up rooms", "RoomHandling")


class TestRoomManagerBaseExternalDomainProperty:
    """Test suite for external_domain property"""

    def test_external_domain_getter(self):
        """Test that external_domain property returns correct value"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        assert manager.external_domain == ""

    def test_external_domain_after_modification(self):
        """Test external_domain property after internal modification"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        manager._external_domain = "test.domain.com"
        assert manager.external_domain == "test.domain.com"

    def test_external_domain_is_readonly_property(self):
        """Test that external_domain property has no setter"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())

        # Attempting to set the property should raise AttributeError
        with pytest.raises(AttributeError):
            manager.external_domain = "new.domain.com"


class TestRoomManagerBaseAbstractMethods:
    """Test suite verifying abstract methods must be implemented"""

    def test_cannot_instantiate_abstract_class(self):
        """Test that RoomManagerBase cannot be instantiated directly"""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            RoomManagerBase(hub_index=1, on_room_activated=Mock())

    def test_concrete_class_must_implement_initialize_pool(self):
        """Test that concrete class must implement initialize_pool"""

        class IncompleteManager(RoomManagerBase):
            def _create_room(self, room_id: str, port: int) -> bool:
                return True

            def _delete_room(self, room_id: str) -> None:
                pass

            def get_room_address(self, room: Room) -> str:
                return "test"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteManager(hub_index=1, on_room_activated=Mock())

    def test_concrete_class_must_implement_create_room(self):
        """Test that concrete class must implement _create_room"""

        class IncompleteManager(RoomManagerBase):
            def initialize_pool(self) -> None:
                pass

            def _delete_room(self, room_id: str) -> None:
                pass

            def get_room_address(self, room: Room) -> str:
                return "test"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteManager(hub_index=1, on_room_activated=Mock())

    def test_concrete_class_must_implement_delete_room(self):
        """Test that concrete class must implement _delete_room"""

        class IncompleteManager(RoomManagerBase):
            def initialize_pool(self) -> None:
                pass

            def _create_room(self, room_id: str, port: int) -> bool:
                return True

            def get_room_address(self, room: Room) -> str:
                return "test"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteManager(hub_index=1, on_room_activated=Mock())

    def test_concrete_class_must_implement_get_room_address(self):
        """Test that concrete class must implement get_room_address"""

        class IncompleteManager(RoomManagerBase):
            def initialize_pool(self) -> None:
                pass

            def _create_room(self, room_id: str, port: int) -> bool:
                return True

            def _delete_room(self, room_id: str) -> None:
                pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteManager(hub_index=1, on_room_activated=Mock())


class TestRoomManagerBaseConstant:
    """Test suite for class constant"""

    def test_starting_pool_size_constant(self):
        """Test that STARTING_POOL_SIZE is defined and has correct value"""
        assert hasattr(RoomManagerBase, 'STARTING_POOL_SIZE')
        assert RoomManagerBase.STARTING_POOL_SIZE == 3

    def test_starting_pool_size_accessible_from_instance(self):
        """Test that STARTING_POOL_SIZE is accessible from instance"""
        manager = ConcreteRoomManager(hub_index=1, on_room_activated=Mock())
        assert manager.STARTING_POOL_SIZE == 3