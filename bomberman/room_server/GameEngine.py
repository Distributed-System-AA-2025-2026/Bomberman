import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple

# Constants
TICK_RATE = 10  # Ticks per second, so 1 tick = 0.1 seconds
BOMB_TIMER_SEC = 2.0  # Seconds will be translated to ticks
EXPLOSION_DURATION_SEC = 1.0  # Seconds will be translated to ticks
BOMB_RANGE = 2  # Tiles


# This is an enumeration for different tile types in the game, needed for serialization. Just static tiles (not dynamic entities like players, bombs or explosions)
class TileType(Enum):
    EMPTY = 0
    WALL_UNBREAKABLE = 1
    WALL_BREAKABLE = 2
    SPAWN_POINT = 3


TILE_PROPERTIES = {
    # Properties for each tile type
    TileType.EMPTY: {"walkable": True, "symbol": " "},
    TileType.WALL_UNBREAKABLE: {"walkable": False, "symbol": "#"},
    TileType.WALL_BREAKABLE: {"walkable": False, "symbol": "+"},
    TileType.SPAWN_POINT: {"walkable": True, "symbol": "S"},
}

# Reverse lookup for parsing levels
SYMBOL_TO_TILE = {v["symbol"]: k for k, v in TILE_PROPERTIES.items()}

@dataclass
class Position():
    """Class representing a position on the grid"""

    x: int
    y: int


class Direction(Enum):
    """Class representing a movement direction"""

    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)
    STAY = (0, 0)


@dataclass
class Player:
    """Class representing a player in the game"""

    id: str
    position: Position
    has_bomb: bool = False
    is_alive: bool = True

    class ActionType(Enum):
        """Class representing possible player actions"""

        MOVE = 0
        STAY = 1
        PLACE_BOMB = 2


@dataclass
class Bomb:
    """Class representing a bomb in the game"""

    position: Position
    timer: int  # Ticks until explosion
    range: int = BOMB_RANGE

    def __init__(self, position: Position, timer_seconds: int):
        self.position = position
        self.timer = timer_seconds * TICK_RATE  # Convert seconds to ticks

    def decrease_timer(self):
        """Decrease the bomb timer by one tick"""
        self.timer -= 1


class GameEngine:
    """
    Authoritative Server Logic.
    Manages the grid (static map) and state (dynamic entities like players, bombs, and explosions).
    """

    def __init__(self):
        self.grid, self.width, self.height = self._initialize_grid()

    def _initialize_grid(self) -> Tuple[List[List[TileType]], int, int]:
        """Helper to try loading file, catching errors, and falling back to default."""
        try:
            return self.generate_grid_from_file()
        except FileNotFoundError:
            print("Error: Level file not found. Falling back to empty default grid.")
            return self._create_default_grid()
        except ValueError as e:
            print(f"Error parsing level file: {e}. Falling back to empty default grid.")
            return self._create_default_grid()

    def _create_default_grid(self) -> Tuple[List[List[TileType]], int, int]:
        """Creates a safe default 11x11 empty grid with 4 spawn points."""
        width, height = 11, 11
        grid = [[TileType.EMPTY for _ in range(width)] for _ in range(height)]  # Create empty grid

        # Add walls around the edges
        for x in range(width):
            grid[0][x] = TileType.WALL_UNBREAKABLE
            grid[height - 1][x] = TileType.WALL_UNBREAKABLE

        # Add walls around the left and right edges
        for y in range(height):
            grid[y][0] = TileType.WALL_UNBREAKABLE
            grid[y][width - 1] = TileType.WALL_UNBREAKABLE

        # Add 4 spawn points at the corners
        spawn_positions = [(1, 1), (1, height - 2), (width - 2, 1), (width - 2, height - 2)]
        for x, y in spawn_positions:
            grid[y][x] = TileType.SPAWN_POINT

        return grid, width, height

    def generate_grid_from_file(
        self, file_path: str = "bomberman/room_server/level.txt"
    ) -> Tuple[List[List[TileType]], int, int]:
        """Generate the game grid from a predefined file"""
        grid: List[List[TileType]] = []
        with open(file_path, "r", encoding="utf-8") as file:
            for line_num, line in enumerate(file):
                row: List[TileType] = []
                # Use rstrip('\n') to keep trailing spaces (important for empty tiles)
                stripped_line = line.rstrip("\n")

                for col_num, char in enumerate(stripped_line):
                    if char in SYMBOL_TO_TILE:
                        row.append(SYMBOL_TO_TILE[char])
                    else:
                        raise ValueError(
                            f"Unknown character '{char}' in level file at line {line_num+1}, col {col_num+1}"
                        )
                grid.append(row)

        height = len(grid)
        width = len(grid[0]) if height > 0 else 0

        # Count spawn points
        spawn_count = sum(row.count(TileType.SPAWN_POINT) for row in grid)
        if spawn_count < 2:
            raise ValueError("Level must contain at least 2 spawn points.")

        return grid, width, height

    def get_ascii_snapshot(self) -> str:
        """Get ASCII representation of the game grid"""
        snapshot = ""
        for row in self.grid:
            for tile in row:
                snapshot += TILE_PROPERTIES[tile]["symbol"]
            snapshot += "\n"
        return snapshot


if __name__ == "__main__":
    engine = GameEngine()
    print(engine.get_ascii_snapshot())
