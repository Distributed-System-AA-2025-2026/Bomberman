import os
from typing import Callable
from kubernetes import client, config

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.hublogging import print_console


class RoomManager:
    ROOM_PORT_START = 10001
    ROOM_PORT_END = 10100
    POOL_SIZE = 3  # Room pre-create per hub

    _hub_index: int
    _local_rooms: dict[str, Room]  # room_id -> Room (solo le mie)
    _k8s_core: client.CoreV1Api
    _on_room_activated: Callable[[Room], None]
    _external_domain: str

    def __init__(
            self,
            hub_index: int,
            on_room_activated: Callable[[Room], None],
            external_domain: str = "bomberman.romanellas.cloud"
    ):
        self._hub_index = hub_index
        self._local_rooms = {}
        self._on_room_activated = on_room_activated
        self._external_domain = external_domain

        # Init K8s client
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()  # Fallback per dev locale

        self._k8s_core = client.CoreV1Api()

    def initialize_pool(self):
        """Crea il pool di room dormant all'avvio"""
        print_console(f"Initializing room pool with {self.POOL_SIZE} rooms")

        for i in range(self.POOL_SIZE):
            room_id = f"hub-{self._hub_index}-{i}"
            port = self._allocate_port()

            if port is None:
                print_console(f"No available ports for room {room_id}", "Error")
                continue

            try:
                self._create_room_pod(room_id)
                self._create_room_service(room_id)

                room = Room(
                    room_id=room_id,
                    owner_hub_index=self._hub_index,
                    status=RoomStatus.DORMANT,
                    external_port=port,
                    internal_service=f"room-{room_id}-svc.bomberman.svc.cluster.local"
                )
                self._local_rooms[room_id] = room

                print_console(f"Created dormant room {room_id} on port {port}")

            except Exception as e:
                print_console(f"Failed to create room {room_id}: {e}", "Error")

        self._update_nginx_config()

    def _allocate_port(self) -> int | None:
        """Alloca una porta non usata"""
        used_ports = {r.external_port for r in self._local_rooms.values()}

        for port in range(self.ROOM_PORT_START, self.ROOM_PORT_END + 1):
            if port not in used_ports:
                return port
        return None

    def _create_room_pod(self, room_id: str):
        """Crea il pod della room"""
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}",
                namespace="bomberman",
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
                        image="httpd:2.4",  # TODO: sostituire con room image
                        ports=[client.V1ContainerPort(container_port=80)],
                        env=[
                            client.V1EnvVar(name="ROOM_ID", value=room_id),
                            client.V1EnvVar(name="OWNER_HUB", value=str(self._hub_index)),
                        ]
                    )
                ]
            )
        )

        self._k8s_core.create_namespaced_pod(namespace="bomberman", body=pod)

    def _create_room_service(self, room_id: str):
        """Crea il service ClusterIP per la room"""
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}-svc",
                namespace="bomberman"
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"room-id": room_id},
                ports=[client.V1ServicePort(port=80, target_port=80)]
            )
        )

        self._k8s_core.create_namespaced_service(namespace="bomberman", body=service)

    def _update_nginx_config(self):
        """Aggiorna ConfigMap Nginx con tutte le room"""
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
                namespace="bomberman",
                body=config_map
            )
        except client.exceptions.ApiException as e:
            if e.status == 404:
                self._k8s_core.create_namespaced_config_map(
                    namespace="bomberman",
                    body=config_map
                )
            else:
                raise

    def activate_room(self) -> Room | None:
        """Attiva una room dormant e notifica via gossip"""
        for room in self._local_rooms.values():
            if room.status == RoomStatus.DORMANT:
                room.status = RoomStatus.ACTIVE
                print_console(f"Activated room {room.room_id}")

                # Notifica HubServer per gossip broadcast
                self._on_room_activated(room)

                return room

        print_console("No dormant rooms available", "Warning")
        return None

    def get_local_room(self, room_id: str) -> Room | None:
        return self._local_rooms.get(room_id)

    def get_all_local_rooms(self) -> list[Room]:
        return list(self._local_rooms.values())

    def set_room_status(self, room_id: str, status: RoomStatus):
        if room_id in self._local_rooms:
            self._local_rooms[room_id].status = status

    def cleanup(self):
        """Elimina tutte le room al shutdown"""
        print_console("Cleaning up rooms")

        for room_id in list(self._local_rooms.keys()):
            try:
                self._k8s_core.delete_namespaced_pod(
                    name=f"room-{room_id}",
                    namespace="bomberman"
                )
                self._k8s_core.delete_namespaced_service(
                    name=f"room-{room_id}-svc",
                    namespace="bomberman"
                )
            except Exception as e:
                print_console(f"Failed to cleanup room {room_id}: {e}", "Error")

        self._local_rooms.clear()