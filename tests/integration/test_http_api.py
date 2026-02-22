import os
import pytest
from fastapi.testclient import TestClient


def make_client(gossip_port: int) -> TestClient:
    """
    Creates a TestClient for a fresh HubServer instance on the given port.
    Must be used as a context manager to trigger lifespan startup/shutdown.
    """
    os.environ["GOSSIP_PORT"] = str(gossip_port)
    os.environ["HOSTNAME"] = "hub-0.local"
    os.environ["HUB_FANOUT"] = "4"
    os.environ["HUB_DISCOVERY_MODE"] = "manual"

    # Import after env vars are set — HubServer reads them at construction time
    from bomberman.hub_server.__main__ import create_application
    return TestClient(create_application())


# Utility endpoints: /, /health, /ready
class TestUtilityEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        with make_client(19300) as c:
            yield c

    def test_root_returns_200(self, client):
        assert client.get("/").status_code == 200

    def test_root_contains_expected_body(self, client):
        assert client.get("/").json() == {"content": "Go away."}

    def test_health_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_health_returns_healthy_status(self, client):
        assert client.get("/health").json() == {"status": "healthy"}

    def test_ready_returns_200_when_hub_running(self, client):
        assert client.get("/ready").status_code == 200

    def test_ready_returns_ready_status(self, client):
        assert client.get("/ready").json() == {"status": "ready"}


class TestMatchmakingResponseContract:

    @pytest.fixture(scope="class")
    def matchmaking_response(self):
        with make_client(19310) as client:
            yield client.post("/matchmaking").json()

    def test_returns_200(self):
        with make_client(19311) as client:
            assert client.post("/matchmaking").status_code == 200

    def test_response_has_room_id(self, matchmaking_response):
        assert "room_id" in matchmaking_response
        assert matchmaking_response["room_id"] != ""

    def test_response_has_room_address(self, matchmaking_response):
        assert "room_address" in matchmaking_response
        assert matchmaking_response["room_address"] != ""

    def test_response_has_room_port(self, matchmaking_response):
        assert "room_port" in matchmaking_response
        assert isinstance(matchmaking_response["room_port"], int)
        assert matchmaking_response["room_port"] > 0

    def test_response_has_request_code_200(self, matchmaking_response):
        assert matchmaking_response["request_code"] == 200

    def test_room_id_belongs_to_this_hub(self, matchmaking_response):
        # LocalRoomManager names rooms as hub{index}-{n}, hub index is 0
        assert matchmaking_response["room_id"].startswith("hub0-")


class TestMatchmakingRoomAssignment:

    @pytest.fixture(scope="class")
    def client(self):
        with make_client(19320) as c:
            yield c

    def test_first_four_calls_get_same_room(self, client):
        """A room accepts up to max_players=4 before a new one is activated."""
        ids = [client.post("/matchmaking").json()["room_id"] for _ in range(4)]
        assert len(set(ids)) == 1, f"Expected same room for 4 players, got: {ids}"

    def test_fifth_call_gets_different_room(self, client):
        # After setup above, room 0 is full — this call must activate room 1
        r5 = client.post("/matchmaking").json()["room_id"]
        assert r5 != "hub0-0"

    def test_second_room_also_serves_four_players(self, client):
        # room 1 was activated by call 5, so calls 6-8 should stay on it
        ids = [client.post("/matchmaking").json()["room_id"] for _ in range(3)]
        assert all(i == "hub0-1" for i in ids), \
            f"Expected room hub0-1 for 3 more players, got: {ids}"

    def test_all_three_rooms_activated_after_twelve_calls(self, client):
        # Calls 9-12 fill room 2
        ids = {client.post("/matchmaking").json()["room_id"] for _ in range(4)}
        assert "hub0-2" in ids

    def test_503_when_all_rooms_exhausted(self, client):
        # All 3 rooms are now full (12 calls done above)
        assert client.post("/matchmaking").status_code == 503

    def test_503_response_has_meaningful_detail(self, client):
        r = client.post("/matchmaking")
        assert "detail" in r.json()


