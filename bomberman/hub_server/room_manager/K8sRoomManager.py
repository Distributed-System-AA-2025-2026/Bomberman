import os
from typing import Callable
from kubernetes import client, config

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase, print_console


class K8sRoomManager(RoomManagerBase):
    ROOM_PORT_START = 10001
    ROOM_PORT_END = 10100

    _k8s_core: client.CoreV1Api
    _external_domain: str
    _namespace: str

    def __init__(
        self,
        hub_index: int,
        on_room_activated: Callable[[Room], None],
        external_domain: str = "bomberman.romanellas.cloud"
    ):
        super().__init__(hub_index, on_room_activated)
        self._external_domain = external_domain
        self._namespace = os.environ.get("K8S_NAMESPACE", "bomberman")

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._k8s_core = client.CoreV1Api()

    def initialize_pool(self) -> None:
        print_console(f"Initializing K8s room pool with {self.POOL_SIZE} rooms", 'RoomHandling')

        for i in range(self.POOL_SIZE):
            room_id = f"hub{self._hub_index}-{i}"
            port = self._allocate_port()

            if port is None:
                print_console(f"No available ports for room {room_id}", "Error")
                continue

            if self._create_room(room_id, port):
                room = Room(
                    room_id=room_id,
                    owner_hub_index=self._hub_index,
                    status=RoomStatus.DORMANT,
                    external_port=port,
                    internal_service=f"room-{room_id}-svc.{self._namespace}.svc.cluster.local"
                )
                self._local_rooms[room_id] = room
                print_console(f"Created dormant room {room_id} on port {port}", "RoomHandling")

        self._update_nginx_config()

    def _allocate_port(self) -> int | None:
        used_ports = {r.external_port for r in self._local_rooms.values()}
        for port in range(self.ROOM_PORT_START, self.ROOM_PORT_END + 1):
            if port not in used_ports:
                return port
        return None

    def _create_room(self, room_id: str, port: int) -> bool:
        try:
            self._create_room_pod(room_id)
            self._create_room_service(room_id)
            return True
        except Exception as e:
            print_console(f"Failed to create room {room_id}: {e}", "Error")
            return False

    def _create_room_pod(self, room_id: str) -> None:
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}",
                namespace=self._namespace,
                labels={
                    "app": "room",
                    "room-id": room_id,
                    "owner-hub": str(self._hub_index)
                }
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="room",
                        image="httpd:2.4",
                        ports=[client.V1ContainerPort(container_port=80)],
                        env=[
                            client.V1EnvVar(name="ROOM_ID", value=room_id),
                            client.V1EnvVar(name="OWNER_HUB", value=str(self._hub_index)),
                        ]
                    )
                ]
            )
        )
        self._k8s_core.create_namespaced_pod(namespace=self._namespace, body=pod)

    def _create_room_service(self, room_id: str) -> None:
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}-svc",
                namespace=self._namespace
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"room-id": room_id},
                ports=[client.V1ServicePort(port=80, target_port=80)]
            )
        )
        self._k8s_core.create_namespaced_service(namespace=self._namespace, body=service)

    def _delete_room(self, room_id: str) -> None:
        try:
            self._k8s_core.delete_namespaced_pod(
                name=f"room-{room_id}",
                namespace=self._namespace
            )
            self._k8s_core.delete_namespaced_service(
                name=f"room-{room_id}-svc",
                namespace=self._namespace
            )
        except Exception as e:
            print_console(f"Failed to delete room {room_id}: {e}", "Error")

    def get_room_address(self, room: Room) -> str:
        return self._external_domain

    def _update_nginx_config(self) -> None:
        nginx_conf = """events {
    worker_connections 1024;
}

stream {
"""
        for room in self._local_rooms.values():
            nginx_conf += f"""
    server {{
        listen {room.external_port};
        proxy_pass {room.internal_service}:80;
    }}
"""
        nginx_conf += "}\n"

        config_map = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name="nginx-tcp-config"),
            data={"nginx.conf": nginx_conf}
        )

        try:
            self._k8s_core.patch_namespaced_config_map(
                name="nginx-tcp-config",
                namespace=self._namespace,
                body=config_map
            )
        except client.exceptions.ApiException as e:
            if e.status == 404:
                self._k8s_core.create_namespaced_config_map(
                    namespace=self._namespace,
                    body=config_map
                )
            else:
                raise