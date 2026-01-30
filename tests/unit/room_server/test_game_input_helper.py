import unittest
import sys
import os
import time
from unittest.mock import patch, MagicMock, mock_open

# Ensure target modules exist in sys.modules so imports don't fail during testing
sys.modules["msvcrt"] = MagicMock()
sys.modules["termios"] = MagicMock()
sys.modules["tty"] = MagicMock()

# Import the module to be tested
from bomberman.room_server import GameInputHelper

# Inject mocks into the module namespace if they weren't imported due to OS checks
if not hasattr(GameInputHelper, "termios"):
    GameInputHelper.termios = MagicMock()
if not hasattr(GameInputHelper, "tty"):
    GameInputHelper.tty = MagicMock()
if not hasattr(GameInputHelper, "msvcrt"):
    GameInputHelper.msvcrt = MagicMock()

class TestGetch(unittest.TestCase):
    def setUp(self):
        self.mock_msvcrt = MagicMock()
        self.mock_termios = MagicMock()
        self.mock_tty = MagicMock()
        
        # Reset module level mocks
        GameInputHelper.msvcrt = self.mock_msvcrt
        GameInputHelper.termios = self.mock_termios
        GameInputHelper.tty = self.mock_tty

    @patch("bomberman.room_server.GameInputHelper._GetchWindows")
    def test_init_favors_windows(self, mock_win):
        """Test that _Getch tries Windows implementation first."""
        # Make _GetchWindows succeed
        mock_win.return_value = MagicMock()
        
        getter = GameInputHelper._Getch()
        getter()
        
        mock_win.assert_called()

    @patch("bomberman.room_server.GameInputHelper._GetchWindows")
    @patch("bomberman.room_server.GameInputHelper._GetchUnix")
    def test_init_fallbacks_unix(self, mock_unix, mock_win):
        """Test that _Getch falls back to Unix if Windows import fails."""
        # Simulate ImportError in _GetchWindows
        mock_win.side_effect = ImportError("No msvcrt")
        
        getter = GameInputHelper._Getch()
        getter()
        
        mock_unix.assert_called()

    def test_getch_windows_normal(self):
        """Test Windows getch with normal character."""
        # Patch local import inside __call__
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            self.mock_msvcrt.getch.side_effect = [b"x"]
            
            gw = GameInputHelper._GetchWindows()
            result = gw()
            
            self.assertEqual(result, "x")

    def test_getch_windows_special_key(self):
        """Test Windows getch ignoring special keys (0x00/0xe0)."""
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            # First returns prefix, then code (should consume both and return empty)
            self.mock_msvcrt.getch.side_effect = [b"\xe0", b"H"]
            
            gw = GameInputHelper._GetchWindows()
            result = gw()
            
            self.assertEqual(result, "")
            self.assertEqual(self.mock_msvcrt.getch.call_count, 2)

    def test_getch_windows_decode_error(self):
        """Test Windows getch handling non-utf8 input."""
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            self.mock_msvcrt.getch.return_value = b"\xff"
            
            gw = GameInputHelper._GetchWindows()
            result = gw()
            
            self.assertEqual(result, "")

    def test_getch_unix(self):
        """Test Unix getch reading from stdin."""
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 1
        mock_stdin.read.return_value = "u"
        
        # Ensure module uses mocks
        GameInputHelper.sys.stdin = mock_stdin
        
        gu = GameInputHelper._GetchUnix()
        result = gu()
        
        self.assertEqual(result, "u")
        GameInputHelper.termios.tcgetattr.assert_called_with(1)
        GameInputHelper.tty.setraw.assert_called_with(1)
        GameInputHelper.termios.tcsetattr.assert_called()


