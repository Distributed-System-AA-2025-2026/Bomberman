import unittest
from unittest.mock import patch, mock_open
from bomberman.room_server.GameEngine import GameEngine, TileType, Bomb, Position, TICK_RATE, BOMB_RANGE

class TestBomb(unittest.TestCase):
    def test_bomb_initialization(self):
        """Test that bomb timer converts seconds to ticks correctly."""
        pos = Position(1, 1)
        seconds = 2
        bomb = Bomb(pos, seconds)
        
        self.assertEqual(bomb.position, pos)
        # Verify conversion logic: 2 seconds * 10 ticks/sec = 20 ticks
        self.assertEqual(bomb.timer, seconds * TICK_RATE)
        self.assertEqual(bomb.range, BOMB_RANGE)

    def test_decrease_timer(self):
        """Test that the timer decreases by 1 tick."""
        bomb = Bomb(Position(0, 0), 1)
        initial_timer = bomb.timer
        bomb.decrease_timer()
        self.assertEqual(bomb.timer, initial_timer - 1)

class TestGameEngine(unittest.TestCase):
    
    def setUp(self):
        """Runs before every test method."""
        # Define a simple 5x5 valid grid for mocking
        self.valid_level_data = (
            "#####\n"
            "#S S#\n"
            "# + #\n"
            "#S S#\n"
            "#####"
        )

    @patch("builtins.open", new_callable=mock_open, read_data="#####\n#S S#\n# + #\n#S S#\n#####")
    def test_init_successful_file_load(self, mock_file):
        """Test initializing grid from a valid file."""
        engine = GameEngine()
        
        # Check dimensions based on valid_level_data
        self.assertEqual(engine.width, 5)
        self.assertEqual(engine.height, 5)
        
        # Verify specific tiles
        self.assertEqual(engine.grid[0][0], TileType.WALL_UNBREAKABLE) # Top-left corner
        self.assertEqual(engine.grid[1][1], TileType.SPAWN_POINT)      # Spawn point
        self.assertEqual(engine.grid[2][2], TileType.WALL_BREAKABLE)   # Center breakable
        self.assertEqual(engine.grid[1][2], TileType.EMPTY)            # Space between

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_init_file_not_found_fallback(self, mock_file):
        """Test fallback to default grid when file is missing."""
        engine = GameEngine()
        
        # Default grid is 11x11
        self.assertEqual(engine.width, 11)
        self.assertEqual(engine.height, 11)
        # Check if corners are walls (default grid logic)
        self.assertEqual(engine.grid[0][0], TileType.WALL_UNBREAKABLE)

    @patch("builtins.open", new_callable=mock_open, read_data="##\n#?") # '?' is invalid
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
            self.assertEqual(grid[height-1][x], TileType.WALL_UNBREAKABLE)

        # Check Outer Walls (Left/Right)
        for y in range(height):
            self.assertEqual(grid[y][0], TileType.WALL_UNBREAKABLE)
            self.assertEqual(grid[y][width-1], TileType.WALL_UNBREAKABLE)
            
        # Check Spawn Points
        self.assertEqual(grid[1][1], TileType.SPAWN_POINT)
        self.assertEqual(grid[height-2][width-2], TileType.SPAWN_POINT)

    @patch("builtins.open", new_callable=mock_open, read_data="#####\n#S S#\n#####")
    def test_get_ascii_snapshot(self, mock_file):
        """Test that the string representation matches the grid."""
        engine = GameEngine()
        
        # At least 2 spawn points so the engine accepts it
        expected_output = "#####\n#S S#\n#####\n"
        
        self.assertEqual(engine.get_ascii_snapshot(), expected_output)
