import unittest
from unittest.mock import patch, mock_open
from bomberman.room_server.GameEngine import (
    GameEngine,
    TileType,
    TICK_RATE,
    BOMB_RANGE,
    Bomb,
    Position,
    Player,
    Direction,
    ADD_PLAYER,
    MOVE_PLAYER,
    PLACE_BOMB,
)


class TestBomb(unittest.TestCase):
    def test_bomb_initialization(self):
        """Test that bomb timer converts seconds to ticks correctly."""
        pos = Position(1, 1)
        seconds = 2
        bomb = Bomb("Enrico", pos, seconds)

        self.assertEqual(bomb.position, pos)
        # Verify conversion logic: 2 seconds * 10 ticks/sec = 20 ticks
        self.assertEqual(bomb.timer, seconds * TICK_RATE)
        self.assertEqual(bomb.range, BOMB_RANGE)

    def test_decrease_timer(self):
        """Test that the timer decreases by 1 tick."""
        bomb = Bomb("Enrico", Position(0, 0), 1)
        initial_timer = bomb.timer
        bomb.decrease_timer()
        self.assertEqual(bomb.timer, initial_timer - 1)


class TestGameEngine(unittest.TestCase):

    def setUp(self):
        """Runs before every test method."""
        # Define a simple 5x5 valid grid for mocking
        self.valid_level_data = "#####\n" "#S S#\n" "# + #\n" "#S S#\n" "#####"

    @patch("builtins.open", new_callable=mock_open, read_data="#####\n#S S#\n# + #\n#S S#\n#####")
    def test_init_successful_file_load(self, mock_file):
        """Test initializing grid from a valid file."""
        engine = GameEngine()

        # Check dimensions based on valid_level_data
        self.assertEqual(engine.width, 5)
        self.assertEqual(engine.height, 5)

        # Verify specific tiles
        self.assertEqual(engine.grid[0][0], TileType.WALL_UNBREAKABLE)  # Top-left corner
        self.assertEqual(engine.grid[1][1], TileType.SPAWN_POINT)  # Spawn point
        self.assertEqual(engine.grid[2][2], TileType.WALL_BREAKABLE)  # Center breakable
        self.assertEqual(engine.grid[1][2], TileType.EMPTY)  # Space between

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_init_file_not_found_fallback(self, mock_file):
        """Test fallback to default grid when file is missing."""
        engine = GameEngine()

        # Default grid is 11x11
        self.assertEqual(engine.width, 11)
        self.assertEqual(engine.height, 11)
        # Check if corners are walls (default grid logic)
        self.assertEqual(engine.grid[0][0], TileType.WALL_UNBREAKABLE)

    @patch("builtins.open", new_callable=mock_open, read_data="##\n#?")  # '?' is invalid
    def test_init_invalid_char_fallback(self, mock_file):
        """Test fallback to default grid when file contains invalid characters."""
        engine = GameEngine()

        # Fallback successful (11x11 grid)
        self.assertEqual(engine.width, 11)

        # The default grid places a SPAWN_POINT at (1,1)
        self.assertEqual(engine.grid[1][1], TileType.SPAWN_POINT)

    @patch("builtins.open", new_callable=mock_open, read_data="###\n#S#\n###")
    def test_init_insufficient_spawns_fallback(self, mock_file):
        """Test fallback when file has fewer than 2 spawn points."""
        # The mock data only has 1 'S'
        engine = GameEngine()

        # Should fallback to default 11x11
        self.assertEqual(engine.width, 11)
        # Ensure default grid has 4 spawns
        spawn_count = sum(row.count(TileType.SPAWN_POINT) for row in engine.grid)
        self.assertEqual(spawn_count, 4)

    def test_create_default_grid_structure(self):
        """Explicitly test the internal _create_default_grid logic."""
        # Force the engine to use the default grid by mocking file failure
        with patch("builtins.open", side_effect=FileNotFoundError):
            engine = GameEngine()

        grid = engine.grid
        height = engine.height
        width = engine.width

        # Check dimensions
        self.assertEqual(width, 11)
        self.assertEqual(height, 11)

        # Check Outer Walls (Top/Bottom)
        for x in range(width):
            self.assertEqual(grid[0][x], TileType.WALL_UNBREAKABLE)
            self.assertEqual(grid[height - 1][x], TileType.WALL_UNBREAKABLE)

        # Check Outer Walls (Left/Right)
        for y in range(height):
            self.assertEqual(grid[y][0], TileType.WALL_UNBREAKABLE)
            self.assertEqual(grid[y][width - 1], TileType.WALL_UNBREAKABLE)

        # Check Spawn Points
        self.assertEqual(grid[1][1], TileType.SPAWN_POINT)
        self.assertEqual(grid[height - 2][width - 2], TileType.SPAWN_POINT)

    @patch("builtins.open", new_callable=mock_open, read_data="#####\n#S S#\n#####")
    def test_get_ascii_snapshot(self, mock_file):
        """Test that the string representation matches the grid."""
        engine = GameEngine()

        # At least 2 spawn points so the engine accepts it
        expected_output = "#####\n#S S#\n#####\n"

        self.assertEqual(engine.get_ascii_snapshot(), expected_output)

