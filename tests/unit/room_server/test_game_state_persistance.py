import unittest
import time
import pickle
from unittest.mock import patch, MagicMock, mock_open
from bomberman.room_server.GameStatePersistence import GameStatePersistence, SAVE_FILE_PATH, SERVER_RECONNECTION_TIMEOUT

class TestGameStatePersistence(unittest.TestCase):

    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.current_tick = 100

    @patch("pickle.dump")
    @patch("builtins.open", new_callable=mock_open)
    def test_save_game_state_success(self, mock_file, mock_pickle_dump):
        """Test saving state writes to file successfully."""
        result = GameStatePersistence.save_game_state(self.mock_engine)
        
        self.assertTrue(result)
        mock_file.assert_called_with(SAVE_FILE_PATH, "wb")
        mock_pickle_dump.assert_called()
        
        # Verify structure passed to pickle
        args, _ = mock_pickle_dump.call_args
        data = args[0]
        self.assertIn("timestamp", data)
        self.assertIn("engine", data)
        self.assertEqual(data["engine"], self.mock_engine)

    @patch("pickle.dump", side_effect=Exception("Disk full"))
    @patch("builtins.open", new_callable=mock_open)
    def test_save_game_state_failure(self, mock_file, mock_pickle_dump):
        """Test saving handles exceptions gracefully."""
        result = GameStatePersistence.save_game_state(self.mock_engine)
        self.assertFalse(result)

    @patch("time.time")
    @patch("pickle.load")
    @patch("builtins.open", new_callable=mock_open)
    def test_load_game_state_success(self, mock_file, mock_pickle_load, mock_time):
        """Test loading a valid, recent save file."""
        # Setup time
        mock_time.return_value = 1000.0
        
        # Setup pickle return
        saved_data = {
            "timestamp": 990.0, # 10 seconds ago (valid)
            "engine": self.mock_engine
        }
        mock_pickle_load.return_value = saved_data
        
        result = GameStatePersistence.load_game_state()
        
        self.assertIsNotNone(result)
        engine, timestamp = result
        self.assertEqual(engine, self.mock_engine)
        self.assertEqual(timestamp, 990.0)

    @patch("time.time")
    @patch("pickle.load")
    @patch("builtins.open", new_callable=mock_open)
    def test_load_game_state_timeout(self, mock_file, mock_pickle_load, mock_time):
        """Test loading a save file that is too old."""
        mock_time.return_value = 1000.0
        
        # Save is older than SERVER_RECONNECTION_TIMEOUT (30s)
        old_timestamp = 1000.0 - (SERVER_RECONNECTION_TIMEOUT + 5)
        
        saved_data = {
            "timestamp": old_timestamp,
            "engine": self.mock_engine
        }
        mock_pickle_load.return_value = saved_data
        
        result = GameStatePersistence.load_game_state()
        
        self.assertIsNone(result) # Should discard save

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_load_game_state_file_not_found(self, mock_file):
        """Test loading when file does not exist (covers FileNotFoundError block)."""
        result = GameStatePersistence.load_game_state()
        self.assertIsNone(result)

    @patch("builtins.open", side_effect=Exception("Corrupted file"))
    def test_load_game_state_generic_exception(self, mock_file):
        """Test loading when a generic exception occurs (covers Exception block)."""
        result = GameStatePersistence.load_game_state()
        self.assertIsNone(result)

    @patch("os.remove")
    @patch("os.path.exists", return_value=True)
    def test_delete_save_file_success(self, mock_exists, mock_remove):
        """Test file deletion success."""
        GameStatePersistence.delete_save_file()
        mock_remove.assert_called_with(SAVE_FILE_PATH)

    @patch("os.remove", side_effect=PermissionError("Locked"))
    @patch("os.path.exists", return_value=True)
    def test_delete_save_file_exception(self, mock_exists, mock_remove):
        """Test file deletion handling exceptions (covers Exception block)."""
        # Should catch the exception and print error, not crash
        GameStatePersistence.delete_save_file()
        mock_remove.assert_called_with(SAVE_FILE_PATH)