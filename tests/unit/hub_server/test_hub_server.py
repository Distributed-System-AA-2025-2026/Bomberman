import pytest
import os
import time
from unittest.mock import MagicMock, patch

from bomberman.hub_server.HubServer import get_hub_index, HubServer
from bomberman.common.ServerReference import ServerReference
from bomberman.hub_server.Room import Room
from bomberman.common.RoomState import RoomStatus
from bomberman.hub_server.gossip import messages_pb2 as pb


class TestGetHubIndex:

    @pytest.mark.parametrize("hostname,expected", [
        ("hub-0.local", 0),
        ("hub-1.local", 1),
        ("hub-99.svc.cluster.local", 99),
        ("hub-0", 0),
        ("hub-42", 42),
    ])
    def test_valid_hostnames(self, hostname, expected):
        assert get_hub_index(hostname) == expected

    @pytest.mark.parametrize("hostname", [
        "invalid",
        "server-0.local",
        "hub-.local",
        "hub-abc.local",
        "",
        "0-hub.local",
        "hubserver-0",
    ])
    def test_invalid_hostnames_raise(self, hostname):
        with pytest.raises(ValueError):
            get_hub_index(hostname)

    def test_leading_whitespace_rejected(self):
        with pytest.raises(ValueError):
            get_hub_index(" hub-0.local")

    def test_trailing_whitespace_rejected(self):
        with pytest.raises(ValueError):
            get_hub_index("hub-0.local ")

    def test_leading_zeros_are_parsed_as_integer(self):
        """hub-007 viene parsato come indice 7 (int rimuove gli zeri)."""
        assert get_hub_index("hub-007.local") == 7


class TestHubServerCreation:

    @patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000"})
    @patch("bomberman.hub_server.HubServer.HubSocketHandler")
    @patch("bomberman.hub_server.HubServer.FailureDetector")
    @patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor")
    @patch("bomberman.hub_server.HubServer.RoomHealthMonitor")
    @patch("bomberman.hub_server.HubServer.create_room_manager")
    def test_server_initializes_with_correct_index(self, mock_rm, mock_rhm, mock_pdm, mock_fd, mock_sh):
        mock_rm.return_value = MagicMock()
        server = HubServer(discovery_mode="manual")
        assert server.hub_index == 0
        assert server.hostname == "hub-0.local"
        assert server.discovery_mode == "manual"

    @patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000", "HUB_FANOUT": "0"})
    @patch("bomberman.hub_server.HubServer.HubSocketHandler")
    def test_zero_fanout_raises(self, mock_sh):
        with pytest.raises(ValueError, match="Invalid fanout"):
            HubServer(discovery_mode="manual")

    @patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000", "HUB_FANOUT": "-1"})
    @patch("bomberman.hub_server.HubServer.HubSocketHandler")
    def test_negative_fanout_raises(self, mock_sh):
        with pytest.raises(ValueError, match="Invalid fanout"):
            HubServer(discovery_mode="manual")


