from unittest.mock import MagicMock, patch
from kubernetes.client.exceptions import ApiException

from bomberman.hub_server.room_manager.K8sRoomManager import K8sRoomManager
from bomberman.common.RoomState import RoomStatus

def make_manager(hub_index: int = 0) -> K8sRoomManager:
    with patch("bomberman.hub_server.room_manager.K8sRoomManager.config"), \
         patch("bomberman.hub_server.room_manager.K8sRoomManager.client"):
        mgr = K8sRoomManager(
            hub_index=hub_index,
            on_room_activated=MagicMock(),
            external_address="test.example.com",
        )
    mgr._k8s_core = MagicMock()
    mgr._last_used_room_index = 0
    return mgr


def make_pod(room_id: str, phase: str) -> MagicMock:
    pod = MagicMock()
    pod.metadata.labels = {"app": "room", "room-id": room_id, "owner-hub": "0"}
    pod.status.phase = phase
    return pod


def make_service(node_port: int) -> MagicMock:
    svc = MagicMock()
    svc.spec.ports = [MagicMock(node_port=node_port)]
    return svc

class TestRecoverExistingRooms:

    def test_running_pod_is_recovered_as_active(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Running")]
        mgr._k8s_core.read_namespaced_service.return_value = make_service(30000)

        mgr._recover_existing_rooms()

        assert "hub0-0" in mgr._local_rooms
        assert mgr._local_rooms["hub0-0"].status == RoomStatus.ACTIVE

    def test_pending_pod_is_recovered_as_active(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Pending")]
        mgr._k8s_core.read_namespaced_service.return_value = make_service(30000)

        mgr._recover_existing_rooms()

        recovered = mgr._local_rooms.get("hub0-0")
        assert recovered is not None
        assert recovered.status == RoomStatus.DORMANT

    def test_failed_pod_is_ignored(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Failed")]

        mgr._recover_existing_rooms()

        assert "hub0-0" not in mgr._local_rooms

    def test_succeeded_pod_is_ignored(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Succeeded")]

        mgr._recover_existing_rooms()

        assert "hub0-0" not in mgr._local_rooms

    def test_pod_without_room_id_label_is_ignored(self):
        mgr = make_manager()
        pod = make_pod("hub0-0", "Running")
        pod.metadata.labels = {"app": "room"}  # room-id missing
        mgr._k8s_core.list_namespaced_pod.return_value.items = [pod]

        mgr._recover_existing_rooms()

        assert len(mgr._local_rooms) == 0

    def test_service_lookup_failure_silently_skips_room(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Running")]
        mgr._k8s_core.read_namespaced_service.side_effect = Exception("service not found")

        mgr._recover_existing_rooms()  # must not raise

        assert "hub0-0" not in mgr._local_rooms

    def test_recovered_room_has_correct_internal_service_name(self):
        mgr = make_manager()
        mgr._namespace = "bomberman"
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Running")]
        mgr._k8s_core.read_namespaced_service.return_value = make_service(30000)

        mgr._recover_existing_rooms()

        assert mgr._local_rooms["hub0-0"].internal_service == \
               "room-hub0-0-svc.bomberman.svc.cluster.local"

    def test_recovered_room_has_correct_node_port(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.return_value.items = [make_pod("hub0-0", "Running")]
        mgr._k8s_core.read_namespaced_service.return_value = make_service(31337)

        mgr._recover_existing_rooms()

        assert mgr._local_rooms["hub0-0"].external_port == 31337

    def test_last_used_index_updated_to_max_recovered(self):
        mgr = make_manager()
        pods = [make_pod("hub0-2", "Running"), make_pod("hub0-5", "Running")]
        mgr._k8s_core.list_namespaced_pod.return_value.items = pods
        mgr._k8s_core.read_namespaced_service.return_value = make_service(30000)

        mgr._recover_existing_rooms()

        assert mgr._last_used_room_index == 5

    def test_k8s_api_failure_is_caught_and_does_not_raise(self):
        mgr = make_manager()
        mgr._k8s_core.list_namespaced_pod.side_effect = Exception("k8s unavailable")

        mgr._recover_existing_rooms()  # must not raise

        assert len(mgr._local_rooms) == 0

    def test_multiple_running_pods_all_recovered(self):
        mgr = make_manager()
        pods = [make_pod(f"hub0-{i}", "Running") for i in range(3)]
        mgr._k8s_core.list_namespaced_pod.return_value.items = pods
        mgr._k8s_core.read_namespaced_service.return_value = make_service(30000)

        mgr._recover_existing_rooms()

        assert len(mgr._local_rooms) == 3

class TestWaitForPodDeletion:

    def test_returns_immediately_on_404(self):
        mgr = make_manager()
        mgr._k8s_core.read_namespaced_pod.side_effect = ApiException(status=404)

        mgr._wait_for_pod_deletion("room-hub0-0")  # must not raise, must not loop

        mgr._k8s_core.read_namespaced_pod.assert_called_once()

    def test_polls_until_pod_disappears(self):
        """Simulates pod existing for 2 polls, then 404 on 3rd."""
        mgr = make_manager()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return MagicMock()  # pod still exists
            raise ApiException(status=404)

        mgr._k8s_core.read_namespaced_pod.side_effect = side_effect

        with patch("bomberman.hub_server.room_manager.K8sRoomManager.sleep"):
            mgr._wait_for_pod_deletion("room-hub0-0", timeout=10)

        assert call_count == 3

class TestCreateAndRegisterRoom:

    def test_room_registered_as_dormant_after_creation(self):
        mgr = make_manager()
        created_svc = MagicMock()
        created_svc.spec.ports = [MagicMock(node_port=30001)]
        mgr._k8s_core.create_namespaced_service.return_value = created_svc

        room = mgr._create_and_register_room(0)

        assert room is not None
        assert room.status == RoomStatus.DORMANT

    def test_room_has_correct_id(self):
        mgr = make_manager(hub_index=2)
        created_svc = MagicMock()
        created_svc.spec.ports = [MagicMock(node_port=30002)]
        mgr._k8s_core.create_namespaced_service.return_value = created_svc

        room = mgr._create_and_register_room(4)

        assert room.room_id == "hub2-4"

    def test_room_external_port_comes_from_service_node_port(self):
        mgr = make_manager()
        created_svc = MagicMock()
        created_svc.spec.ports = [MagicMock(node_port=31999)]
        mgr._k8s_core.create_namespaced_service.return_value = created_svc

        room = mgr._create_and_register_room(0)

        assert room.external_port == 31999

    def test_room_added_to_local_rooms(self):
        mgr = make_manager()
        created_svc = MagicMock()
        created_svc.spec.ports = [MagicMock(node_port=30001)]
        mgr._k8s_core.create_namespaced_service.return_value = created_svc

        mgr._create_and_register_room(0)

        assert "hub0-0" in mgr._local_rooms

    def test_returns_none_when_k8s_creation_fails(self):
        mgr = make_manager()
        mgr._k8s_core.create_namespaced_pod.side_effect = ApiException(status=403)

        result = mgr._create_and_register_room(0)

        assert result is None

    def test_pod_leak_when_service_creation_fails(self):
        mgr = make_manager()
        mgr._k8s_core.create_namespaced_pod.return_value = MagicMock()
        mgr._k8s_core.create_namespaced_service.side_effect = ApiException(status=500)

        with patch.object(mgr, '_delete_room_pod') as mock_delete:
            result = mgr._create_and_register_room(0)

        assert result is None
        mock_delete.assert_called_once_with("room-hub0-0")

    def test_room_internal_service_name_is_correct(self):
        mgr = make_manager(hub_index=1)
        mgr._namespace = "bomberman"
        created_svc = MagicMock()
        created_svc.spec.ports = [MagicMock(node_port=30001)]
        mgr._k8s_core.create_namespaced_service.return_value = created_svc

        room = mgr._create_and_register_room(0)

        assert room.internal_service == "room-hub1-0-svc.bomberman.svc.cluster.local"