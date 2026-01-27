import pytest
from unittest.mock import Mock, patch, call, MagicMock
import os

from kubernetes import client
from kubernetes.config import ConfigException

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.K8sRoomManager import K8sRoomManager


class TestK8sRoomManagerInitialization:
    """Test suite for K8sRoomManager initialization"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_with_default_parameters(self, mock_core_api, mock_config):
        """Test initialization with default parameters"""
        callback = Mock()

        manager = K8sRoomManager(hub_index=5, on_room_activated=callback)

        assert manager._hub_index == 5
        assert manager._on_room_activated is callback
        assert manager._local_rooms == {}
        assert manager.STARTING_POOL_SIZE == 1
        mock_config.load_incluster_config.assert_called_once()
        mock_core_api.assert_called_once()

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_with_custom_external_address(self, mock_core_api, mock_config):
        """Test initialization with custom external address"""
        callback = Mock()

        manager = K8sRoomManager(
            hub_index=1,
            on_room_activated=callback,
            external_address="custom.domain.com"
        )

        assert manager._external_address == "custom.domain.com"

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_reads_namespace_from_env(self, mock_core_api, mock_config):
        """Test that namespace is read from K8S_NAMESPACE env var"""
        callback = Mock()

        with patch.dict(os.environ, {'K8S_NAMESPACE': 'custom-namespace'}):
            manager = K8sRoomManager(hub_index=1, on_room_activated=callback)

        assert manager._namespace == 'custom-namespace'

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_default_namespace_if_env_not_set(self, mock_core_api, mock_config):
        """Test default namespace when K8S_NAMESPACE is not set"""
        callback = Mock()

        with patch.dict(os.environ, {}, clear=True):
            manager = K8sRoomManager(hub_index=1, on_room_activated=callback)

        assert manager._namespace == 'bomberman'

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_reads_external_address_from_env(self, mock_core_api, mock_config):
        """Test that external_address is read from EXTERNAL_ADDRESS env var"""
        callback = Mock()

        with patch.dict(os.environ, {'EXTERNAL_ADDRESS': 'env.domain.com'}):
            manager = K8sRoomManager(hub_index=1, on_room_activated=callback)

        assert manager._external_address == 'env.domain.com'

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_initialization_external_address_parameter_overrides_env(self, mock_core_api, mock_config):
        """Test that external_address parameter overrides env var"""
        callback = Mock()

        with patch.dict(os.environ, {'EXTERNAL_ADDRESS': 'env.domain.com'}):
            manager = K8sRoomManager(
                hub_index=1,
                on_room_activated=callback,
                external_address='param.domain.com'
            )

        assert manager._external_address == 'param.domain.com'


class TestK8sRoomManagerCraftRoomId:
    """Test suite for craft_room_id method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_craft_room_id_format(self, mock_core_api, mock_config):
        """Test that craft_room_id follows the pattern hub{index}-{room_index}"""
        manager = K8sRoomManager(hub_index=5, on_room_activated=Mock())

        room_id = manager.craft_room_id(3)
        assert room_id == "hub5-3"

    @pytest.mark.parametrize("hub_index,room_index,expected", [
        (0, 0, "hub0-0"),
        (1, 5, "hub1-5"),
        (10, 99, "hub10-99"),
        (999, 1234, "hub999-1234"),
    ])
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_craft_room_id_various_indices(self, mock_core_api, mock_config, hub_index, room_index, expected):
        """Test craft_room_id with various hub and room indices"""
        manager = K8sRoomManager(hub_index=hub_index, on_room_activated=Mock())

        room_id = manager.craft_room_id(room_index)
        assert room_id == expected


class TestK8sRoomManagerInitializePool:
    """Test suite for initialize_pool method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_initialize_pool_creates_starting_pool_size_rooms(self, mock_print, mock_core_api, mock_config):
        """Test that initialize_pool creates STARTING_POOL_SIZE rooms"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_and_register_room') as mock_create:
            mock_create.return_value = Mock()
            manager.initialize_pool()

        assert mock_create.call_count == 1  # STARTING_POOL_SIZE = 1
        mock_create.assert_called_with(0)

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_initialize_pool_sets_last_used_room_index(self, mock_print, mock_core_api, mock_config):
        """Test that initialize_pool sets _last_used_room_index correctly"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_and_register_room') as mock_create:
            mock_create.return_value = Mock()
            manager.initialize_pool()

        # _last_used_room_index should be max(STARTING_POOL_SIZE - 1, 0) = 0
        assert manager._last_used_room_index == 0

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_initialize_pool_logs_message(self, mock_print, mock_core_api, mock_config):
        """Test that initialize_pool logs initialization message"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_and_register_room') as mock_create:
            mock_create.return_value = Mock()
            manager.initialize_pool()

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "Initializing K8s room pool" in call_args
        assert "1 room(s)" in call_args