class TestRealTimeInput(unittest.TestCase):
    
    def setUp(self):
        self.mock_msvcrt = MagicMock()
        self.mock_termios = MagicMock()
        self.mock_tty = MagicMock()
        self.mock_select = MagicMock()

    @patch("os.name", "nt")
    def test_init_windows(self):
        """Test initialization on Windows."""
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            self.assertTrue(rti.is_windows)
            self.assertIsNotNone(rti.msvcrt)

    @patch("os.name", "posix")
    def test_init_unix(self):
        """Test initialization on Unix."""
        with patch.dict(sys.modules, {
            "select": self.mock_select,
            "tty": self.mock_tty,
            "termios": self.mock_termios
        }):
            rti = GameInputHelper.RealTimeInput()
            self.assertFalse(rti.is_windows)
            self.assertIsNotNone(rti.select)

    @patch("os.name", "nt")
    def test_context_manager_windows(self):
        """Test Windows context manager (does nothing)."""
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            with GameInputHelper.RealTimeInput():
                pass

    @patch("os.name", "posix")
    def test_context_manager_unix(self):
        """Test Unix context manager sets/restores terminal settings."""
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 1
        
        with patch.dict(sys.modules, {
            "select": self.mock_select,
            "tty": self.mock_tty,
            "termios": self.mock_termios
        }), patch("sys.stdin", mock_stdin):
            
            with GameInputHelper.RealTimeInput():
                self.mock_termios.tcgetattr.assert_called()
                self.mock_tty.setcbreak.assert_called_with(1)
            
            self.mock_termios.tcsetattr.assert_called()

    @patch("os.name", "nt")
    def test_get_key_windows_hit(self):
        """Test Windows get_key when key is available."""
        self.mock_msvcrt.kbhit.return_value = True
        self.mock_msvcrt.getch.return_value = b"W"
        
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            key = rti.get_key()
            self.assertEqual(key, "w") # lower case

    @patch("os.name", "nt")
    def test_get_key_windows_timeout(self):
        """Test Windows get_key timeout."""
        self.mock_msvcrt.kbhit.return_value = False
        
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            start = time.time()
            key = rti.get_key(timeout=0.02)
            self.assertIsNone(key)
            self.assertGreaterEqual(time.time() - start, 0.02)

    @patch("os.name", "nt")
    def test_get_key_windows_special(self):
        """Test Windows get_key special char."""
        self.mock_msvcrt.kbhit.return_value = True
        self.mock_msvcrt.getch.side_effect = [b"\xe0", b"x"]
        
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            key = rti.get_key()
            self.assertEqual(key, "")

    @patch("os.name", "nt")
    def test_get_key_windows_decode_error(self):
        """Test Windows get_key decode error."""
        self.mock_msvcrt.kbhit.return_value = True
        self.mock_msvcrt.getch.return_value = b"\xff"
        
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            key = rti.get_key()
            self.assertEqual(key, "")

    @patch("os.name", "posix")
    def test_get_key_unix_hit(self):
        """Test Unix get_key when data ready."""
        # select returns (rlist, wlist, xlist)
        self.mock_select.select.return_value = ([sys.stdin], [], [])
        
        mock_stdin = MagicMock()
        mock_stdin.read.return_value = "A"
        
        with patch.dict(sys.modules, {
            "select": self.mock_select,
            "tty": self.mock_tty,
            "termios": self.mock_termios
        }), patch("sys.stdin", mock_stdin):
            
            rti = GameInputHelper.RealTimeInput()
            key = rti.get_key()
            self.assertEqual(key, "a")

    @patch("os.name", "posix")
    def test_get_key_unix_timeout(self):
        """Test Unix get_key timeout."""
        self.mock_select.select.return_value = ([], [], [])
        
        with patch.dict(sys.modules, {
            "select": self.mock_select,
            "tty": self.mock_tty,
            "termios": self.mock_termios
        }):
            rti = GameInputHelper.RealTimeInput()
            key = rti.get_key()
            self.assertIsNone(key)

    @patch("os.name", "nt")
    def test_flush_windows(self):
        """Test Windows flush clears buffer."""
        # kbhit true twice, then false
        self.mock_msvcrt.kbhit.side_effect = [True, True, False]
        
        with patch.dict(sys.modules, {"msvcrt": self.mock_msvcrt}):
            rti = GameInputHelper.RealTimeInput()
            rti.flush()
            self.assertEqual(self.mock_msvcrt.getch.call_count, 2)

    @patch("os.name", "posix")
    def test_flush_unix(self):
        """Test Unix flush."""
        with patch.dict(sys.modules, {
            "select": self.mock_select,
            "tty": self.mock_tty,
            "termios": self.mock_termios
        }):
            rti = GameInputHelper.RealTimeInput()
            rti.flush()
            self.mock_termios.tcflush.assert_called()