class TestHubServerMessageProcessing:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler") as mock_sh, \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_handle_peer_join_creates_peer(self):
        server = self._create_server()
        payload = pb.PeerJoinPayload(joining_peer=5)
        server._handle_peer_join(payload)
        peer = server._state.get_peer(5)
        assert peer is not None

    def test_handle_peer_leave_marks_dead(self):
        server = self._create_server()
        server._ensure_peer_exists(3)
        payload = pb.PeerLeavePayload(leaving_peer=3)
        server._handle_peer_leave(payload)
        assert server._state.get_peer(3).status == 'dead'

    def test_handle_peer_alive_updates_status(self):
        server = self._create_server()
        server._ensure_peer_exists(2)
        server._state.set_peer_status(2, 'suspected')
        payload = pb.PeerAlivePayload(alive_peer=2)
        server._handle_peer_alive(payload)
        assert server._state.get_peer(2).status == 'alive'

    def test_handle_peer_suspicious_triggers_alive_broadcast_for_self(self):
        server = self._create_server()
        with patch.object(server, '_broadcast_peer_alive') as mock_broadcast:
            payload = pb.PeerSuspiciousPayload(suspicious_peer=0)
            server._handle_peer_suspicious(payload)
            mock_broadcast.assert_called_once()

    def test_handle_peer_suspicious_ignores_if_not_self(self):
        server = self._create_server()
        with patch.object(server, '_broadcast_peer_alive') as mock_broadcast:
            payload = pb.PeerSuspiciousPayload(suspicious_peer=5)
            server._handle_peer_suspicious(payload)
            mock_broadcast.assert_not_called()

    def test_handle_peer_dead_removes_suspected_peer(self):
        server = self._create_server()
        server._ensure_peer_exists(3)
        server._state.set_peer_status(3, 'suspected')
        payload = pb.PeerDeadPayload(dead_peer=3)
        server._handle_peer_dead(payload)
        assert server._state.get_peer(3).status == 'dead'

    def test_handle_peer_dead_ignores_alive_peer(self):
        """handle_peer_dead rimuove un peer solo se e' gia' suspected.
        Se e' alive, il peer viene ignorato (fiducia nel proprio failure detector)."""
        server = self._create_server()
        server._ensure_peer_exists(3)
        payload = pb.PeerDeadPayload(dead_peer=3)
        server._handle_peer_dead(payload)
        assert server._state.get_peer(3).status == 'alive'

    def test_handle_room_activated_adds_to_state(self):
        server = self._create_server()
        payload = pb.RoomActivatedPayload(
            room_id="room-5",
            owner_hub=2,
            external_port=30001,
            external_address="example.com",
        )
        server._handle_room_activated(payload)
        room = server._state.get_room("room-5")
        assert room is not None
        assert room.owner_hub_index == 2
        assert room.status == RoomStatus.ACTIVE

    def test_handle_room_started_changes_status(self):
        server = self._create_server()
        server._state.add_room(Room("room-1", 0, RoomStatus.ACTIVE, 10001, "svc"))
        payload = pb.RoomStartedPayload(room_id="room-1")
        server._handle_room_started(payload)
        assert server._state.get_room("room-1").status == RoomStatus.PLAYING

    def test_handle_room_closed_changes_status(self):
        server = self._create_server()
        server._state.add_room(Room("room-1", 0, RoomStatus.PLAYING, 10001, "svc"))
        payload = pb.RoomClosedPayload(room_id="room-1")
        server._handle_room_closed(payload)
        assert server._state.get_room("room-1").status == RoomStatus.DORMANT


class TestHubServerNonce:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_nonce_is_monotonically_increasing(self):
        server = self._create_server()
        n1 = server._get_next_nonce()
        n2 = server._get_next_nonce()
        n3 = server._get_next_nonce()
        assert n1 < n2 < n3

    def test_nonce_starts_from_one(self):
        server = self._create_server()
        assert server._get_next_nonce() == 1


class TestHubServerSendValidation:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-1.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_send_message_from_other_origin_raises(self):
        server = self._create_server()
        msg = pb.GossipMessage(nonce=1, origin=99, forwarded_by=99)
        with pytest.raises(ValueError):
            server._send_messages_and_forward(msg)

    def test_send_specific_from_other_origin_raises(self):
        server = self._create_server()
        msg = pb.GossipMessage(nonce=1, origin=99, forwarded_by=99)
        with pytest.raises(ValueError):
            server._send_messages_specific_destination(msg, ServerReference("10.0.0.1", 9000))


class TestHubServerRoomUnhealthy:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_local_unhealthy_room_transitions_to_playing(self):
        server = self._create_server()
        room = Room("room-1", 0, RoomStatus.ACTIVE, 10001, "svc")
        server._state.add_room(room)
        with patch.object(server, 'broadcast_room_started'):
            server._on_room_unhealthy(room)
        assert server._state.get_room("room-1").status == RoomStatus.PLAYING

    def test_remote_unhealthy_room_is_removed(self):
        server = self._create_server()
        room = Room("room-remote", 5, RoomStatus.ACTIVE, 10001, "")
        server._state.add_room(room)
        server._on_room_unhealthy(room)
        assert server._state.get_room("room-remote") is None