class TestK8sRoomManagerGetNextRoomIndex:
    """Test suite for _get_next_room_index method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_get_next_room_index_increments(self, mock_core_api, mock_config):
        """Test that _get_next_room_index increments the counter"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._last_used_room_index = 5

        next_index = manager._get_next_room_index()
        assert next_index == 6
        assert manager._last_used_room_index == 6

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_get_next_room_index_multiple_calls(self, mock_core_api, mock_config):
        """Test sequential calls to _get_next_room_index"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._last_used_room_index = 0

        indices = [manager._get_next_room_index() for _ in range(5)]
        assert indices == [1, 2, 3, 4, 5]
        assert manager._last_used_room_index == 5


class TestK8sRoomManagerCreateRoom:
    """Test suite for _create_room method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_create_room_success(self, mock_core_api, mock_config):
        """Test successful room creation"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        mock_service = Mock()
        mock_service.spec.ports = [Mock(node_port=30001)]
        manager._k8s_core.create_namespaced_service.return_value = mock_service

        with patch.object(manager, '_create_room_pod'):
            node_port = manager._create_room("test-room")

        assert node_port == 30001

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_create_room_pod_creation_fails(self, mock_print, mock_core_api, mock_config):
        """Test _create_room when pod creation fails"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_room_pod', side_effect=Exception("Pod creation failed")):
            node_port = manager._create_room("test-room")

        assert node_port is None
        mock_print.assert_called_once()
        assert "Failed to create room" in mock_print.call_args[0][0]
        assert "Error" in mock_print.call_args[0]

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_create_room_service_creation_fails(self, mock_print, mock_core_api, mock_config):
        """Test _create_room when service creation fails"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_room_pod'):
            with patch.object(manager, '_create_room_service', side_effect=Exception("Service failed")):
                node_port = manager._create_room("test-room")

        assert node_port is None
        assert "Failed to create room" in mock_print.call_args[0][0]


class TestK8sRoomManagerCreateRoomPod:
    """Test suite for _create_room_pod method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_create_room_pod_creates_correct_pod_spec(self, mock_core_api, mock_config):
        """Test that _create_room_pod creates pod with correct specification"""
        manager = K8sRoomManager(hub_index=5, on_room_activated=Mock())
        manager._namespace = "test-namespace"

        manager._create_room_pod("test-room")

        # Verify create_namespaced_pod was called
        manager._k8s_core.create_namespaced_pod.assert_called_once()
        call_args = manager._k8s_core.create_namespaced_pod.call_args

        assert call_args[1]['namespace'] == 'test-namespace'

        pod_spec = call_args[1]['body']
        assert isinstance(pod_spec, client.V1Pod)
        assert pod_spec.metadata.name == "room-test-room"
        assert pod_spec.metadata.namespace == "test-namespace"
        assert pod_spec.metadata.labels == {
            "app": "room",
            "room-id": "test-room",
            "owner-hub": "5"
        }

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_create_room_pod_container_spec(self, mock_core_api, mock_config):
        """Test that pod has correct container specification"""
        manager = K8sRoomManager(hub_index=3, on_room_activated=Mock())

        manager._create_room_pod("room-123")

        call_args = manager._k8s_core.create_namespaced_pod.call_args
        pod_spec = call_args[1]['body']

        container = pod_spec.spec.containers[0]
        assert container.name == "room"
        assert container.image == "docker.io/library/bomberman-room:latest"
        assert len(container.ports) == 1
        assert container.ports[0].container_port == 5000

        # Check environment variables
        env_dict = {env.name: env.value for env in container.env}
        assert env_dict["ROOM_ID"] == "room-123"
        assert env_dict["OWNER_HUB"] == "3"


