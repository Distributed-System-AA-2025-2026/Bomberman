import os
from time import sleep
from typing import Callable
from kubernetes import client, config

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.room_manager.RoomManagerBase import RoomManagerBase, print_console


class K8sRoomManager(RoomManagerBase):
    STARTING_POOL_SIZE = 1  # Una room per hub
    ROOM_IMAGE = "docker.io/library/bomberman-room:latest"
    ROOM_PORT = 5000

    _k8s_core: client.CoreV1Api
    _external_address: str
    _namespace: str
    _last_used_room_index: int

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

    def craft_room_id(self, room_index: int) -> str:
        return f"hub{self._hub_index}-{room_index}"

    def initialize_pool(self) -> None:
        sleep(5)
        print_console(f"Initializing K8s room pool with {self.STARTING_POOL_SIZE} room(s)")

        # Prima recupera room esistenti di questo hub
        self._recover_existing_rooms()

        existing_count = len(self._local_rooms)
        for i in range(existing_count, self.STARTING_POOL_SIZE):
            self._create_and_register_room(i)

        if self._local_rooms:
            indices = [int(rid.split("-")[-1]) for rid in self._local_rooms.keys()]
            self._last_used_room_index = max(indices)
        else:
            self._last_used_room_index = 0

    def _recover_existing_rooms(self) -> None:
        """Recupera le room esistenti da k8s dopo un restart."""
        try:
            # Trova pod room di questo hub
            pods = self._k8s_core.list_namespaced_pod(
                namespace=self._namespace,
                label_selector=f"app=room,owner-hub={self._hub_index}"
            )

            for pod in pods.items:
                room_id = pod.metadata.labels.get("room-id")
                if not room_id:
                    continue

                # Recupera il service per la NodePort
                try:
                    svc = self._k8s_core.read_namespaced_service(
                        name=f"room-{room_id}-svc",
                        namespace=self._namespace
                    )
                    node_port = svc.spec.ports[0].node_port
                except Exception:
                    continue

                phase = pod.status.phase
                if phase == "Running":
                    status = RoomStatus.ACTIVE
                elif phase == "Pending":
                    status = RoomStatus.ACTIVE
                else:
                    continue

                room = Room(
                    room_id=room_id,
                    owner_hub_index=self._hub_index,
                    status=status,
                    external_port=node_port,
                    internal_service=f"room-{room_id}-svc.{self._namespace}.svc.cluster.local"
                )
                self._local_rooms[room_id] = room
                print_console(f"Recovered room {room_id} (port {node_port}, status {status})")

            # Aggiorna last_used_room_index
            if self._local_rooms:
                indices = [int(rid.split("-")[-1]) for rid in self._local_rooms.keys()]
                self._last_used_room_index = max(indices)

        except Exception as e:
            print_console(f"Failed to recover rooms: {e}", "Error")

    def _get_next_room_index(self) -> int:
        self._last_used_room_index = self._last_used_room_index + 1
        return self._last_used_room_index

    def _create_room(self, room_id: str) -> int | None:
        try:
            self._create_room_pod(room_id)
            node_port = self._create_room_service(room_id)
            return node_port
        except Exception as e:
            print_console(f"Failed to create room {room_id}: {e}", "Error")
            return None

    def _create_room_pod(self, room_id: str) -> None:
        # Construct the Hub API URL for the room to connect back
        if os.environ.get("DISCOVERY_MODE") == "k8s":
            hub_api_url = f"http://localhost:8000"
        else:
            hub_api_url = f"https://bomberman.romanellas.cloud"
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
                        image=self.ROOM_IMAGE,
                        image_pull_policy="Never",
                        ports=[client.V1ContainerPort(
                            container_port=self.ROOM_PORT,
                            protocol="TCP"
                        )],
                        env=[
                            client.V1EnvVar(name="ROOM_ID", value=room_id),
                            client.V1EnvVar(name="OWNER_HUB", value=str(self._hub_index)),
                            client.V1EnvVar(name="HUB_API_URL", value=hub_api_url)
                        ],
                        resources=client.V1ResourceRequirements(
                            requests={"memory": "64Mi", "cpu": "100m"},
                            limits={"memory": "256Mi", "cpu": "500m"}
                        )
                    )
                ],
                restart_policy="OnFailure"
            )
        )
        self._k8s_core.create_namespaced_pod(namespace=self._namespace, body=pod)

    def _create_room_service(self, room_id: str) -> int:
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=f"room-{room_id}-svc",
                namespace=self._namespace,
                labels={
                    "app": "room",
                    "room-id": room_id,
                    "owner-hub": str(self._hub_index)
                }
            ),
            spec=client.V1ServiceSpec(
                type="NodePort",
                selector={"room-id": room_id},
                ports=[
                    client.V1ServicePort(
                        port=self.ROOM_PORT,
                        target_port=self.ROOM_PORT,
                        protocol="TCP",
                        name="game"
                    ),
                    client.V1ServicePort(
                        port=8080,
                        target_port=8080,
                        protocol="TCP",
                        name="api"
                    )
                ]
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

    def _create_and_register_room(self, room_index: int) -> Room | None:
        room_id = self.craft_room_id(room_index)

        node_port = self._create_room(room_id)
        if node_port is None:
            return None

        room = Room(
            room_id=room_id,
            owner_hub_index=self._hub_index,
            status=RoomStatus.DORMANT,
            external_port=node_port,
            internal_service=f"room-{room_id}-svc.{self._namespace}.svc.cluster.local"
        )
        self._local_rooms[room_id] = room
        print_console(f"Created dormant room {room_id} on NodePort {node_port}")

        return room

    def activate_room(self) -> Room | None:
        room = super().activate_room()
        if room is not None:
            return room

        # Crea e registra nuova room
        new_room = self._create_and_register_room(self._get_next_room_index())
        if new_room is None:
            return None

        return super().activate_room()
