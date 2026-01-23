import time
import pickle
from typing import Optional, Tuple
import bomberman.room_server.GameEngine as GameEngine

# Constants
SERVER_RECONNECTION_TIMEOUT = 30  # Seconds to wait for reconnection
SAVE_FILE_PATH = "bomberman_save.pkl"
AUTOSAVE_INTERVAL = 5  # Save every 5 ticks


class GameStatePersistence:
    """Handles saving and loading game state to/from disk."""

    @staticmethod
    def save_game_state(engine: GameEngine.GameEngine, filepath: str = SAVE_FILE_PATH) -> bool:
        """Saves the game state including a timestamp. Returns True on success, False otherwise."""

        try:
            data = {
                "timestamp": time.time(),
                "engine": engine,
            }

            # Save game
            with open(filepath, "wb") as f:
                pickle.dump(data, f)

            return True

        except Exception as e:
            print(f"[ERROR] Failed to save game state: {e}")
            return False

    @staticmethod
    def load_game_state(
        filepath: str = SAVE_FILE_PATH,
    ) -> Optional[Tuple[GameEngine.GameEngine, float]]:
        """Loads game state from a file. Returns (GameEngine, timestamp) if successful, None otherwise."""
        try:
            # Load file
            with open(filepath, "rb") as f:
                state_data = pickle.load(f)

            timestamp = state_data["timestamp"]
            engine = state_data["engine"]

            # Check timestamp validity
            current_time = time.time()
            time_since_save = current_time - timestamp

            # Check if save is too old
            if time_since_save > SERVER_RECONNECTION_TIMEOUT:
                print(
                    f"[*] Save file is {time_since_save:.1f}s old (>{SERVER_RECONNECTION_TIMEOUT}s). Starting fresh game."
                )
                return None

            print(f"[*] Game state loaded successfully (saved {time_since_save:.1f}s ago)")

            return (engine, timestamp)

        except FileNotFoundError:
            print("[*] No save file found. Starting fresh game.")
            return None
        except Exception as e:
            print(f"[ERROR] Failed to load game state: {e}")
            return None

    @staticmethod
    def delete_save_file(filepath: str = SAVE_FILE_PATH):
        """Deletes the save file if it exists."""

        try:
            import os

            if os.path.exists(filepath):
                os.remove(filepath)
                print("[*] Save file deleted.")
        except Exception as e:
            print(f"[ERROR] Failed to delete save file: {e}")