class TestK8sRoomManagerCreateRoomService:
    """Test suite for _create_room_service method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_create_room_service_creates_nodeport_service(self, mock_core_api, mock_config):
        """Test that _create_room_service creates NodePort service"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._namespace = "test-namespace"

        mock_service = Mock()
        mock_service.spec.ports = [Mock(node_port=30123)]
        manager._k8s_core.create_namespaced_service.return_value = mock_service

        node_port = manager._create_room_service("test-room")

        assert node_port == 30123
        manager._k8s_core.create_namespaced_service.assert_called_once()

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_create_room_service_spec(self, mock_core_api, mock_config):
        """Test service specification details"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._namespace = "custom-ns"

        mock_service = Mock()
        mock_service.spec.ports = [Mock(node_port=30001)]
        manager._k8s_core.create_namespaced_service.return_value = mock_service

        manager._create_room_service("room-abc")

        call_args = manager._k8s_core.create_namespaced_service.call_args
        assert call_args[1]['namespace'] == 'custom-ns'

        service_spec = call_args[1]['body']
        assert isinstance(service_spec, client.V1Service)
        assert service_spec.metadata.name == "room-room-abc-svc"
        assert service_spec.metadata.namespace == "custom-ns"
        assert service_spec.spec.type == "NodePort"
        assert service_spec.spec.selector == {"room-id": "room-abc"}

        port_spec = service_spec.spec.ports[0]
        assert port_spec.port == 5000
        assert port_spec.target_port == 5000


class TestK8sRoomManagerDeleteRoom:
    """Test suite for _delete_room method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_delete_room_success(self, mock_core_api, mock_config):
        """Test successful room deletion"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._namespace = "test-namespace"

        manager._delete_room("test-room")

        manager._k8s_core.delete_namespaced_pod.assert_called_once_with(
            name="room-test-room",
            namespace="test-namespace"
        )
        manager._k8s_core.delete_namespaced_service.assert_called_once_with(
            name="room-test-room-svc",
            namespace="test-namespace"
        )

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_delete_room_pod_deletion_fails(self, mock_print, mock_core_api, mock_config):
        """Test _delete_room when pod deletion fails"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._k8s_core.delete_namespaced_pod.side_effect = Exception("Delete failed")

        manager._delete_room("test-room")

        mock_print.assert_called_once()
        assert "Failed to delete room" in mock_print.call_args[0][0]
        assert "Error" in mock_print.call_args[0]

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_delete_room_service_deletion_fails(self, mock_print, mock_core_api, mock_config):
        """Test _delete_room when service deletion fails (after pod deleted)"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager._k8s_core.delete_namespaced_service.side_effect = Exception("Service delete failed")

        manager._delete_room("test-room")

        # Pod deletion should succeed
        manager._k8s_core.delete_namespaced_pod.assert_called_once()
        # Error should be logged
        mock_print.assert_called_once()
        assert "Failed to delete room" in mock_print.call_args[0][0]


class TestK8sRoomManagerGetRoomAddress:
    """Test suite for get_room_address method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_get_room_address_returns_external_address(self, mock_core_api, mock_config):
        """Test that get_room_address returns the configured external address"""
        manager = K8sRoomManager(
            hub_index=1,
            on_room_activated=Mock(),
            external_address="my.domain.com"
        )

        room = Room(
            room_id="test",
            owner_hub_index=1,
            status=RoomStatus.ACTIVE,
            external_port=30001,
            internal_service="test-svc"
        )

        address = manager.get_room_address(room)
        assert address == "my.domain.com"

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_get_room_address_independent_of_room(self, mock_core_api, mock_config):
        """Test that returned address doesn't depend on room properties"""
        manager = K8sRoomManager(
            hub_index=1,
            on_room_activated=Mock(),
            external_address="fixed.address.com"
        )

        rooms = [
            Room("r1", 1, RoomStatus.ACTIVE, 30001, "svc1"),
            Room("r2", 2, RoomStatus.DORMANT, 30002, "svc2"),
            Room("r3", 3, RoomStatus.PLAYING, 30003, "svc3"),
        ]

        addresses = [manager.get_room_address(room) for room in rooms]
        assert all(addr == "fixed.address.com" for addr in addresses)


class TestK8sRoomManagerCreateAndRegisterRoom:
    """Test suite for _create_and_register_room method"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_create_and_register_room_success(self, mock_print, mock_core_api, mock_config):
        """Test successful room creation and registration"""
        manager = K8sRoomManager(hub_index=3, on_room_activated=Mock())
        manager._namespace = "test-ns"

        with patch.object(manager, '_create_room', return_value=30555):
            room = manager._create_and_register_room(7)

        assert room is not None
        assert room.room_id == "hub3-7"
        assert room.owner_hub_index == 3
        assert room.status == RoomStatus.DORMANT
        assert room.external_port == 30555
        assert room.internal_service == "room-hub3-7-svc.test-ns.svc.cluster.local"

        # Verify room is registered
        assert "hub3-7" in manager._local_rooms
        assert manager._local_rooms["hub3-7"] is room

        # Verify logging
        mock_print.assert_called_once()
        assert "Created dormant room hub3-7" in mock_print.call_args[0][0]
        assert "NodePort 30555" in mock_print.call_args[0][0]

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_create_and_register_room_creation_fails(self, mock_print, mock_core_api, mock_config):
        """Test _create_and_register_room when creation fails"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        with patch.object(manager, '_create_room', return_value=None):
            room = manager._create_and_register_room(0)

        assert room is None
        assert len(manager._local_rooms) == 0
        # No success log should be printed
        mock_print.assert_not_called()