class TestHubServerGetOrActivateRoom:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-0.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_returns_existing_active_room(self):
        server = self._create_server()
        room = Room("room-1", 0, RoomStatus.ACTIVE, 10001, "svc")
        server._state.add_room(room)
        result = server.get_or_activate_room()
        assert result is room

    def test_activates_new_room_when_none_active(self):
        server = self._create_server()
        new_room = Room("room-new", 0, RoomStatus.ACTIVE, 10001, "svc")
        server._room_manager.activate_room.return_value = new_room
        result = server.get_or_activate_room()
        assert result is new_room
        server._room_manager.activate_room.assert_called_once()

    def test_returns_none_when_no_rooms_available(self):
        server = self._create_server()
        server._room_manager.activate_room.return_value = None
        result = server.get_or_activate_room()
        assert result is None


class TestHubServerBroadcasts:

    def _create_server(self, hub_index=0):
        hostname = f"hub-{hub_index}.local"
        with patch.dict(os.environ, {"HOSTNAME": hostname, "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler") as mock_sh, \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "test.example.com"
            server = HubServer(discovery_mode="manual")
        return server

    def test_broadcast_room_started_updates_state_and_forwards(self):
        server = self._create_server()
        server._state.add_room(Room("room-1", 0, RoomStatus.ACTIVE, 10001, "svc"))
        server._ensure_peer_exists(1)
        server.broadcast_room_started("room-1")
        assert server._state.get_room("room-1").status == RoomStatus.PLAYING

    def test_broadcast_room_closed_updates_state_and_forwards(self):
        server = self._create_server()
        server._state.add_room(Room("room-1", 0, RoomStatus.PLAYING, 10001, "svc"))
        server._ensure_peer_exists(1)
        server.broadcast_room_closed("room-1")
        assert server._state.get_room("room-1").status == RoomStatus.DORMANT

    def test_broadcast_room_activated_adds_to_state(self):
        server = self._create_server()
        room = Room("room-new", 0, RoomStatus.ACTIVE, 30001, "svc.local")
        server._ensure_peer_exists(1)
        server._broadcast_room_activated(room)
        assert server._state.get_room("room-new") is room

    def test_broadcast_peer_alive(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        initial_nonce = server.last_used_nonce
        server._broadcast_peer_alive()
        assert server.last_used_nonce > initial_nonce

    def test_on_peer_suspicious_broadcasts(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        initial_nonce = server.last_used_nonce
        server._on_peer_suspicious(1)
        assert server.last_used_nonce > initial_nonce

    def test_on_peer_dead_marks_dead_and_broadcasts(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        server._on_peer_dead(1)
        assert server._state.get_peer(1).status == 'dead'


class TestHubServerForwardAndDiscovery:

    def _create_server(self, discovery_mode="manual", hub_index=0):
        hostname = f"hub-{hub_index}.local"
        env = {"HOSTNAME": hostname, "GOSSIP_PORT": "9000"}
        if discovery_mode == "k8s":
            env["K8S_NAMESPACE"] = "test-ns"
            env["HUB_SERVICE_NAME"] = "hub-svc"
        with patch.dict(os.environ, env), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler") as mock_sh, \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode=discovery_mode)
        return server

    def test_calculate_server_reference_manual(self):
        server = self._create_server(discovery_mode="manual")
        ref = server._calculate_server_reference(3)
        assert ref.address == "127.0.0.1"
        assert ref.port == 9003

    def test_calculate_server_reference_k8s(self):
        server = self._create_server(discovery_mode="k8s")
        with patch.dict(os.environ, {"GOSSIP_PORT": "9000", "K8S_NAMESPACE": "test-ns", "HUB_SERVICE_NAME": "hub-svc"}):
            ref = server._calculate_server_reference(2)
        assert "hub-2" in ref.address
        assert "hub-svc" in ref.address

    def test_forward_message_sends_to_subset_of_peers(self):
        server = self._create_server()
        for i in range(1, 6):
            server._ensure_peer_exists(i)

        msg = pb.GossipMessage(nonce=1, origin=0, forwarded_by=0)
        server._forward_message(msg)
        server._socket_handler.send_to_many.assert_called()

    def test_forward_message_updates_forwarded_by(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        msg = pb.GossipMessage(nonce=1, origin=5, forwarded_by=5)
        server._forward_message(msg)
        assert msg.forwarded_by == 0

    def test_ensure_peer_exists_creates_if_missing(self):
        server = self._create_server()
        assert server._state.get_peer(5) is None
        server._ensure_peer_exists(5)
        assert server._state.get_peer(5) is not None

    def test_ensure_peer_exists_does_not_overwrite(self):
        server = self._create_server()
        server._ensure_peer_exists(5)
        peer = server._state.get_peer(5)
        server._ensure_peer_exists(5)
        assert server._state.get_peer(5) is peer

    def test_stop_sends_leave_and_cleans_up(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        server.stop()
        server._peer_discovery_monitor.stop.assert_called()
        server._room_health_monitor.stop.assert_called()
        server._socket_handler.stop.assert_called()
        server._room_manager.cleanup.assert_called()


class TestHubServerOnGossipMessage:

    def _create_server(self, hub_index=0):
        hostname = f"hub-{hub_index}.local"
        with patch.dict(os.environ, {"HOSTNAME": hostname, "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler") as mock_sh, \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_on_gossip_message_processes_new_peer_join(self):
        server = self._create_server()
        msg = pb.GossipMessage(
            nonce=1, origin=1, forwarded_by=1,
            timestamp=time.time(),
            event_type=pb.PEER_JOIN,
            peer_join=pb.PeerJoinPayload(joining_peer=1),
        )
        sender = ServerReference("127.0.0.1", 9001)
        server._on_gossip_message(msg, sender)
        assert server._state.get_peer(1) is not None

    def test_on_gossip_message_skips_old_heartbeat(self):
        server = self._create_server()
        server._ensure_peer_exists(1)
        server._state.update_heartbeat(1, 10)
        msg = pb.GossipMessage(
            nonce=5, origin=1, forwarded_by=1,
            timestamp=time.time(),
            event_type=pb.PEER_JOIN,
            peer_join=pb.PeerJoinPayload(joining_peer=2),
        )
        sender = ServerReference("127.0.0.1", 9001)
        with patch.object(server, '_process_message') as mock_proc:
            server._on_gossip_message(msg, sender)
            mock_proc.assert_not_called()

    def test_on_gossip_message_forwards_new_messages(self):
        server = self._create_server()
        msg = pb.GossipMessage(
            nonce=1, origin=2, forwarded_by=2,
            timestamp=time.time(),
            event_type=pb.PEER_ALIVE,
            peer_alive=pb.PeerAlivePayload(alive_peer=2),
        )
        sender = ServerReference("127.0.0.1", 9002)
        with patch.object(server, '_forward_message') as mock_fwd:
            server._on_gossip_message(msg, sender)
            mock_fwd.assert_called_once()

    def test_process_message_dispatches_all_event_types(self):
        server = self._create_server()
        server._ensure_peer_exists(5)
        server._state.add_room(Room("r1", 1, RoomStatus.ACTIVE, 30001, "svc"))

        messages = [
            pb.GossipMessage(nonce=1, origin=0, forwarded_by=0, event_type=pb.PEER_JOIN,
                             peer_join=pb.PeerJoinPayload(joining_peer=5)),
            pb.GossipMessage(nonce=2, origin=0, forwarded_by=0, event_type=pb.PEER_ALIVE,
                             peer_alive=pb.PeerAlivePayload(alive_peer=5)),
            pb.GossipMessage(nonce=3, origin=0, forwarded_by=0, event_type=pb.PEER_SUSPICIOUS,
                             peer_suspicious=pb.PeerSuspiciousPayload(suspicious_peer=5)),
            pb.GossipMessage(nonce=4, origin=0, forwarded_by=0, event_type=pb.PEER_DEAD,
                             peer_dead=pb.PeerDeadPayload(dead_peer=5)),
            pb.GossipMessage(nonce=5, origin=0, forwarded_by=0, event_type=pb.ROOM_ACTIVATED,
                             room_activated=pb.RoomActivatedPayload(room_id="r2", owner_hub=1, external_port=30002)),
            pb.GossipMessage(nonce=6, origin=0, forwarded_by=0, event_type=pb.ROOM_STARTED,
                             room_started=pb.RoomStartedPayload(room_id="r1")),
            pb.GossipMessage(nonce=7, origin=0, forwarded_by=0, event_type=pb.ROOM_CLOSED,
                             room_closed=pb.RoomClosedPayload(room_id="r1")),
            pb.GossipMessage(nonce=8, origin=0, forwarded_by=0, event_type=pb.PEER_LEAVE,
                             peer_leave=pb.PeerLeavePayload(leaving_peer=5)),
        ]

        for msg in messages:
            server._process_message(msg)


class TestHubServerProperties:

    def _create_server(self):
        with patch.dict(os.environ, {"HOSTNAME": "hub-2.local", "GOSSIP_PORT": "9000"}), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="manual")
        return server

    def test_all_properties(self):
        server = self._create_server()
        assert server.hostname == "hub-2.local"
        assert server.hub_index == 2
        assert server.discovery_mode == "manual"
        assert server.fanout == 4
        assert server.last_used_nonce == 0
        assert server.room_manager is not None

    def test_get_all_peers(self):
        server = self._create_server()
        peers = server.get_all_peers()
        assert len(peers) == 1

    def test_get_all_rooms(self):
        server = self._create_server()
        server._state.add_room(Room("r1", 0, RoomStatus.ACTIVE, 10001, "svc"))
        assert len(server.get_all_rooms()) == 1


class TestHubServerDiscoveryPeers:

    def _create_server(self, discovery_mode="manual", hub_index=1):
        hostname = f"hub-{hub_index}.local"
        env = {"HOSTNAME": hostname, "GOSSIP_PORT": "9000", "EXPECTED_HUB_COUNT": "3"}
        with patch.dict(os.environ, env), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler") as mock_sh, \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode=discovery_mode)
        return server

    def test_discovery_peers_manual_mode_sends_to_random_peer(self):
        server = self._create_server(discovery_mode="manual", hub_index=1)
        server._discovery_peers()
        server._socket_handler.send.assert_called()

    def test_discovery_peers_k8s_mode(self):
        env = {"HOSTNAME": "hub-1.local", "GOSSIP_PORT": "9000", "EXPECTED_HUB_COUNT": "3",
               "K8S_NAMESPACE": "test", "HUB_SERVICE_NAME": "hub-svc"}
        with patch.dict(os.environ, env), \
             patch("bomberman.hub_server.HubServer.HubSocketHandler"), \
             patch("bomberman.hub_server.HubServer.FailureDetector"), \
             patch("bomberman.hub_server.HubServer.PeerDiscoveryMonitor"), \
             patch("bomberman.hub_server.HubServer.RoomHealthMonitor"), \
             patch("bomberman.hub_server.HubServer.create_room_manager") as mock_rm:
            mock_rm.return_value = MagicMock()
            mock_rm.return_value.external_domain = "localhost"
            server = HubServer(discovery_mode="k8s")
            server._discovery_peers()
            server._socket_handler.send.assert_called()

    def test_discovery_peers_manual_hub0_does_not_send(self):
        """Hub-0 in manual mode non invia discovery perche' e' il primo nodo."""
        server = self._create_server(discovery_mode="manual", hub_index=0)
        server._socket_handler.reset_mock()
        with patch.dict(os.environ, {"EXPECTED_HUB_COUNT": "1"}):
            server._discovery_peers()
        server._socket_handler.send.assert_not_called()