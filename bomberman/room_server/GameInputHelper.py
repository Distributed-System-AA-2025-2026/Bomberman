import sys
import os
import time

if os.name == "nt":  # Windows
    import msvcrt
else:
    import tty, termios


class _Getch:
    """Gets a single character from standard input.  Does not echo to the screen."""

    def __init__(self):
        try:
            self.impl = _GetchWindows()
        except ImportError:
            self.impl = _GetchUnix()

    def __call__(self):
        return self.impl()


# TODO: try on different OS
class _GetchUnix:
    def __call__(self):
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


class _GetchWindows:
    def __init__(self):
        import msvcrt

    def __call__(self):
        import msvcrt

        # Get the key press
        ch = msvcrt.getch()

        # Check for special keys (Arrow keys, F1-F12, etc.)
        # These keys send a prefix of 0x00 or 0xe0 first
        if ch in (b"\x00", b"\xe0"):
            msvcrt.getch()  # Read the second byte to clear the buffer
            return ""  # Return empty string to ignore this input

        # Decode normal characters
        try:
            return ch.decode("utf-8")
        except UnicodeDecodeError:
            return ""  # Safely ignore other weird inputs


class RealTimeInput:
    def __init__(self):
        self.is_windows = os.name == "nt"
        if self.is_windows:
            import msvcrt

            self.msvcrt = msvcrt
        else:
            import select
            import tty
            import termios

            self.select = select
            self.tty = tty
            self.termios = termios

    def __enter__(self):
        if not self.is_windows:
            self.old_settings = self.termios.tcgetattr(sys.stdin)
            self.tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, type, value, traceback):
        if not self.is_windows:
            self.termios.tcsetattr(sys.stdin, self.termios.TCSADRAIN, self.old_settings)

    def get_key(self, timeout=0.1):
        """Waits for key for `timeout` seconds. Returns char or None."""
        if self.is_windows:
            start_time = time.time()
            while True:
                # Check if key is available
                if self.msvcrt.kbhit():
                    ch = self.msvcrt.getch()
                    # Handle special keys (arrows send 2 bytes)
                    if ch in (b"\x00", b"\xe0"):
                        self.msvcrt.getch()  # clear second byte
                        return ""
                    try:
                        return ch.decode("utf-8").lower()
                    except UnicodeDecodeError:
                        return ""

                # Check timeout
                if time.time() - start_time > timeout:
                    return None

                # Small sleep to prevent overuse of CPU
                time.sleep(0.01)
        else:
            # Unix select approach
            rlist, _, _ = self.select.select([sys.stdin], [], [], timeout)
            if rlist:
                return sys.stdin.read(1).lower()
            return None
        
    def flush(self):
        """Clears all remaining keystrokes in the buffer."""
        if self.is_windows:
            while self.msvcrt.kbhit():
                self.msvcrt.getch()
        else:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
