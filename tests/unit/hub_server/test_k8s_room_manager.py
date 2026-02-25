import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from bomberman.hub_server.room_manager.K8sRoomManager import K8sRoomManager
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus


class TestK8sRoomManagerUnit:

    def _create_manager(self, hub_index=0):
        with patch("bomberman.hub_server.room_manager.K8sRoomManager.config"), \
             patch("bomberman.hub_server.room_manager.K8sRoomManager.client"):
            mgr = K8sRoomManager(
                hub_index=hub_index,
                on_room_activated=MagicMock(),
                external_address="test.example.com",
            )
        mgr._last_used_room_index = 0
        return mgr

    def test_craft_room_id(self):
        mgr = self._create_manager(hub_index=3)
        assert mgr.craft_room_id(0) == "hub3-0"
        assert mgr.craft_room_id(7) == "hub3-7"

    def test_get_next_room_index_increments(self):
        mgr = self._create_manager()
        mgr._last_used_room_index = 5
        assert mgr._get_next_room_index() == 6
        assert mgr._get_next_room_index() == 7

    def test_get_room_address_returns_external(self):
        mgr = self._create_manager()
        room = Room("room-1", 0, RoomStatus.ACTIVE, 10001, "svc")
        assert mgr.get_room_address(room) == "test.example.com"

    def test_activate_room_uses_base_when_dormant_available(self):
        mgr = self._create_manager()
        dormant = Room("room-0", 0, RoomStatus.DORMANT, 10001, "svc")
        mgr._local_rooms["room-0"] = dormant
        result = mgr.activate_room()
        assert result is dormant
        assert dormant.status == RoomStatus.ACTIVE

    def test_activate_room_creates_new_when_no_dormant(self):
        """Se non ci sono room dormant, K8sRoomManager prova a creare una nuova room.
        _create_and_register_room aggiunge la room a _local_rooms e poi super().activate_room() la attiva."""
        mgr = self._create_manager()
        mgr._local_rooms["room-0"] = Room("room-0", 0, RoomStatus.ACTIVE, 10001, "svc")

        new_room = Room("hub0-1", 0, RoomStatus.DORMANT, 30002, "new-svc")

        def mock_create(idx):
            mgr._local_rooms[new_room.room_id] = new_room
            return new_room

        with patch.object(mgr, '_create_and_register_room', side_effect=mock_create):
            result = mgr.activate_room()
        assert result is new_room
        assert new_room.status == RoomStatus.ACTIVE

    def test_activate_room_returns_none_when_creation_fails(self):
        mgr = self._create_manager()
        with patch.object(mgr, '_create_and_register_room', return_value=None):
            result = mgr.activate_room()
        assert result is None

    def test_delete_room_handles_404_pod_gracefully(self):
        mgr = self._create_manager()
        from kubernetes.client.exceptions import ApiException
        mgr._k8s_core = MagicMock()
        mgr._k8s_core.delete_namespaced_pod.side_effect = ApiException(status=404)
        mgr._k8s_core.delete_namespaced_service.return_value = None

        with patch.object(mgr, '_wait_for_pod_deletion'):
            mgr._delete_room("room-0")

    def test_delete_room_propagates_non_404_error(self):
        mgr = self._create_manager()
        from kubernetes.client.exceptions import ApiException
        mgr._k8s_core = MagicMock()
        mgr._k8s_core.delete_namespaced_pod.side_effect = ApiException(status=500)

        with patch.object(mgr, '_wait_for_pod_deletion'):
            mgr._delete_room("room-0")

