from unittest.mock import MagicMock, patch
import requests

from bomberman.hub_server.HubState import HubState
from bomberman.hub_server.Room import Room
from bomberman.hub_server.RoomHealthMonitor import RoomHealthMonitor
from bomberman.common.RoomState import RoomStatus


class TestRoomHealthMonitorIsRoomHealthy:

    def _make_room(self, room_id="room-1", status=RoomStatus.ACTIVE, internal_service="room-svc.local"):
        return Room(
            room_id=room_id,
            owner_hub_index=0,
            status=status,
            external_port=10001,
            internal_service=internal_service,
        )

    def _make_monitor(self):
        state = HubState()
        callback = MagicMock()
        monitor = RoomHealthMonitor(state, my_index=0, on_room_unhealthy=callback)
        return monitor, state, callback

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_healthy_room_returns_true(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "WAITING_FOR_PLAYERS"})
        assert monitor._is_room_healthy(self._make_room()) is True

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_with_wrong_status_returns_false(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "IN_GAME"})
        assert monitor._is_room_healthy(self._make_room()) is False

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_returning_500_is_unhealthy(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.return_value = MagicMock(status_code=500)
        assert monitor._is_room_healthy(self._make_room()) is False

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_timeout_is_unhealthy(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.side_effect = requests.exceptions.Timeout()
        assert monitor._is_room_healthy(self._make_room()) is False

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_connection_refused_is_unhealthy(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.side_effect = requests.exceptions.ConnectionError()
        assert monitor._is_room_healthy(self._make_room()) is False

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_generic_exception_is_unhealthy(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.side_effect = Exception("unexpected")
        assert monitor._is_room_healthy(self._make_room()) is False

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_room_with_missing_status_field_is_unhealthy(self, mock_get):
        monitor, _, _ = self._make_monitor()
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"other": "data"})
        assert monitor._is_room_healthy(self._make_room()) is False


class TestRoomHealthMonitorCheckAllRooms:

    def _make_room(self, room_id, status=RoomStatus.ACTIVE, internal_service="room-svc.local"):
        return Room(
            room_id=room_id,
            owner_hub_index=0,
            status=status,
            external_port=10001,
            internal_service=internal_service,
        )

    def _make_monitor(self):
        state = HubState()
        callback = MagicMock()
        monitor = RoomHealthMonitor(state, my_index=0, on_room_unhealthy=callback)
        return monitor, state, callback

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_only_active_rooms_are_checked(self, mock_get):
        monitor, state, callback = self._make_monitor()
        state.add_room(self._make_room("active-room", RoomStatus.ACTIVE))
        state.add_room(self._make_room("playing-room", RoomStatus.PLAYING))
        state.add_room(self._make_room("dormant-room", RoomStatus.DORMANT))

        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "WAITING_FOR_PLAYERS"})
        monitor._running = True
        monitor._check_all_rooms()

        assert mock_get.call_count == 1

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_rooms_without_internal_service_are_skipped(self, mock_get):
        monitor, state, callback = self._make_monitor()
        state.add_room(self._make_room("remote-room", RoomStatus.ACTIVE, internal_service=""))

        monitor._running = True
        monitor._check_all_rooms()

        mock_get.assert_not_called()

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_unhealthy_room_triggers_callback(self, mock_get):
        monitor, state, callback = self._make_monitor()
        room = self._make_room("bad-room", RoomStatus.ACTIVE)
        state.add_room(room)

        mock_get.side_effect = requests.exceptions.ConnectionError()
        monitor._running = True
        monitor._check_all_rooms()

        callback.assert_called_once_with(room)

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_healthy_room_does_not_trigger_callback(self, mock_get):
        monitor, state, callback = self._make_monitor()
        state.add_room(self._make_room("good-room", RoomStatus.ACTIVE))

        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "WAITING_FOR_PLAYERS"})
        monitor._running = True
        monitor._check_all_rooms()

        callback.assert_not_called()

    def test_start_is_idempotent(self):
        monitor, _, _ = self._make_monitor()
        monitor.start()
        thread1 = monitor._thread
        monitor.start()
        thread2 = monitor._thread
        assert thread1 is thread2
        monitor.stop()

    def test_stop_without_start_is_safe(self):
        monitor, _, _ = self._make_monitor()
        monitor.stop()

    @patch("bomberman.hub_server.RoomHealthMonitor.requests.get")
    def test_check_all_rooms_respects_running_flag(self, mock_get):
        monitor, state, callback = self._make_monitor()
        state.add_room(self._make_room("room-1", RoomStatus.ACTIVE))
        state.add_room(self._make_room("room-2", RoomStatus.ACTIVE))

        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "WAITING_FOR_PLAYERS"})
        monitor._running = False
        monitor._check_all_rooms()

    def test_monitor_loop_handles_exception_in_check(self):
        monitor, state, callback = self._make_monitor()
        monitor._running = True
        monitor.CHECK_INTERVAL = 0

        call_count = 0

        def failing_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("test error")
            monitor._running = False

        monitor._check_all_rooms = failing_check
        monitor._monitor_loop()
        assert call_count >= 1