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