class TestK8sInitializePool:

    def _create_manager(self, hub_index=0):
        with patch("bomberman.hub_server.room_manager.K8sRoomManager.config"), \
             patch("bomberman.hub_server.room_manager.K8sRoomManager.client"):
            mgr = K8sRoomManager(
                hub_index=hub_index,
                on_room_activated=MagicMock(),
                external_address="test.example.com",
            )
        mgr._last_used_room_index = 0
        return mgr

    @patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep")
    def test_creates_room_when_recovery_finds_nothing(self, mock_sleep):
        """Recovery returns 0 rooms => must create STARTING_POOL_SIZE (1) room."""
        mgr = self._create_manager()
        with patch.object(mgr, '_recover_existing_rooms'), \
             patch.object(mgr, '_create_and_register_room') as mock_create:
            # Simulate _create_and_register_room adding a room
            def fake_create(idx):
                room = Room(f"hub0-{idx}", 0, RoomStatus.DORMANT, 30000 + idx, "svc")
                mgr._local_rooms[room.room_id] = room
                return room
            mock_create.side_effect = fake_create

            mgr.initialize_pool()

            mock_create.assert_called_once_with(0)
        assert mgr._last_used_room_index == 0

    @patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep")
    def test_skips_creation_when_recovery_finds_enough_rooms(self, mock_sleep):
        """Recovery already found >= STARTING_POOL_SIZE rooms => no new rooms created."""
        mgr = self._create_manager()

        def fake_recover():
            mgr._local_rooms["hub0-0"] = Room("hub0-0", 0, RoomStatus.ACTIVE, 30000, "svc")

        with patch.object(mgr, '_recover_existing_rooms', side_effect=fake_recover), \
             patch.object(mgr, '_create_and_register_room') as mock_create:
            mgr.initialize_pool()
            mock_create.assert_not_called()

        assert mgr._last_used_room_index == 0

    @patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep")
    def test_last_used_index_picks_max_from_room_ids(self, mock_sleep):
        """_last_used_room_index must be the highest index suffix across all room IDs."""
        mgr = self._create_manager()

        def fake_recover():
            mgr._local_rooms["hub0-3"] = Room("hub0-3", 0, RoomStatus.ACTIVE, 30003, "svc")
            mgr._local_rooms["hub0-7"] = Room("hub0-7", 0, RoomStatus.ACTIVE, 30007, "svc")

        with patch.object(mgr, '_recover_existing_rooms', side_effect=fake_recover), \
             patch.object(mgr, '_create_and_register_room'):
            mgr.initialize_pool()

        assert mgr._last_used_room_index == 7

    @patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep")
    def test_last_used_index_zero_when_no_rooms_at_all(self, mock_sleep):
        """If recovery and creation both produce nothing => index stays 0."""
        mgr = self._create_manager()
        with patch.object(mgr, '_recover_existing_rooms'), \
             patch.object(mgr, '_create_and_register_room', return_value=None):
            mgr.initialize_pool()

        assert mgr._last_used_room_index == 0
        assert len(mgr._local_rooms) == 0

    @patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep")
    def test_sleeps_before_doing_anything(self, mock_sleep):
        """Pool init waits 5s for K8s cluster readiness before proceeding."""
        mgr = self._create_manager()
        with patch.object(mgr, '_recover_existing_rooms'), \
             patch.object(mgr, '_create_and_register_room'):
            mgr.initialize_pool()
        mock_sleep.assert_called_once_with(5)


class TestK8sActivateRoomOverride:

    def _create_manager(self, hub_index=0):
        with patch("bomberman.hub_server.room_manager.K8sRoomManager.config"), \
             patch("bomberman.hub_server.room_manager.K8sRoomManager.client"):
            mgr = K8sRoomManager(
                hub_index=hub_index,
                on_room_activated=MagicMock(),
                external_address="test.example.com",
            )
        mgr._last_used_room_index = 0
        return mgr

    def test_prefers_existing_dormant_over_creating_new(self):
        """Base class has a dormant room => use it, don't create anything."""
        mgr = self._create_manager()
        dormant = Room("hub0-0", 0, RoomStatus.DORMANT, 30000, "svc")
        mgr._local_rooms["hub0-0"] = dormant

        with patch.object(mgr, '_create_and_register_room') as mock_create:
            result = mgr.activate_room()
            mock_create.assert_not_called()

        assert result is dormant
        assert dormant.status == RoomStatus.ACTIVE

    def test_creates_new_room_and_activates_it(self):
        """No dormant rooms => creates a new one via K8s, then activates it."""
        mgr = self._create_manager()
        mgr._last_used_room_index = 2

        new_room = Room("hub0-3", 0, RoomStatus.DORMANT, 30003, "new-svc")

        def fake_create(idx):
            assert idx == 3, "Must use _get_next_room_index (2+1=3)"
            mgr._local_rooms[new_room.room_id] = new_room
            return new_room

        with patch.object(mgr, '_create_and_register_room', side_effect=fake_create):
            result = mgr.activate_room()

        assert result is new_room
        assert new_room.status == RoomStatus.ACTIVE

    def test_returns_none_when_k8s_creation_fails(self):
        """K8s can't create the room (API error, quota, etc.) => returns None."""
        mgr = self._create_manager()

        with patch.object(mgr, '_create_and_register_room', return_value=None):
            result = mgr.activate_room()

        assert result is None

    def test_activate_triggers_callback_on_success(self):
        """The on_room_activated callback must fire when a room gets activated."""
        callback = MagicMock()
        with patch("bomberman.hub_server.room_manager.K8sRoomManager.config"), \
             patch("bomberman.hub_server.room_manager.K8sRoomManager.client"):
            mgr = K8sRoomManager(hub_index=0, on_room_activated=callback, external_address="test.example.com")
        mgr._last_used_room_index = 0

        dormant = Room("hub0-0", 0, RoomStatus.DORMANT, 30000, "svc")
        mgr._local_rooms["hub0-0"] = dormant

        mgr.activate_room()
        callback.assert_called_once_with(dormant)