class TestPlayerActions(unittest.TestCase):
    """Tests for adding, removing, and moving players."""

    def setUp(self):
        # Force a default grid (11x11, 4 spawns) to ensure consistent environment
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.engine = GameEngine()

    def test_add_player_success(self):
        """Test adding a player to a valid spawn point."""
        player = self.engine.add_player("Enrico")
        self.assertEqual(len(self.engine.players), 1)
        self.assertEqual(player.id, "Enrico")
        # Default grid spawns are at (1,1), (1,9), (9,1), (9,9)
        self.assertTrue(player.position in [(1, 1), (1, 9), (9, 1), (9, 9)])

    def test_add_duplicate_player_fails(self):
        """Test that adding a player with an existing ID raises an error."""
        self.engine.add_player("Enrico")
        with self.assertRaises(ValueError):
            self.engine.add_player("Enrico")

    def test_add_player_no_spawns_left(self):
        """Test that adding a 5th player to a 4-spawn map fails."""
        self.engine.add_player("P1")
        self.engine.add_player("P2")
        self.engine.add_player("P3")
        self.engine.add_player("P4")

        with self.assertRaisesRegex(ValueError, "No available spawn points"):
            self.engine.add_player("P5")

    def test_remove_player(self):
        """Test removing a player frees up the spawn point."""
        p1 = self.engine.add_player("Enrico")
        initial_spawn_count = len(self.engine.spawn_points)

        self.engine.remove_player("Enrico")

        self.assertEqual(len(self.engine.players), 0)
        self.assertEqual(len(self.engine.spawn_points), initial_spawn_count + 1)
        self.assertIn(p1.position, self.engine.spawn_points)

    def test_movement_valid(self):
        """Test moving into an empty space."""
        # Setup: Grid with Player at (1,1). (1,2) is empty in default grid.
        player = self.engine.add_player("Enrico")
        # Force position to (1,1) to be sure
        player.position.x, player.position.y = 1, 1

        self.engine.move_player("Enrico", Direction.DOWN)

        self.assertEqual(player.position.x, 1)
        self.assertEqual(player.position.y, 2)

    def test_movement_collision_wall(self):
        """Test that moving into a wall does not change position."""
        player = self.engine.add_player("Enrico")
        # Force position to (1,1). (0,1) is a wall.
        player.position.x, player.position.y = 1, 1

        self.engine.move_player("Enrico", Direction.LEFT)

        # Position should remain (1,1)
        self.assertEqual(player.position.x, 1)
        self.assertEqual(player.position.y, 1)

    def test_movement_dead_player(self):
        """Test that a dead player cannot move."""
        player = self.engine.add_player("Enrico")
        player.is_alive = False

        self.engine.move_player("Enrico", Direction.DOWN)

        original_pos = (player.position.x, player.position.y)
        self.engine.move_player("Enrico", Direction.DOWN)
        self.assertEqual((player.position.x, player.position.y), original_pos)


