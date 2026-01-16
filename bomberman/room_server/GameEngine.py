import os
import sys
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple

# Constants
TICK_RATE = 10  # Ticks per second, so 1 tick = 0.1 seconds
BOMB_TIMER_SEC = 2.0  # Seconds will be translated to ticks
EXPLOSION_DURATION_SEC = 1.0  # Seconds will be translated to ticks
BOMB_RANGE = 2  # Tiles


# This is an enumeration for different tile types in the game, needed for serialization.
class TileType(Enum):
    EMPTY = 0
    WALL_UNBREAKABLE = 1
    WALL_BREAKABLE = 2
    SPAWN_POINT = 3
    BOMB = 4


TILE_PROPERTIES = {
    # Properties for each tile type
    TileType.EMPTY: {"walkable": True, "symbol": " "},
    TileType.WALL_UNBREAKABLE: {"walkable": False, "symbol": "#"},
    TileType.WALL_BREAKABLE: {"walkable": False, "symbol": "+"},
    TileType.SPAWN_POINT: {"walkable": True, "symbol": "S"},
    TileType.BOMB: {"walkable": True, "symbol": "@"},
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

    player_id: str
    position: Position
    timer: int  # Ticks until explosion
    range: int = BOMB_RANGE

    def __init__(self, player_id: str, position: Position, timer_seconds: int):
        self.player_id = player_id
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


@dataclass
class MOVE_PLAYER(GameAction):
    """Action carrying the player ID and direction"""

    player_id: str
    direction: Direction


@dataclass
class PLACE_BOMB(GameAction):
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

    def __init__(self, seed: Optional[int] = None):
        self.grid, self.width, self.height, self.spawn_points = self._initialize_grid()
        self.players = []
        self.bombs = []
        self.current_tick = 0
        if seed is not None:
            random.seed(seed)

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
                # Start with the static tile symbol
                symbol = TILE_PROPERTIES[tile]["symbol"]

                # If tile is a spawn point, represent it as empty space for clarity
                if tile == TileType.SPAWN_POINT:
                    symbol = TILE_PROPERTIES[TileType.EMPTY]["symbol"]

                # Check for bombs at this position
                for bomb in self.bombs:
                    if bomb.position.x == x and bomb.position.y == y:
                        symbol = TILE_PROPERTIES[TileType.BOMB]["symbol"]
                        break  # Stop looking for other bombs in this cell

                # Check if a Player is present at this position
                for player in self.players:
                    if player.position.x == x and player.position.y == y and player.is_alive:
                        # Use the first letter of the Player ID
                        symbol = player.id[0]
                        break  # Stop looking for other players in this cell

                snapshot += symbol
            snapshot += "\n"

        if verbose:
            snapshot += f"Grid Size: {self.width}x{self.height}\n"
            snapshot += f"Free Spawn Points: {[(sp.x, sp.y) for sp in self.spawn_points]}\n"
            snapshot += f"Players: {[p.id for p in self.players]}\n"
            snapshot += f"Bombs: {len(self.bombs)}\n"
            snapshot += f"Current Tick: {self.current_tick} - Time elapsed: {self.current_tick / TICK_RATE:.1f}s\n"

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

    def move_player(self, player_id: str, direction: Direction, verbose: bool = True) -> None:
        """Move a player in the specified direction if possible."""

        # Find the player
        player = next((p for p in self.players if p.id == player_id), None)
        if player is None:
            raise ValueError(f"Player with ID '{player_id}' does not exist.")

        if not player.is_alive:
            if verbose:
                print(f"Player '{player_id}' is not alive and cannot move.")
            return

        # Check if direction is an instance of Direction
        if not isinstance(direction, Direction):
            raise ValueError(f"Invalid direction provided for player '{player_id}'.")

        # Calculate new position
        delta_x, delta_y = direction.value
        new_x = player.position.x + delta_x
        new_y = player.position.y + delta_y

        # Check bounds
        if new_x < 0 or new_x >= self.width or new_y < 0 or new_y >= self.height:
            if verbose:
                print(f"Player '{player_id}' cannot move out of bounds.")
            return

        # Check if the tile is walkable
        target_tile = self.grid[new_y][new_x]
        if TILE_PROPERTIES[target_tile]["walkable"]:
            # Move the player
            player.position = Position(new_x, new_y)
            if verbose:
                print(f"Player '{player_id}' moved {direction.name} to ({new_x}, {new_y}).")
        else:
            if verbose:
                print(
                    f"Player '{player_id}' cannot move to non-walkable tile at ({new_x}, {new_y})."
                )

    def place_bomb(self, player_id: str, verbose: bool = True) -> None:
        """Place a bomb at the player's current position."""

        # Find the player
        player = next((p for p in self.players if p.id == player_id), None)
        if player is None:
            raise ValueError(f"Player with ID '{player_id}' does not exist.")

        if not player.is_alive:
            if verbose:
                print(f"Player '{player_id}' is not alive and cannot place bombs.")
            return

        if player.has_bomb:
            if verbose:
                print(f"Player '{player_id}' already has an active bomb and cannot place another.")
            return

        # Create and add the bomb
        bomb_position = Position(player.position.x, player.position.y)
        new_bomb = Bomb(player_id=player_id, position=bomb_position, timer_seconds=BOMB_TIMER_SEC)
        self.bombs.append(new_bomb)

        if verbose:
            print(f"Player '{player_id}' placed a bomb at ({bomb_position.x}, {bomb_position.y}).")

    def explode_bomb(self, bomb: Bomb, verbose: bool = True) -> None:
        """Handle bomb explosion logic."""
        if verbose:
            print(f"Bomb at ({bomb.position.x}, {bomb.position.y}) exploded.")

        # Remove the bomb from the game
        self.bombs.remove(bomb)

        # Toggle player's bomb availability
        player = next((p for p in self.players if p.id == bomb.player_id), None)
        if player:
            player.has_bomb = False

        # Explosion logic
        affected_positions = [bomb.position]
        # Add positions in all four directions based on bomb range
        for direction in [Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT]:
            for r in range(1, bomb.range + 1):
                new_x = bomb.position.x + direction.value[0] * r
                new_y = bomb.position.y + direction.value[1] * r

                # Check bounds
                if new_x < 0 or new_x >= self.width or new_y < 0 or new_y >= self.height:
                    break

                target_tile = self.grid[new_y][new_x]
                if target_tile == TileType.WALL_UNBREAKABLE:
                    break  # Stop explosion in this direction
                affected_positions.append(Position(new_x, new_y))

                if target_tile == TileType.WALL_BREAKABLE:
                    # Destroy the breakable wall
                    self.grid[new_y][new_x] = TileType.EMPTY
                    break  # Stop explosion in this direction

        # Check for players in affected positions
        for pos in affected_positions:
            for player in self.players:
                if player.position.x == pos.x and player.position.y == pos.y and player.is_alive:
                    player.is_alive = False

                    if verbose:
                        print(
                            f"Player '{player.id}' was hit by the explosion at ({pos.x}, {pos.y}) and is now dead."
                        )

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

                # MOVE_PLAYER action
                if isinstance(action, MOVE_PLAYER):
                    self.move_player(action.player_id, action.direction, verbose)
                    return True

                # PLACE_BOMB action
                if isinstance(action, PLACE_BOMB):
                    self.place_bomb(action.player_id, verbose)
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

        # Update bombs
        for bomb in self.bombs[:]:  # Copy the list to avoid modification during iteration
            bomb.decrease_timer()
            if bomb.timer <= 0:
                self.explode_bomb(bomb, verbose)

        self.current_tick += 1

        return is_action_valid


if __name__ == "__main__":
    PLAY_GAME = True
    
    if not PLAY_GAME:
        engine = GameEngine(seed=42)

        engine.tick(verbose=True, action=ADD_PLAYER(player_id="Enrico"))
        engine.tick(verbose=True, action=MOVE_PLAYER(player_id="Enrico", direction=Direction.DOWN))
        engine.tick(verbose=True, action=MOVE_PLAYER(player_id="Enrico", direction=Direction.DOWN))
        engine.tick(verbose=True, action=MOVE_PLAYER(player_id="Enrico", direction=Direction.DOWN))

        print(engine.get_ascii_snapshot())
    else:
        from GameInputHelper import _Getch, RealTimeInput

        # Initialize Engine
        engine = GameEngine(seed=42)

        # Helper to clear terminal
        def clear_screen():
            os.system("cls" if os.name == "nt" else "clear")

        my_player_id = "Enrico"

        # Initial Setup
        try:
            engine.tick(verbose=False, action=ADD_PLAYER(player_id=my_player_id))
            engine.tick(verbose=False, action=ADD_PLAYER(player_id="Marzia"))
        except ValueError as e:
            print(f"Startup Error: {e}")
            sys.exit(1)

        getch = _Getch()
        message = "Controls: [W, A, S, D] to Move, [E] to Place Bomb, [Q] to Quit."

        with RealTimeInput() as input_handler:
            while True:
                # Record start time to manage tick rate
                start_time = time.time()

                clear_screen()

                # Render Game
                print(engine.get_ascii_snapshot(verbose=True))
                print(f"Status: {message}")
                print("-" * 30)

                # Get Input - Non-blocking - wait for 1/TICK_RATE seconds (frequency) then process tick, if key pressed, process it immediately

                key = input_handler.get_key(timeout=1.0 / TICK_RATE)

                action = None

                # Map Input to Actions
                if key == "w":
                    action = MOVE_PLAYER(player_id=my_player_id, direction=Direction.UP)
                    message = "Moved UP"
                elif key == "s":
                    action = MOVE_PLAYER(player_id=my_player_id, direction=Direction.DOWN)
                    message = "Moved DOWN"
                elif key == "a":
                    action = MOVE_PLAYER(player_id=my_player_id, direction=Direction.LEFT)
                    message = "Moved LEFT"
                elif key == "d":
                    action = MOVE_PLAYER(player_id=my_player_id, direction=Direction.RIGHT)
                    message = "Moved RIGHT"
                elif key == "e":
                    action = PLACE_BOMB(player_id=my_player_id)
                    message = "Placed BOMB"
                elif key == "q":
                    print("Quitting game...")
                    break
                else:
                    action = STAY()  # Logic for passing time without moving
                    message = "Waiting..."

                # Process Tick
                engine.tick(verbose=False, action=action)

                # Calculate how much time to sleep to maintain tick rate
                elapsed_time = time.time() - start_time
                sleep_time = max(0, (1.0 / TICK_RATE) - elapsed_time)
                time.sleep(sleep_time)

                # Flush any remaining inputs to prevent backlog
                input_handler.flush()
