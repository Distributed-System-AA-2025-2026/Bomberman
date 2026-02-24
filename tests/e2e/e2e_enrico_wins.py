import socket
import threading
import time
import pytest
import requests

from bomberman.room_server.gossip import bomberman_pb2
from bomberman.room_server.NetworkUtils import send_msg, recv_msg

TICK_INTERVAL = 0.15      # seconds between moves (1 tick = 0.1s + 0.05s margin)
BOMB_FUSE_SEC = 2.0       # GameEngine.BOMB_TIMER_SEC
EXPLOSION_SEC = 1.0       # GameEngine.EXPLOSION_DURATION_SEC
POST_BOMB_WAIT = BOMB_FUSE_SEC + EXPLOSION_SEC + 1.0  # 4s total
COUNTDOWN_WAIT = 35.0     # wait for the 30s lobby countdown to expire
WINNER_WAIT = 8.0         # seconds to wait for game-over snapshot after bomb

class HeadlessClient:
    """
    Scriptable game client — identical protocol to GameClient, no terminal I/O.
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
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((self.host, self.port))
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False
        self.sock.settimeout(None)

        pkt = bomberman_pb2.Packet()
        pkt.join_request.player_id = self.player_id
        send_msg(self.sock, pkt.SerializeToString())

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
                pkt = bomberman_pb2.Packet()
                pkt.ParseFromString(data)
                if pkt.HasField("state_snapshot"):
                    with self._lock:
                        self._snapshots.append(pkt.state_snapshot)
            except OSError:
                break

    def send_action(self, action_type) -> None:
        pkt = bomberman_pb2.Packet()
        pkt.client_action.player_id = self.player_id
        pkt.client_action.action_type = action_type
        try:
            send_msg(self.sock, pkt.SerializeToString())
        except OSError:
            pass

    def wait_for_snapshot_matching(self, predicate, timeout: float = 35.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for snap in reversed(self._snapshots):
                    if predicate(snap):
                        return snap
            time.sleep(0.1)
        return None

    def latest_snapshot(self):
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def close(self) -> None:
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


@pytest.fixture(scope="session")
def matchmaking_url(pytestconfig):
    return pytestconfig.getoption("--matchmaking-url")


@pytest.fixture(scope="session")
def deploy_timeout(pytestconfig):
    return pytestconfig.getoption("--deploy-timeout")


@pytest.fixture(scope="session", autouse=True)
def wait_for_deployment(matchmaking_url, deploy_timeout):
    """Polls matchmaking until ready or timeout. Skips session if never ready."""
    deadline = time.time() + deploy_timeout
    last_error = None
    while time.time() < deadline:
        try:
            r = requests.post(matchmaking_url, timeout=5)
            if r.status_code in (200, 503):
                return
        except requests.exceptions.RequestException as e:
            last_error = e
        time.sleep(3)
    pytest.skip(f"Deployment not ready after {deploy_timeout}s. Last error: {last_error}")


@pytest.mark.slow
class TestEnricoWins:

    def test_enrico_beats_daniele_with_scripted_moves(self, matchmaking_url):
        """
        Move sequence (Enrico):
            MOVE_LEFT  x3
            MOVE_DOWN  x3
            MOVE_LEFT  x4
            MOVE_UP    x3
            PLACE_BOMB
            MOVE_DOWN  x4   <- escape
        """
        r = requests.post(matchmaking_url, timeout=10)
        if r.status_code == 503:
            pytest.skip("No room available (503)")
        r.raise_for_status()
        d = r.json()
        host, port = d["room_address"], int(d["room_port"])

        daniele = HeadlessClient("Daniele", host, port)
        enrico  = HeadlessClient("Enrico",  host, port)

        try:
            assert daniele.connect_and_join(timeout=8.0), \
                "Daniele could not connect — room server may be down"
            assert enrico.connect_and_join(timeout=8.0), \
                "Enrico could not connect — room server may be down"

            assert enrico.wait_for_snapshot_matching(
                lambda s: "Starting in:" in s.ascii_grid,
                timeout=10.0,
            ) is not None, "Countdown did not start with 2 players"

            started = enrico.wait_for_snapshot_matching(
                lambda s: "Starting in:" not in s.ascii_grid and not s.is_game_over,
                timeout=COUNTDOWN_WAIT,
            )
            assert started is not None, \
                f"Game did not start after {COUNTDOWN_WAIT}s countdown"

            def move(action, n=1):
                for _ in range(n):
                    enrico.send_action(action)
                    time.sleep(TICK_INTERVAL)

            move(bomberman_pb2.GameAction.MOVE_LEFT,  3)
            move(bomberman_pb2.GameAction.MOVE_DOWN,  3)
            move(bomberman_pb2.GameAction.MOVE_LEFT,  4)
            move(bomberman_pb2.GameAction.MOVE_UP,    3)
            move(bomberman_pb2.GameAction.PLACE_BOMB, 1)
            move(bomberman_pb2.GameAction.MOVE_DOWN,  4)

            time.sleep(POST_BOMB_WAIT)

            winner_snap = enrico.wait_for_snapshot_matching(
                lambda s: s.is_game_over,
                timeout=WINNER_WAIT,
            )

            assert winner_snap is not None, (
                "Game did not end after bomb exploded.\n"
                f"Last snapshot:\n{enrico.latest_snapshot()}"
            )
            assert "Winner: Player 'Enrico'" in winner_snap.ascii_grid, (
                f"Expected Enrico to win.\nActual grid:\n{winner_snap.ascii_grid}\n\n"
                "Move sequence may need recalibration for the current map."
            )

        finally:
            daniele.close()
            enrico.close()