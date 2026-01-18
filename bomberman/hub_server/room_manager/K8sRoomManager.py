import os
from typing import Callable
from kubernetes import client, config

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase, print_console


class K8sRoomManager(RoomManagerBase):
    POOL_SIZE = 1  # Una room per hub

    _k8s_core: client.CoreV1Api
    _external_address: str
    _namespace: str

    def __init__(
            self,
            hub_index: int,
            on_room_activated: Callable[[Room], None],
            external_address: str = None
    ):
        super().__init__(hub_index, on_room_activated)
        self._namespace = os.environ.get("K8S_NAMESPACE", "bomberman")
        self._external_address = external_address or os.environ.get(
            "EXTERNAL_ADDRESS",
            "bomberman.romanellas.cloud"
        )

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._k8s_core = client.CoreV1Api()

    def initialize_pool(self) -> None:
        print_console(f"Initializing K8s room pool with {self.POOL_SIZE} room(s)")

        for i in range(self.POOL_SIZE):
            room_id = f"hub{self._hub_index}-{i}"

            node_port = self._create_room(room_id)

            if node_port is None:
                continue

            room = Room(
                room_id=room_id,
                owner_hub_index=self._hub_index,
                status=RoomStatus.DORMANT,
                external_port=node_port,
                internal_service=f"room-{room_id}-svc.{self._namespace}.svc.cluster.local"
            )
            self._local_rooms[room_id] = room
            print_console(f"Created dormant room {room_id} on NodePort {node_port}")

    def _create_room(self, room_id: str) -> int | None:
        try:
            self._create_room_pod(room_id)
            node_port = self._create_room_service(room_id)
            return node_port
        except Exception as e:
            print_console(f"Failed to create room {room_id}: {e}", "Error")
            return None

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
                        image="httpd:2.4",  # TODO: tua immagine room
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

    def _create_room_service(self, room_id: str) -> int:
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}-svc",
                namespace=self._namespace
            ),
            spec=client.V1ServiceSpec(
                type="NodePort",
                selector={"room-id": room_id},
                ports=[client.V1ServicePort(
                    port=80,
                    target_port=80
                )]
            )
        )

        created = self._k8s_core.create_namespaced_service(
            namespace=self._namespace,
            body=service
        )

        return created.spec.ports[0].node_port

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
        return self._external_address