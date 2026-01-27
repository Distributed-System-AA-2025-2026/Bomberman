import unittest
import sys
from unittest.mock import patch, mock_open
import runpy
from bomberman.room_server.GameEngine import (
    GameEngine,
    GameState,
    TileType,
    Player,
    Direction,
    MOVE_PLAYER,
    PLACE_BOMB,
    STAY,
    MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE,
)


class TestGameEngineDetailed(unittest.TestCase):
    def setUp(self):
        # Default behavior: File not found -> loads default grid (11x11, 4 spawns)
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.engine = GameEngine()

    # Initialization Tests
    def test_init_grid_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            engine = GameEngine()
            self.assertEqual(engine.width, 11)
            self.assertEqual(engine.height, 11)

    def test_init_grid_value_error(self):
        invalid_level = "InvalidContent"
        with patch("builtins.open", mock_open(read_data=invalid_level)):
            engine = GameEngine()
            self.assertEqual(engine.width, 11)

    def test_init_grid_success(self):
        valid_level = "#####\n#S S#\n#####"
        with patch("builtins.open", mock_open(read_data=valid_level)):
            engine = GameEngine()
            self.assertEqual(engine.width, 5)
            self.assertEqual(engine.height, 3)
            self.assertEqual(len(engine.free_spawn_points), 2)

    def test_init_grid_insufficient_spawns(self):
        invalid_level = "#####\n#S  #\n#####"
        with patch("builtins.open", mock_open(read_data=invalid_level)):
            engine = GameEngine()
            self.assertEqual(engine.width, 11)

    # Add Player Tests
    def test_add_player_validation_empty_id(self):
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            self.engine.add_player("")

    def test_add_player_validation_duplicate_initial(self):
        self.engine.add_player("Alpha")
        with self.assertRaisesRegex(ValueError, "initial 'A' is already in use"):
            self.engine.add_player("Andy")

    def test_add_player_wrong_state(self):
        self.engine.state = GameState.IN_PROGRESS
        with self.assertRaisesRegex(ValueError, "not in WAITING_FOR_PLAYERS"):
            self.engine.add_player("Beta")

    def test_add_player_no_spawn_points(self):
        # Consume all 4 spawn points of the default grid with unique initials
        self.engine.add_player("P1")
        self.engine.add_player("Q2")
        self.engine.add_player("R3")
        self.engine.add_player("S4")

        # When all spawn points are taken, engine automatically transitions to IN_PROGRESS.
        # Adding a 5th player should fail due to the state change.
        with self.assertRaisesRegex(ValueError, "not in WAITING_FOR_PLAYERS"):
            self.engine.add_player("T5")

        self.assertEqual(self.engine.state, GameState.IN_PROGRESS)

    # Remove Player Tests
    def test_remove_player_success(self):
        self.engine.add_player("P1")
        self.assertIn("P1", [p.id for p in self.engine.players])
        self.engine.remove_player("P1")
        self.assertNotIn("P1", [p.id for p in self.engine.players])
        self.assertEqual(len(self.engine.free_spawn_points), 4)

    def test_remove_player_not_found(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.engine.remove_player("Ghost")

    def test_remove_player_wrong_state(self):
        self.engine.state = GameState.IN_PROGRESS
        with self.assertRaisesRegex(ValueError, "not in WAITING_FOR_PLAYERS"):
            self.engine.remove_player("P1")

    # Movement Tests
    def test_move_player_success(self):
        # Default grid: (1,1) is spawn, (1,2) is empty, (0,1) is wall
        p = self.engine.add_player("P1")
        p.position.x = 1
        p.position.y = 1
        self.engine.state = GameState.IN_PROGRESS

        # Move Down
        self.engine.move_player("P1", Direction.DOWN)
        self.assertEqual(p.position.y, 2)

    def test_move_player_wall_collision(self):
        p = self.engine.add_player("P1")
        p.position.x = 1
        p.position.y = 1
        self.engine.state = GameState.IN_PROGRESS

        # Move Left into Wall
        self.engine.move_player("P1", Direction.LEFT)
        self.assertEqual(p.position.x, 1)  # Should not move

    def test_move_player_out_of_bounds(self):
        p = self.engine.add_player("P1")
        p.position.x = 0
        p.position.y = 0
        self.engine.grid[0][0] = TileType.EMPTY  # Hack to allow initial placement
        self.engine.state = GameState.IN_PROGRESS

        # Move Up (y = -1)
        self.engine.move_player("P1", Direction.UP)
        self.assertEqual(p.position.y, 0)  # Should not move

    def test_move_player_dead(self):
        p = self.engine.add_player("P1")
        p.is_alive = False
        self.engine.state = GameState.IN_PROGRESS

        original_pos = (p.position.x, p.position.y)
        self.engine.move_player("P1", Direction.DOWN)
        self.assertEqual((p.position.x, p.position.y), original_pos)

    def test_move_player_not_found(self):
        self.engine.state = GameState.IN_PROGRESS
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.engine.move_player("Ghost", Direction.UP)

    def test_move_player_invalid_direction(self):
        self.engine.add_player("P1")
        self.engine.state = GameState.IN_PROGRESS
        with self.assertRaisesRegex(ValueError, "Invalid direction"):
            self.engine.move_player("P1", "INVALID")

    # Bomb Tests
    def test_place_bomb_success(self):
        p = self.engine.add_player("P1")
        self.engine.state = GameState.IN_PROGRESS

        self.engine.place_bomb("P1")
        self.assertEqual(len(self.engine.bombs), 1)
        self.assertTrue(p.has_bomb)
        self.assertEqual(self.engine.bombs[0].position, p.position)

    def test_place_bomb_already_has_bomb(self):
        self.engine.add_player("P1")
        self.engine.state = GameState.IN_PROGRESS
        self.engine.place_bomb("P1")

        self.engine.place_bomb("P1")
        self.assertEqual(len(self.engine.bombs), 1)

    def test_place_bomb_dead(self):
        p = self.engine.add_player("P1")
        p.is_alive = False
        self.engine.state = GameState.IN_PROGRESS

        self.engine.place_bomb("P1")
        self.assertEqual(len(self.engine.bombs), 0)

    def test_place_bomb_player_not_found(self):
        self.engine.state = GameState.IN_PROGRESS
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.engine.place_bomb("Ghost")

    def test_bomb_explosion_mechanics(self):
        # Setup: P1 at (1,1)
        p = self.engine.add_player("P1")
        p.position.x = 1
        p.position.y = 1

        # Add a breakable wall to the RIGHT at (2,1) [x=2, y=1]
        self.engine.grid[1][2] = TileType.WALL_BREAKABLE

        # Place "Target" player DOWN at (1,2) [x=1, y=2] - Empty space in range
        p2 = self.engine.add_player("Target")
        p2.position.x = 1
        p2.position.y = 2

        self.engine.state = GameState.IN_PROGRESS
        self.engine.place_bomb("P1")
        bomb = self.engine.bombs[0]

        # Fast forward timer
        bomb.timer = 1
        self.engine.tick(verbose=True)

        # Verify Bomb gone
        self.assertEqual(len(self.engine.bombs), 0)
        self.assertFalse(p.has_bomb)

        # Verify Breakable Wall gone (replaced by explosion)
        self.assertEqual(self.engine.grid[1][2], TileType.EXPLOSION)

        # Verify P2 status (hit by explosion)
        self.assertFalse(p2.is_alive)

        # P1 is on top of bomb, should die
        self.assertFalse(p.is_alive)

    def test_explosion_blocked_by_unbreakable(self):
        p = self.engine.add_player("P1")
        p.position.x = 1
        p.position.y = 1

        # Unbreakable wall at (2,1) [y=1, x=2]
        self.engine.grid[1][2] = TileType.WALL_UNBREAKABLE

        # Player behind wall at (3,1) [y=1, x=3]
        p2 = self.engine.add_player("Safe")
        p2.position.x = 3
        p2.position.y = 1

        self.engine.state = GameState.IN_PROGRESS
        self.engine.place_bomb("P1")
        self.engine.bombs[0].timer = 1
        self.engine.tick()

        self.assertTrue(p2.is_alive)

    def test_explosion_cleanup(self):
        p = self.engine.add_player("P1")

        # Add TWO survivors with UNIQUE initials so the game doesn't end immediately
        self.engine.add_player("Bob")  # Initial B
        self.engine.add_player("Charlie")  # Initial C

        self.engine.state = GameState.IN_PROGRESS
        self.engine.place_bomb("P1")
        self.engine.bombs[0].timer = 1

        # Explode
        self.engine.tick()
        # Check explosion tile exists
        self.assertEqual(self.engine.grid[p.position.y][p.position.x], TileType.EXPLOSION)

        # Fast forward explosion visual timer
        pos = (p.position.x, p.position.y)
        self.engine.explosion_timers[pos] = 1

        # Tick to clear
        self.engine.tick()
        self.assertEqual(self.engine.grid[p.position.y][p.position.x], TileType.EMPTY)

    # Process GameAction Tests
    def test_process_gameaction_types(self):
        p = self.engine.add_player("P1")
        self.engine.state = GameState.IN_PROGRESS

        self.assertTrue(self.engine.process_gameaction(STAY()))
        self.assertTrue(self.engine.process_gameaction(MOVE_PLAYER("P1", Direction.DOWN)))
        self.assertTrue(self.engine.process_gameaction(PLACE_BOMB("P1")))
        self.assertFalse(self.engine.process_gameaction("NotAnAction"))

    def test_process_gameaction_exception(self):
        self.engine.add_player("P1")
        self.engine.state = GameState.IN_PROGRESS

        with patch.object(self.engine, "place_bomb", side_effect=Exception("Boom")):
            result = self.engine.process_gameaction(PLACE_BOMB("P1"), verbose=True)
            self.assertFalse(result)

    # Tick Tests
    def test_tick_wait_state_countdown(self):
        self.engine.state = GameState.WAITING_FOR_PLAYERS
        # Use distinct initials
        self.engine.add_player("Alpha")
        self.engine.add_player("Bravo")

        self.engine.time_until_start = 0.5
        self.engine.tick_rate = 10

        # Tick 1: 0.5 - 0.1 = 0.4
        self.engine.tick()
        self.assertAlmostEqual(self.engine.time_until_start, 0.4)
        self.assertEqual(self.engine.state, GameState.WAITING_FOR_PLAYERS)

        # Manual jump to finish
        self.engine.time_until_start = 0.05
        self.engine.tick()  # Goes below 0 -> Start
        self.assertEqual(self.engine.state, GameState.IN_PROGRESS)

    def test_tick_wait_state_reset(self):
        self.engine.state = GameState.WAITING_FOR_PLAYERS
        self.engine.add_player("P1")  # Only 1 player
        self.engine.time_until_start = 5.0

        self.engine.tick(verbose=True)
        # Should reset to max
        self.assertEqual(
            self.engine.time_until_start, MAX_TIME_TO_WAIT_FOR_PLAYERS_DURING_WAITING_STATE
        )

    def test_ascii_snapshot_rendering(self):
        self.engine.add_player("Enrico")

        # Force set position to (1, 1) top-left spawn so we know where we are
        p = self.engine.players[0]
        p.position.x = 1
        p.position.y = 1

        self.engine.state = GameState.IN_PROGRESS
        self.engine.place_bomb("Enrico")

        # Move Enrico AWAY from the bomb so the bomb ('@') is visible on the grid.
        # Moving RIGHT from (1,1) goes to (2,1), which is empty in default grid.
        self.engine.move_player("Enrico", Direction.RIGHT)

        snapshot = self.engine.get_ascii_snapshot(verbose=True)

        self.assertIn("Grid Size:", snapshot)
        self.assertIn("Game State:", snapshot)
        self.assertIn("Bombs: 1", snapshot)
        self.assertIn("E", snapshot)
        self.assertIn("@", snapshot)

    def test_wait_state_snapshot(self):
        self.engine.state = GameState.WAITING_FOR_PLAYERS
        self.engine.add_player("Alpha")
        snap = self.engine.get_ascii_snapshot()
        self.assertIn("Waiting for more", snap)

        self.engine.add_player("Bravo")
        snap = self.engine.get_ascii_snapshot()
        self.assertIn("Starting in:", snap)

    def test_game_over_snapshot(self):
        self.engine.state = GameState.GAME_OVER
        self.engine.winner = "P1"
        snap = self.engine.get_ascii_snapshot()
        self.assertIn("Winner: Player 'P1'", snap)

        self.engine.winner = None
        snap = self.engine.get_ascii_snapshot()
        self.assertIn("Game ended in a draw", snap)

    def test_main_execution(self):
        """Test the __main__ block using runpy to cover the non-interactive path."""
        module_name = "bomberman.room_server.GameEngine"

        # Temporarily remove module from sys.modules to prevent RuntimeWarning because it was already imported by the test file
        original_module = sys.modules.get(module_name)
        if module_name in sys.modules:
            del sys.modules[module_name]

        try:
            with patch("builtins.print"):
                with patch("builtins.open", side_effect=FileNotFoundError):
                    runpy.run_module(module_name, run_name="__main__")
        finally:
            if original_module:
                sys.modules[module_name] = original_module
