import os
import time
from unittest.mock import patch, MagicMock

from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
import socket


# ---------------------------------------------------------------------------
# Factory: real HubServer with real RoomHealthMonitor, only requests mocked
# ---------------------------------------------------------------------------

def _wait_until_listening(port: int, timeout: float = 5.0) -> None:
    """Block until the server's UDP socket is bound and ready to receive."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(("0.0.0.0", port))
            probe.close()
        except OSError:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Server did not bind to UDP port {port} within {timeout}s")


def make_server(gossip_port: int):
    os.environ["GOSSIP_PORT"] = str(gossip_port)
    os.environ["HOSTNAME"] = "hub-0.local"
    os.environ["HUB_FANOUT"] = "4"
    os.environ["HUB_DISCOVERY_MODE"] = "manual"

    from bomberman.hub_server.HubServer import HubServer
    server = HubServer("manual")
    _wait_until_listening(gossip_port)
    return server


# ---------------------------------------------------------------------------
# Local room: unhealthy → PLAYING + gossip broadcast
# ---------------------------------------------------------------------------

class TestLocalRoomUnhealthy:
    """
    When the health check fails on a local room (owner == self), HubServer
    must mark it PLAYING and broadcast ROOM_STARTED. This prevents the room
    from being assigned to new players while it's in an unknown state.
    """

    def test_local_unhealthy_room_transitions_to_playing(self):
        server = make_server(19420)
        try:
            room = Room("hub0-0", owner_hub_index=0, status=RoomStatus.ACTIVE,
                        external_port=30000, internal_service="room-hub0-0-svc:8080")
            server._state.add_room(room)

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.side_effect = __import__("requests").exceptions.ConnectionError()
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server._state.get_room("hub0-0").status == RoomStatus.PLAYING, (
                "Local room must be marked PLAYING when health check fails. "
                "Check HubServer._on_room_unhealthy local branch."
            )
        finally:
            server.stop()

    def test_local_unhealthy_room_triggers_gossip_broadcast(self):
        """
        ROOM_STARTED gossip must be broadcast so other hubs update their state.
        We detect this by checking that last_used_nonce increases.
        """
        server = make_server(19421)
        try:
            room = Room("hub0-0", owner_hub_index=0, status=RoomStatus.ACTIVE,
                        external_port=30000, internal_service="room-hub0-0-svc:8080")
            server._state.add_room(room)
            nonce_before = server.last_used_nonce

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.side_effect = __import__("requests").exceptions.ConnectionError()
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server.last_used_nonce > nonce_before, (
                "Health check failure on local room must broadcast ROOM_STARTED gossip. "
                "nonce did not increase — broadcast_room_started was not called."
            )
        finally:
            server.stop()

    def test_local_unhealthy_room_is_not_joinable_after_transition(self):
        server = make_server(19422)
        try:
            room = Room("hub0-0", owner_hub_index=0, status=RoomStatus.ACTIVE,
                        external_port=30000, internal_service="room-hub0-0-svc:8080")
            server._state.add_room(room)

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.side_effect = __import__("requests").exceptions.ConnectionError()
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert not server._state.get_room("hub0-0").is_joinable, (
                "A room in PLAYING state must not be joinable."
            )
        finally:
            server.stop()


class TestRemoteRoomUnhealthy:
    """
    When the health check fails on a remote room (owner != self), HubServer
    must remove it from HubState entirely. The local hub has no authority
    to broadcast on behalf of another hub — it just purges the stale entry.
    """

    def test_remote_unhealthy_room_is_removed_from_state(self):
        server = make_server(19430)
        try:
            room = Room("hub1-0", owner_hub_index=1, status=RoomStatus.ACTIVE,
                        external_port=30001, internal_service="room-hub1-0-svc:8080")
            server._state.add_room(room)

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.side_effect = __import__("requests").exceptions.ConnectionError()
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server._state.get_room("hub1-0") is None, (
                "Remote room must be removed from HubState when health check fails. "
                "Check HubServer._on_room_unhealthy remote branch."
            )
        finally:
            server.stop()

    def test_remote_unhealthy_room_does_not_trigger_gossip(self):
        """
        Hub-0 must NOT broadcast ROOM_STARTED for a room it does not own.
        Only the owning hub has authority to declare its rooms started.
        """
        server = make_server(19431)
        try:
            room = Room("hub1-0", owner_hub_index=1, status=RoomStatus.ACTIVE,
                        external_port=30001, internal_service="room-hub1-0-svc:8080")
            server._state.add_room(room)
            nonce_before = server.last_used_nonce

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.side_effect = __import__("requests").exceptions.ConnectionError()
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server.last_used_nonce == nonce_before, (
                "Hub must not broadcast gossip for a remote room it does not own. "
                "nonce increased unexpectedly."
            )
        finally:
            server.stop()

class TestHealthyRoomNoSideEffects:
    """
    A healthy room must be left completely untouched — no status change,
    no gossip, no removal. Verifying this is important because the callback
    is wired in HubServer and could theoretically be called incorrectly.
    """

    def test_healthy_room_stays_active(self):
        server = make_server(19440)
        try:
            room = Room("hub0-0", owner_hub_index=0, status=RoomStatus.ACTIVE,
                        external_port=30000, internal_service="room-hub0-0-svc:8080")
            server._state.add_room(room)

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.return_value = MagicMock(
                    status_code=200,
                    json=lambda: {"status": "WAITING_FOR_PLAYERS"}
                )
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server._state.get_room("hub0-0").status == RoomStatus.ACTIVE
        finally:
            server.stop()

    def test_healthy_room_produces_no_gossip(self):
        server = make_server(19441)
        try:
            room = Room("hub0-0", owner_hub_index=0, status=RoomStatus.ACTIVE,
                        external_port=30000, internal_service="room-hub0-0-svc:8080")
            server._state.add_room(room)
            nonce_before = server.last_used_nonce

            with patch("bomberman.hub_server.RoomHealthMonitor.requests.get") as mock_get:
                mock_get.return_value = MagicMock(
                    status_code=200,
                    json=lambda: {"status": "WAITING_FOR_PLAYERS"}
                )
                server._room_health_monitor._running = True
                server._room_health_monitor._check_all_rooms()

            assert server.last_used_nonce == nonce_before
        finally:
            server.stop()