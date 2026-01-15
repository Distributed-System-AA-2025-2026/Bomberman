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
class Position:
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

class GameAction:
    """Namespace for game actions"""
    pass

@dataclass
class STAY(GameAction):
    """Empty action"""
    pass

@dataclass
class ADD_PLAYER(GameAction):
    """Action carrying the player ID"""
    player_id: str

@dataclass
class REMOVE_PLAYER(GameAction):
    """Action carrying the player ID"""
    player_id: str

class GameEngine:
    """
    Authoritative Server Logic.
    Manages the grid (static map) and state (dynamic entities like players, bombs, and explosions).
    """

    players: List[Player] = field(default_factory=list)
    bombs: List[Bomb] = field(default_factory=list)
    spawn_points: List[Position] = field(default_factory=list)
    current_tick: int

    def __init__(self):
        self.grid, self.width, self.height, self.spawn_points = self._initialize_grid()
        self.players = []
        self.bombs = []
        self.current_tick = 0

    def _initialize_grid(self) -> Tuple[List[List[TileType]], int, int, List[Position]]:
        """Helper to try loading file, catching errors, and falling back to default."""
        try:
            return self.generate_grid_from_file()
        except FileNotFoundError:
            print("Error: Level file not found. Falling back to empty default grid.")
            return self._create_default_grid()
        except ValueError as e:
            print(f"Error parsing level file: {e}. Falling back to empty default grid.")
            return self._create_default_grid()

    def _create_default_grid(self) -> Tuple[List[List[TileType]], int, int, List[Position]]:
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

        spawn_points = [Position(x, y) for x, y in spawn_positions]

        return grid, width, height, spawn_points

    def generate_grid_from_file(
        self, file_path: str = "bomberman/room_server/level.txt"
    ) -> Tuple[List[List[TileType]], int, int, List[Position]]:
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

        spawn_points = []
        for y, row in enumerate(grid):
            for x, tile in enumerate(row):
                if tile == TileType.SPAWN_POINT:
                    spawn_points.append(Position(x, y))

        return grid, width, height, spawn_points

    def get_ascii_snapshot(self, verbose: bool = True) -> str:
        """Get ASCII representation of the game grid with players overlaid."""
        snapshot = ""

        # Iterate using indices to know exactly where we are
        for y, row in enumerate(self.grid):
            for x, tile in enumerate(row):
                # 1. Start with the static tile symbol
                symbol = TILE_PROPERTIES[tile]["symbol"]

                # 2. Check if a Player is here (Visual priority over bomb and tile)
                for player in self.players:
                    if player.position.x == x and player.position.y == y and player.is_alive:
                        # Use the first letter of the Player ID
                        symbol = player.id[0]
                        break  # Stop looking for other players in this cell

                snapshot += symbol
            snapshot += "\n"

        if verbose:
            snapshot += f"Grid Size: {self.width}x{self.height}\n"
            snapshot += f"Spawn Points: {[(sp.x, sp.y) for sp in self.spawn_points]}\n"
            snapshot += f"Players: {[p.id for p in self.players]}\n"
            snapshot += f"Bombs: {len(self.bombs)}\n"

        return snapshot

    def add_player(self, player_id: str, verbose: bool = True) -> Player:
        """Add a new player to the game at the specified position"""

        if any(p.id == player_id for p in self.players):
            raise ValueError(f"Player with ID '{player_id}' already exists.")

        if not self.spawn_points:
            raise ValueError("No available spawn points to add a new player.")

        # Randomly select a spawn point from available ones
        spawn_position = random.choice(self.spawn_points)

        # Create and add the new player
        new_player = Player(id=player_id, position=spawn_position)
        self.players.append(new_player)

        # Remove the used spawn point from available ones
        self.spawn_points.remove(spawn_position)

        if verbose:
            print(
                f"Player '{player_id}' added at position ({spawn_position.x}, {spawn_position.y})"
            )

        return new_player

    def remove_player(self, player_id: str, verbose: bool = True) -> None:
        """Remove a player from the game by ID and free up their spawn point."""

        # Check if player is in the game
        player_to_remove = next((p for p in self.players if p.id == player_id), None)
        if player_to_remove is None:
            raise ValueError(f"Player with ID '{player_id}' does not exist.")
        
        # Free up the spawn point
        self.spawn_points.append(player_to_remove.position)

        # Remove the player from the game
        self.players.remove(player_to_remove)

        # Log the removal
        if verbose:
            print(f"Player '{player_id}' removed from the game.")


    def process_action(self, action: object, verbose: bool = False) -> bool:
        """Process a game action and validate it."""

        try:
            # Check if GameAction type
            if isinstance(action, GameAction):

                # STAY action
                if isinstance(action, STAY):
                    return True

                # ADD_PLAYER action
                if isinstance(action, ADD_PLAYER):
                    self.add_player(action.player_id, verbose)
                    return True
                
                # REMOVE_PLAYER action
                if isinstance(action, REMOVE_PLAYER):
                    self.remove_player(action.player_id, verbose)
                    return True
                
            return False  # Invalid action type
    
        except Exception as e:  
            if verbose:
                print(f"Invalid action: {e}")
            return False

    def tick(self, verbose: bool = False, action: Optional[GameAction] = None) -> bool:
        """Advance the game state by one tick."""

        is_action_valid = True

        if action is not None:
            is_action_valid = self.process_action(action, verbose)

        self.current_tick += 1

        return is_action_valid


if __name__ == "__main__":
    engine = GameEngine()

    engine.tick(verbose=True, action=ADD_PLAYER(player_id="Enrico"))
    engine.tick(verbose=True, action=ADD_PLAYER(player_id="Alice"))
    engine.tick(verbose=True, action=REMOVE_PLAYER(player_id="Enrico"))
    engine.tick(verbose=True, action=REMOVE_PLAYER(player_id="Enrico"))

    print(engine.get_ascii_snapshot())
