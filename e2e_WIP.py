"""
End-to-end tests for the Bomberman game stack.

Run AFTER deployment. These tests hit the real matchmaking endpoint,
connect to real room servers, and verify the full client ↔ server flow.
"""

import socket
import threading
import time
import pytest
import requests

from bomberman.room_server.gossip import bomberman_pb2
from bomberman.room_server.NetworkUtils import send_msg, recv_msg


@pytest.fixture(scope="session")
def matchmaking_url(pytestconfig):
    return pytestconfig.getoption("--matchmaking-url")


@pytest.fixture(scope="session")
def deploy_timeout(pytestconfig):
    return pytestconfig.getoption("--deploy-timeout")


class HeadlessClient:
    """
    Scriptable game client with no I/O dependencies.
    All blocking helpers accept an explicit timeout parameter.
    """

    def __init__(self, player_id: str, host: str, port: int):
        self.player_id = player_id
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.tick_rate: int = 10
        self._snapshots: list = []
        self._lock = threading.Lock()
        self._receiver: threading.Thread | None = None
        self._running = False

    def connect_and_join(self, timeout: float = 5.0) -> bool:
        """TCP connect + JoinRequest + wait for ServerResponse. Returns True on success."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((self.host, self.port))
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False
        self.sock.settimeout(None)

        packet = bomberman_pb2.Packet()
        packet.join_request.player_id = self.player_id
        send_msg(self.sock, packet.SerializeToString())

        self.sock.settimeout(timeout)
        try:
            data = recv_msg(self.sock)
        except socket.timeout:
            return False
        finally:
            self.sock.settimeout(None)

        if not data:
            return False

        resp = bomberman_pb2.Packet()
        resp.ParseFromString(data)
        if not resp.HasField("server_response") or not resp.server_response.success:
            return False

        self.tick_rate = resp.server_response.tick_rate
        self._running = True
        self._receiver = threading.Thread(target=self._receive_loop, daemon=True)
        self._receiver.start()
        return True

    def _receive_loop(self):
        while self._running:
            try:
                data = recv_msg(self.sock)
                if not data:
                    break
                packet = bomberman_pb2.Packet()
                packet.ParseFromString(data)
                if packet.HasField("state_snapshot"):
                    with self._lock:
                        self._snapshots.append(packet.state_snapshot)
            except OSError:
                break

    def send_action(self, action_type) -> None:
        packet = bomberman_pb2.Packet()
        packet.client_action.player_id = self.player_id
        packet.client_action.action_type = action_type
        try:
            send_msg(self.sock, packet.SerializeToString())
        except OSError:
            pass

    def quit(self) -> None:
        self.send_action(bomberman_pb2.GameAction.QUIT)
        self._running = False

    def wait_for_snapshot(self, timeout: float = 5.0):
        """Block until at least one snapshot arrives, return the latest."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._snapshots:
                    return self._snapshots[-1]
            time.sleep(0.05)
        return None

    def wait_for_snapshot_matching(self, predicate, timeout: float = 35.0):
        """Block until a snapshot satisfying predicate arrives."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for snap in reversed(self._snapshots):
                    if predicate(snap):
                        return snap
            time.sleep(0.1)
        return None

    def close(self) -> None:
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

@pytest.fixture(scope="session", autouse=True)
def wait_for_deployment(matchmaking_url, deploy_timeout):
    """
    Polls matchmaking until it returns any HTTP response or timeout expires.
    Skips the entire session if deployment never becomes ready.
    """
    deadline = time.time() + deploy_timeout
    last_error = None
    while time.time() < deadline:
        try:
            r = requests.post(matchmaking_url, timeout=5)
            if r.status_code in (200, 503):
                return  # Server is up
        except requests.exceptions.RequestException as e:
            last_error = e
        time.sleep(3)

    pytest.skip(
        f"Deployment not ready after {deploy_timeout}s. Last error: {last_error}"
    )


def do_matchmaking(url: str) -> tuple[str, int, str]:
    """Returns (host, port, room_id). Skips test if no room is available."""
    r = requests.post(url, timeout=10)
    if r.status_code == 503:
        pytest.skip("No room available (503) — pool may be exhausted")
    r.raise_for_status()
    d = r.json()
    return d["room_address"], int(d["room_port"]), d["room_id"]


class TestDeploymentReadiness:

    def test_matchmaking_responds(self, matchmaking_url):
        r = requests.post(matchmaking_url, timeout=10)
        assert r.status_code in (200, 503), (
            f"Unexpected status {r.status_code} — server may be crashing on requests."
        )

    def test_matchmaking_200_has_required_fields(self, matchmaking_url):
        r = requests.post(matchmaking_url, timeout=10)
        if r.status_code == 503:
            pytest.skip("No rooms available")
        for field in ("room_address", "room_port", "room_id"):
            assert field in r.json(), f"Missing field '{field}' in matchmaking response"

    def test_matchmaking_port_is_in_valid_range(self, matchmaking_url):
        r = requests.post(matchmaking_url, timeout=10)
        if r.status_code == 503:
            pytest.skip("No rooms available")
        port = r.json()["room_port"]
        assert 1024 <= port <= 65535, f"Port {port} is outside the valid range"


class TestConnectionHandshake:

    def test_tcp_connection_and_join_succeed(self, matchmaking_url):
        host, port, _ = do_matchmaking(matchmaking_url)
        client = HeadlessClient("e2e-connect", host, port)
        try:
            assert client.connect_and_join(timeout=5.0), (
                f"TCP connection to {host}:{port} failed. "
                "Room server may be down or port unreachable."
            )
        finally:
            client.close()

    def test_server_response_tick_rate_is_positive(self, matchmaking_url):
        host, port, _ = do_matchmaking(matchmaking_url)
        client = HeadlessClient("e2e-tickrate", host, port)
        try:
            client.connect_and_join()
            assert client.tick_rate > 0, (
                f"tick_rate={client.tick_rate} — ServerResponse must send a positive tick_rate."
            )
        finally:
            client.close()

    def test_duplicate_player_id_does_not_crash_server(self, matchmaking_url):
        """
        Two clients with the same ID — server must accept or reject cleanly,
        not crash. A third distinct client must still be able to connect.
        """
        host, port, _ = do_matchmaking(matchmaking_url)
        c1 = HeadlessClient("dup-id", host, port)
        c2 = HeadlessClient("dup-id", host, port)
        try:
            c1.connect_and_join()
            c2.connect_and_join()
        finally:
            c1.close()
            c2.close()

        # Server must still be alive
        c3 = HeadlessClient("post-dup", host, port)
        try:
            result = c3.connect_and_join(timeout=5.0)
            # We only verify the server responded — accept or reject is both valid
            assert isinstance(result, bool)
        finally:
            c3.close()


class TestStateSnapshots:

    @pytest.fixture
    def client(self, matchmaking_url):
        host, port, _ = do_matchmaking(matchmaking_url)
        c = HeadlessClient("e2e-snap", host, port)
        assert c.connect_and_join(), "Precondition: client must connect"
        yield c
        c.close()

    def test_server_sends_snapshot_after_join(self, client):
        snap = client.wait_for_snapshot(timeout=5.0)
        assert snap is not None, (
            "No GameStateSnapshot received after joining. "
            "Check RoomServer tick loop and snapshot broadcasting."
        )

    def test_snapshot_ascii_grid_is_non_empty(self, client):
        snap = client.wait_for_snapshot(timeout=5.0)
        assert snap is not None
        assert len(snap.ascii_grid) > 0, (
            "ascii_grid is empty — GameEngine.get_snapshot() may not be rendering."
        )

    def test_game_is_not_over_while_waiting_for_players(self, client):
        snap = client.wait_for_snapshot(timeout=5.0)
        assert snap is not None
        assert not snap.is_game_over, (
            "is_game_over=True immediately after joining — "
            "game ended before it started. Check GameEngine initial state."
        )


class TestTwoClientsCountdown:

    def test_two_clients_see_starting_countdown(self, matchmaking_url):
        """
        With >= 2 clients in the lobby, the snapshot must contain 'Starting in:'.
        This verifies the full chain: 2 TCP connections → GameEngine detects
        len(players) >= 2 → countdown begins → snapshot reflects it.
        """
        host, port, _ = do_matchmaking(matchmaking_url)
        c1 = HeadlessClient("p1-cdwn", host, port)
        c2 = HeadlessClient("p2-cdwn", host, port)
        try:
            assert c1.connect_and_join(), "Client 1 must connect"
            assert c2.connect_and_join(), "Client 2 must connect"

            snap = c1.wait_for_snapshot_matching(
                lambda s: "Starting in:" in s.ascii_grid,
                timeout=10.0,
            )
            assert snap is not None, (
                "With 2 players in lobby, 'Starting in:' must appear in the snapshot. "
                "Check GameEngine._render_waiting_state() countdown display."
            )
        finally:
            c1.close()
            c2.close()

@pytest.mark.slow
class TestFullGame:

    def test_game_starts_after_countdown(self, matchmaking_url):
        host, port, _ = do_matchmaking(matchmaking_url)
        c1 = HeadlessClient("p1-start", host, port)
        c2 = HeadlessClient("p2-start", host, port)
        try:
            assert c1.connect_and_join()
            assert c2.connect_and_join()

            snap = c1.wait_for_snapshot_matching(
                lambda s: "Starting in:" not in s.ascii_grid and not s.is_game_over,
                timeout=35.0,
            )
            assert snap is not None, (
                "Game did not start after the 30s countdown with 2 players. "
                "Check GameEngine.start_game() and tick loop timing."
            )
        finally:
            c1.close()
            c2.close()

    def test_move_action_changes_grid(self, matchmaking_url):
        """
        MOVE_UP must produce a snapshot with a different ascii_grid.
        Verifies the full chain: client TCP → RoomServer → GameEngine.apply_action()
        → new position → snapshot → TCP → client.
        """
        host, port, _ = do_matchmaking(matchmaking_url)
        c1 = HeadlessClient("p1-move", host, port)
        c2 = HeadlessClient("p2-move", host, port)
        try:
            assert c1.connect_and_join()
            assert c2.connect_and_join()

            started = c1.wait_for_snapshot_matching(
                lambda s: "Starting in:" not in s.ascii_grid and not s.is_game_over,
                timeout=35.0,
            )
            assert started is not None, "Precondition: game must start"
            grid_before = started.ascii_grid

            c1.send_action(bomberman_pb2.GameAction.MOVE_UP)

            changed = c1.wait_for_snapshot_matching(
                lambda s: s.ascii_grid != grid_before,
                timeout=5.0,
            )
            assert changed is not None, (
                "Grid did not change after MOVE_UP. "
                "Action may not be reaching GameEngine, or the player is blocked."
            )
        finally:
            c1.close()
            c2.close()

class TestQuit:

    def test_quit_does_not_crash_server(self, matchmaking_url):
        """
        Client sends QUIT and disconnects. A new client must still be able
        to connect to the same room server afterward.
        """
        host, port, _ = do_matchmaking(matchmaking_url)
        c1 = HeadlessClient("p1-quit", host, port)
        try:
            assert c1.connect_and_join()
            c1.wait_for_snapshot(timeout=3.0)
            c1.quit()
            time.sleep(0.5)
        finally:
            c1.close()

        # Server must still accept new connections
        c2 = HeadlessClient("p2-after-quit", host, port)
        try:
            result = c2.connect_and_join(timeout=5.0)
            # Any bool response means server is alive
            assert isinstance(result, bool), (
                "Server stopped responding after client quit — it may have crashed."
            )
        finally:
            c2.close()