class TestK8sRoomManagerActivateRoom:
    """Test suite for activate_room method (overridden)"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console')
    def test_activate_room_uses_existing_dormant(self, mock_print, mock_core_api, mock_config):
        """Test that activate_room uses existing dormant room if available"""
        callback = Mock()
        manager = K8sRoomManager(hub_index=1, on_room_activated=callback)

        # Add a dormant room
        room = Room("hub1-0", 1, RoomStatus.DORMANT, 30001, "svc")
        manager._local_rooms["hub1-0"] = room

        activated = manager.activate_room()

        assert activated is room
        assert room.status == RoomStatus.ACTIVE
        callback.assert_called_once_with(room)

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_activate_room_returns_none_when_creation_fails(self, mock_print, mock_core_api, mock_config):
        """Test activate_room returns None when room creation fails"""
        callback = Mock()
        manager = K8sRoomManager(hub_index=1, on_room_activated=callback)
        manager._last_used_room_index = 0

        with patch.object(manager, '_create_and_register_room', return_value=None):
            with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
                activated = manager.activate_room()

        assert activated is None
        callback.assert_not_called()


class TestK8sRoomManagerIntegrationWithBase:
    """Test suite for integration with RoomManagerBase"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_cleanup_calls_delete_room(self, mock_core_api, mock_config):
        """Test that cleanup calls _delete_room for each room"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        # Add some rooms
        for i in range(3):
            room = Room(f"hub1-{i}", 1, RoomStatus.ACTIVE, 30000 + i, f"svc{i}")
            manager._local_rooms[f"hub1-{i}"] = room

        with patch.object(manager, '_delete_room') as mock_delete:
            with patch('bomberman.hub_server.room_manager.RoomManagerBase.print_console'):
                manager.cleanup()

        assert mock_delete.call_count == 3
        assert len(manager._local_rooms) == 0


class TestK8sRoomManagerEdgeCases:
    """Test suite for edge cases and error conditions"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_empty_room_id_handling(self, mock_core_api, mock_config):
        """Test behavior with empty room ID"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        room_id = manager.craft_room_id(0)
        assert room_id == "hub1-0"  # Should still work

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_negative_room_index(self, mock_core_api, mock_config):
        """Test craft_room_id with negative index"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        room_id = manager.craft_room_id(-5)
        assert room_id == "hub1--5"  # Will create invalid but predictable ID

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_very_large_hub_index(self, mock_core_api, mock_config):
        """Test with very large hub index"""
        manager = K8sRoomManager(hub_index=999999, on_room_activated=Mock())

        room_id = manager.craft_room_id(123)
        assert room_id == "hub999999-123"

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_api_client_stored_correctly(self, mock_core_api, mock_config):
        """Test that CoreV1Api client is stored in _k8s_core"""
        mock_api_instance = Mock()
        mock_core_api.return_value = mock_api_instance

        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())

        assert manager._k8s_core is mock_api_instance

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.print_console')
    def test_initialize_pool_with_modified_pool_size(self, mock_print, mock_core_api, mock_config):
        """Test initialize_pool with modified STARTING_POOL_SIZE"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        manager.STARTING_POOL_SIZE = 5

        with patch.object(manager, '_create_and_register_room') as mock_create:
            mock_create.return_value = Mock()
            manager.initialize_pool()

        assert mock_create.call_count == 5
        assert manager._last_used_room_index == 4


class TestK8sRoomManagerConstants:
    """Test suite for class constants"""

    @patch('bomberman.hub_server.room_manager.K8sRoomManager.config')
    @patch('bomberman.hub_server.room_manager.K8sRoomManager.client.CoreV1Api')
    def test_starting_pool_size_constant(self, mock_core_api, mock_config):
        """Test STARTING_POOL_SIZE value"""
        manager = K8sRoomManager(hub_index=1, on_room_activated=Mock())
        assert manager.STARTING_POOL_SIZE == 1

    def test_starting_pool_size_class_level(self):
        """Test STARTING_POOL_SIZE is defined at class level"""
        assert hasattr(K8sRoomManager, 'STARTING_POOL_SIZE')
        assert K8sRoomManager.STARTING_POOL_SIZE == 1