class TestRoomLifecycle:

    @pytest.fixture(scope="class")
    def client(self):
        with make_client(19330) as c:
            yield c

    @pytest.fixture(scope="class")
    def active_room_id(self, client):
        return client.post("/matchmaking").json()["room_id"]

    def test_room_start_returns_200(self, client, active_room_id):
        assert client.post(f"/room/{active_room_id}/start").status_code == 200

    def test_room_start_response_contract(self, client, active_room_id):
        r = client.post(f"/room/{active_room_id}/start").json()
        assert r["response_code"] == 200
        assert r["response_message"] == "Ok."

    def test_room_is_playing_after_start(self, client, active_room_id):
        client.post(f"/room/{active_room_id}/start")
        rooms = {r["room_id"]: r for r in client.get("/debug/").json()["rooms"]}
        assert rooms[active_room_id]["status"] == "playing"

    def test_playing_room_is_not_joinable(self, client, active_room_id):
        client.post(f"/room/{active_room_id}/start")
        rooms = {r["room_id"]: r for r in client.get("/debug/").json()["rooms"]}
        assert rooms[active_room_id]["is_joinable"] is False

    def test_room_close_returns_200(self, client, active_room_id):
        assert client.post(f"/room/{active_room_id}/close").status_code == 200

    def test_room_is_dormant_after_close(self, client, active_room_id):
        client.post(f"/room/{active_room_id}/start")
        client.post(f"/room/{active_room_id}/close")
        rooms = {r["room_id"]: r for r in client.get("/debug/").json()["rooms"]}
        assert rooms[active_room_id]["status"] == "dormant"

    def test_matchmaking_skips_playing_room_and_activates_next(self, client):
        """
        If the only active room starts playing, the next matchmaking call must
        activate a new dormant room rather than returning the playing one.
        """
        r1 = client.post("/matchmaking").json()["room_id"]
        client.post(f"/room/{r1}/start")

        r2 = client.post("/matchmaking").json()["room_id"]
        assert r2 != r1, "Matchmaking returned a room that is already PLAYING"


class TestDebugEndpoint:

    @pytest.fixture(scope="class")
    def client(self):
        with make_client(19340) as c:
            yield c

    def test_debug_returns_200(self, client):
        assert client.get("/debug/").status_code == 200

    def test_debug_hub_index_is_zero(self, client):
        assert client.get("/debug/").json()["hub_index"] == 0

    def test_debug_hostname_matches_env(self, client):
        assert client.get("/debug/").json()["hostname"] == "hub-0.local"

    def test_debug_discovery_mode_is_manual(self, client):
        assert client.get("/debug/").json()["discovery_mode"] == "manual"

    def test_debug_no_active_rooms_before_matchmaking(self, client):
        # No matchmaking called yet — rooms are dormant, not in HubState
        data = client.get("/debug/").json()
        active = [r for r in data["rooms"] if r["status"] == "active"]
        assert len(active) == 0

    def test_debug_active_room_count_increments_after_matchmaking(self, client):
        client.post("/matchmaking")
        data = client.get("/debug/").json()
        assert data["active_rooms_count"] == 1

    def test_debug_room_entry_has_expected_fields(self, client):
        data = client.get("/debug/").json()
        room = data["rooms"][0]
        for field in ("room_id", "owner_hub_index", "status", "external_port", "is_local", "is_joinable"):
            assert field in room, f"Missing field '{field}' in debug room entry"

    def test_debug_room_is_marked_as_local(self, client):
        room = client.get("/debug/").json()["rooms"][0]
        assert room["is_local"] is True

    def test_debug_nonce_increases_with_activity(self, client):
        nonce_before = client.get("/debug/").json()["last_nonce"]
        client.post("/matchmaking")
        nonce_after = client.get("/debug/").json()["last_nonce"]
        assert nonce_after > nonce_before