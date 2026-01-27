import threading
import time
from typing import Callable

import requests

from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.hublogging import print_console


class RoomHealthMonitor:
    CHECK_INTERVAL = 15.0  # Secondi tra ogni check
    API_PORT = 8080  # Porta dell'API HTTP della room
    TIMEOUT = 3.0  # Timeout per la chiamata HTTP
    EXPECTED_STATUS = "WAITING_FOR_PLAYERS"  # Stato che indica room joinable

    def __init__(
            self,
            state: HubState,
            my_index: int,
            on_room_unhealthy: Callable[[Room], None]
    ):
        """
        Args:
            state: HubState condiviso con HubServer
            my_index: Indice di questo hub (per logging)
            on_room_unhealthy: Callback chiamata quando una room non e' piu' joinable.
                               Riceve l'oggetto Room come parametro.
        """
        self._state = state
        self._my_index = my_index
        self._on_room_unhealthy = on_room_unhealthy
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Avvia il thread di monitoring."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print_console("RoomHealthMonitor started", "Info")

    def stop(self) -> None:
        """Ferma il thread di monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        print_console("RoomHealthMonitor stopped", "Info")

    def _monitor_loop(self) -> None:
        """Loop principale del monitor."""
        while self._running:
            try:
                self._check_all_rooms()
            except Exception as e:
                print_console(f"Error in health check loop: {e}", "Error")

            # Sleep interrompibile per shutdown rapido
            for _ in range(int(self.CHECK_INTERVAL)):
                if not self._running:
                    break
                time.sleep(1.0)

    def _check_all_rooms(self) -> None:
        """Controlla tutte le room ACTIVE."""
        rooms = self._state.get_all_rooms()

        for room in rooms:
            if not self._running:
                break

            # Controlla solo room ACTIVE (quelle che dovrebbero essere joinable)
            if room.status != RoomStatus.ACTIVE:
                continue

            # Skip room senza internal_service (room remote di cui non conosco l'indirizzo interno)
            if not room.internal_service:
                continue

            if not self._is_room_healthy(room):
                print_console(
                    f"Room {room.room_id} is unhealthy (not responding or not WAITING_FOR_PLAYERS)",
                    "RoomHealthMonitor"
                )
                self._on_room_unhealthy(room)

    def _is_room_healthy(self, room: Room) -> bool:
        try:
            url = f"http://{room.internal_service}:{self.API_PORT}/status"
            response = requests.get(url, timeout=self.TIMEOUT)

            if response.status_code != 200:
                print_console(
                    f"Room {room.room_id} returned status code {response.status_code}",
                    "RoomHealthMonitor"
                )
                return False

            data = response.json()
            status = data.get("status")

            if status == self.EXPECTED_STATUS:
                return True

            # Room ha risposto ma non e' in WAITING_FOR_PLAYERS
            print_console(
                f"Room {room.room_id} status is '{status}' (expected '{self.EXPECTED_STATUS}')",
                "RoomHealthMonitor"
            )
            return False

        except requests.exceptions.Timeout:
            print_console(f"Room {room.room_id} health check timed out", "RoomHealthMonitor")
            return False
        except requests.exceptions.ConnectionError:
            print_console(f"Room {room.room_id} connection refused", "RoomHealthMonitor")
            return False
        except Exception as e:
            print_console(f"Room {room.room_id} health check failed: {e}", "RoomHealthMonitor")
            return False