class TestCombatLogic(unittest.TestCase):
    """Tests for Bomb placement and Explosion mechanics."""

    def setUp(self):
        """
        Create a custom small map for precise combat testing.
        Map Layout:
        #####
        #S+ #  <- (1,1) Spawn, (2,1) Breakable Wall, (3,1) Empty
        #   #
        #####
        """
        custom_map = "#####\n#S+ #\n#   #\n#####"
        with patch("builtins.open", new_callable=mock_open, read_data=custom_map):
            self.engine = GameEngine()

        self.player = self.engine.add_player("Bomber")
        # Force player to (1,1)
        self.player.position.x, self.player.position.y = 1, 1

    def test_place_bomb_success(self):
        """Test placing a bomb."""
        self.engine.place_bomb("Bomber")

        self.assertEqual(len(self.engine.bombs), 1)
        self.assertTrue(self.player.has_bomb)
        self.assertEqual(self.engine.bombs[0].position.x, 1)
        self.assertEqual(self.engine.bombs[0].position.y, 1)

    def test_place_bomb_cooldown(self):
        """Test that a player cannot place a second bomb while one is active."""
        self.engine.place_bomb("Bomber")
        self.engine.place_bomb("Bomber")  # Attempt second

        self.assertEqual(len(self.engine.bombs), 1)  # Still 1

    def test_bomb_tick_and_explode(self):
        """Test that bomb timer decreases and explodes, removing itself."""
        self.engine.place_bomb("Bomber")
        bomb = self.engine.bombs[0]

        # Simulate time passing until 1 tick remains
        bomb.timer = 1

        # Process tick
        self.engine.tick()

        # Bomb should be gone
        self.assertEqual(len(self.engine.bombs), 0)
        # Player should be allowed to place bomb again
        self.assertFalse(self.player.has_bomb)

    def test_explosion_destroys_breakable_wall(self):
        """Test that an explosion destroys a '+' wall."""
        # Map: #S+ #. Player at (1,1). Wall at (2,1).
        self.assertEqual(self.engine.grid[1][2], TileType.WALL_BREAKABLE)

        self.engine.place_bomb("Bomber")
        bomb = self.engine.bombs[0]

        # Force Explosion
        self.engine.explode_bomb(bomb)

        # Wall at (2,1) should now be Empty
        self.assertEqual(self.engine.grid[1][2], TileType.EMPTY)

    def test_explosion_kills_player(self):
        """Test that an explosion kills a player in range."""
        # Add a victim player at (1,2)
        victim = self.engine.add_player("Victim")
        victim.position.x, victim.position.y = 1, 2

        # Attacker places bomb at (1,1)
        self.engine.place_bomb("Bomber")
        bomb = self.engine.bombs[0]

        # Force Explosion
        self.engine.explode_bomb(bomb)

        self.assertFalse(victim.is_alive)
        # Attacker standing on bomb should also die
        self.assertFalse(self.player.is_alive)

    def test_explosion_blocked_by_unbreakable(self):
        """Test that explosion does not penetrate unbreakable walls."""
        # Custom map: #S# #
        custom_map = "#####\n#S# #\n#####"
        with patch("builtins.open", new_callable=mock_open, read_data=custom_map):
            engine = GameEngine()

        p1 = engine.add_player("P1")
        p1.position.x, p1.position.y = 1, 1

        # Add victim behind the wall at (3,1)
        # (1,1) is bomb, (2,1) is Wall, (3,1) is victim
        victim = Player("Victim", position=Position(3, 1))
        victim.position = Position(3, 1)
        victim.is_alive = True
        engine.players.append(victim)

        engine.place_bomb("P1")
        engine.explode_bomb(engine.bombs[0])

        # Victim should be alive because the wall blocked it
        self.assertTrue(victim.is_alive)


class TestGameLoop(unittest.TestCase):
    """Test the tick processor and action handling."""

    def setUp(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.engine = GameEngine()
            self.engine.add_player("Enrico")

    def test_process_action_wrapper(self):
        """Test that tick() correctly processes a GameAction object."""
        # Player at (1,1)
        action = MOVE_PLAYER(player_id="Enrico", direction=Direction.DOWN)

        self.engine.tick(action=action)

        # Should have moved to (1,2)
        p = self.engine.players[0]
        self.assertEqual(p.position.y, 2)

    def test_tick_increments_counter(self):
        self.assertEqual(self.engine.current_tick, 0)
        self.engine.tick()
        self.assertEqual(self.engine.current_tick, 1)
