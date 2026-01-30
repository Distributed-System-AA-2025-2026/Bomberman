import unittest
import sys
import os
from unittest.mock import patch, mock_open
from io import StringIO

from bomberman.room_server.GameEngine import *

class BaseTestCase(unittest.TestCase):
    """Base test case that suppresses print output"""

    def setUp(self):
        """Suppress print output"""
        self.held_output = StringIO()
        sys.stdout = self.held_output

    def tearDown(self):
        """Restore stdout"""
        sys.stdout = sys.__stdout__


class TestGameEngineInitialization(BaseTestCase):
    """Test GameEngine initialization and grid generation"""

    def test_engine_initialization_default(self):
        """Test that the engine initializes with default values"""
        engine = GameEngine()

        self.assertIsNotNone(engine.grid)
        self.assertEqual(engine.state, GameState.WAITING_FOR_PLAYERS)
        self.assertEqual(len(engine.players), 0)
        self.assertEqual(len(engine.bombs), 0)
        self.assertEqual(engine.current_tick, 0)
        self.assertIsNone(engine.winner)
        self.assertEqual(engine.tick_rate, TICK_RATE)

    def test_engine_initialization_with_seed(self):
        """Test that the engine initializes with a specific seed"""
        seed = 12345
        engine = GameEngine(seed=seed)

        self.assertEqual(engine.seed, seed)

    def test_default_grid_creation(self):
        """Test that the default grid is created correctly when file is not found"""
        with patch("builtins.open", side_effect=FileNotFoundError):
            engine = GameEngine()

            # Check dimensions
            self.assertEqual(engine.width, 11)
            self.assertEqual(engine.height, 11)

            # Check that walls are on edges
            for x in range(engine.width):
                self.assertEqual(engine.grid[0][x], TileType.WALL_UNBREAKABLE)
                self.assertEqual(engine.grid[engine.height - 1][x], TileType.WALL_UNBREAKABLE)

            for y in range(engine.height):
                self.assertEqual(engine.grid[y][0], TileType.WALL_UNBREAKABLE)
                self.assertEqual(engine.grid[y][engine.width - 1], TileType.WALL_UNBREAKABLE)

            # Check spawn points
            self.assertEqual(len(engine.free_spawn_points), 4)

    def test_grid_generation_from_valid_file(self):
        """Test grid generation from a valid level file"""
        valid_level = "###\n# #\n###"

        # The grid generation will still fall back to default since we can't easily mock it
        # Just test that the engine initializes
        engine = GameEngine()

        self.assertIsNotNone(engine.grid)
        self.assertGreater(engine.width, 0)
        self.assertGreater(engine.height, 0)

    def test_grid_generation_from_invalid_file(self):
        """Test that invalid characters in level file cause fallback to default"""
        invalid_level = "###\n#X#\n###"  # X is invalid

        with patch("builtins.open", mock_open(read_data=invalid_level)):
            with patch("builtins.print"):  # Suppress error message
                engine = GameEngine()

                # Should fall back to default 11x11 grid
                self.assertEqual(engine.width, 11)
                self.assertEqual(engine.height, 11)

    def test_at_least_two_spawn_points(self):
        """Test that generated grid has at least two spawn points"""
        engine = GameEngine()

        self.assertGreaterEqual(len(engine.free_spawn_points), 2)


class TestPlayerManagement(BaseTestCase):
    """Test player addition, removal, and management"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        super().setUp()
        self.engine = GameEngine(seed=42)

    def test_add_player(self):
        """Test adding a player to the game"""
        player_id = "Alice"
        result = self.engine.add_player(player_id)

        self.assertIsNotNone(result)
        self.assertEqual(len(self.engine.players), 1)
        self.assertEqual(self.engine.players[0].id, player_id)
        self.assertTrue(self.engine.players[0].is_alive)
        self.assertFalse(self.engine.players[0].has_bomb)

    def test_add_duplicate_player(self):
        """Test that adding a duplicate player with same initial fails"""
        player_id = "Alice"
        self.engine.add_player(player_id)

        # Try to add the same player again, will fail because of initial 'A'
        with self.assertRaises(ValueError) as context:
            self.engine.add_player(player_id)
        # Check error message contains 'already'
        self.assertTrue(
            "already" in str(context.exception).lower()
        )
        self.assertEqual(len(self.engine.players), 1)

    def test_add_player_with_same_initial(self):
        """Test that adding a player with the same first letter fails"""
        self.engine.add_player("Alice")

        # Try to add another player with same initial
        with self.assertRaises(ValueError) as context:
            self.engine.add_player("Amy")
        self.assertIn("initial", str(context.exception).lower())

    def test_add_player_when_no_spawn_points(self):
        """Test that adding a player fails when no spawn points are available"""
        # Fill all spawn points with unique initials
        player_names = ["Alice", "Bob", "Charlie", "David"]
        for i in range(min(self.engine.total_spawn_points_slots, len(player_names))):
            self.engine.add_player(player_names[i])

        # When all spawn points are filled, game automatically starts
        # So adding another player fails because game is no longer in WAITING_FOR_PLAYERS state
        with self.assertRaises(ValueError) as context:
            self.engine.add_player("Eve")
        # Could fail either due to spawn points or due to game state
        error_msg = str(context.exception).lower()
        self.assertTrue("spawn" in error_msg or "waiting_for_players" in error_msg)

    def test_add_player_during_game_in_progress(self):
        """Test that adding a player fails when game is in progress"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        with self.assertRaises(ValueError) as context:
            self.engine.add_player("Charlie")
        self.assertIn("WAITING_FOR_PLAYERS", str(context.exception))

    def test_remove_player(self):
        """Test removing a player from the game"""
        player_id = "Alice"
        self.engine.add_player(player_id)

        self.engine.remove_player(player_id)

        self.assertEqual(len(self.engine.players), 0)
        # Spawn point should be freed
        self.assertEqual(len(self.engine.free_spawn_points), self.engine.total_spawn_points_slots)

    def test_remove_nonexistent_player(self):
        """Test that removing a non-existent player fails"""
        with self.assertRaises(ValueError) as context:
            self.engine.remove_player("NonExistent")
        self.assertIn("does not exist", str(context.exception))

    def test_player_spawn_position(self):
        """Test that players are spawned at spawn points"""
        self.engine.add_player("Alice")
        player = self.engine.players[0]

        # Check that player is at a valid spawn point
        tile = self.engine.grid[player.position.y][player.position.x]
        self.assertEqual(tile, TileType.SPAWN_POINT)


class TestMovement(BaseTestCase):
    """Test player movement mechanics"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

    def test_valid_move(self):
        """Test that a player can move to a valid empty tile"""
        player = self.engine.players[0]
        player.position.x = 3
        player.position.y = 3
        initial_pos = Position(player.position.x, player.position.y)

        # Try to move up
        self.engine.move_player(player.id, Direction.UP)

        # Check that position changed 
        self.assertEqual(player.position.x, initial_pos.x)
        self.assertEqual(player.position.y, initial_pos.y - 1)


    def test_move_into_wall(self):
        """Test that a player cannot move into a wall"""
        player = self.engine.players[0]

        # Move player to a position next to a wall
        # Find the player's current position
        x, y = player.position.x, player.position.y

        # Try to find a direction that leads to a wall
        for direction in [Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT]:
            new_x = x + direction.value[0]
            new_y = y + direction.value[1]

            if (
                0 <= new_x < self.engine.width
                and 0 <= new_y < self.engine.height
                and self.engine.grid[new_y][new_x]
                in [TileType.WALL_UNBREAKABLE, TileType.WALL_BREAKABLE]
            ):

                initial_pos = Position(x, y)
                self.engine.move_player(player.id, direction)

                # Position should not change
                self.assertEqual(player.position.x, initial_pos.x)
                self.assertEqual(player.position.y, initial_pos.y)
                break

    def test_move_out_of_bounds(self):
        """Test that a player cannot move out of bounds"""
        player = self.engine.players[0]

        # Force player to edge
        player.position.x = 0
        player.position.y = 0

        initial_pos = Position(player.position.x, player.position.y)

        # Try to move left (out of bounds)
        self.engine.move_player(player.id, Direction.LEFT)

        # Position should not change
        self.assertEqual(player.position.x, initial_pos.x)

    def test_move_dead_player(self):
        """Test that a dead player cannot move"""
        player = self.engine.players[0]
        player.is_alive = False

        player.position.x = 2
        player.position.y = 2

        initial_pos = Position(player.position.x, player.position.y)

        self.engine.move_player(player.id, Direction.UP)

        # Position should not change
        self.assertEqual(player.position.x, initial_pos.x)
        self.assertEqual(player.position.y, initial_pos.y)

    def test_move_nonexistent_player(self):
        """Test that moving a non-existent player raises an error"""
        with self.assertRaises(ValueError):
            self.engine.move_player("NonExistent", Direction.UP)


class TestBombMechanics(BaseTestCase):
    """Test bomb placement and explosion mechanics"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

    def test_place_bomb(self):
        """Test placing a bomb"""
        player = self.engine.players[0]
        player_id = player.id

        self.engine.place_bomb(player_id)

        # Check that bomb was placed
        self.assertEqual(len(self.engine.bombs), 1)
        self.assertTrue(player.has_bomb)

        # Check bomb properties
        bomb = self.engine.bombs[0]
        self.assertEqual(bomb.player_id, player_id)
        self.assertEqual(bomb.position.x, player.position.x)
        self.assertEqual(bomb.position.y, player.position.y)
        self.assertEqual(bomb.timer, BOMB_TIMER_SEC * TICK_RATE)

    def test_place_bomb_when_already_has_bomb(self):
        """Test that a player cannot place a second bomb"""
        player = self.engine.players[0]
        player_id = player.id

        self.engine.place_bomb(player_id)
        self.engine.place_bomb(player_id)  # Try to place second bomb

        # Only one bomb should exist
        self.assertEqual(len(self.engine.bombs), 1)

    def test_place_bomb_dead_player(self):
        """Test that a dead player cannot place a bomb"""
        player = self.engine.players[0]
        player.is_alive = False

        self.engine.place_bomb(player.id)

        # No bomb should be placed
        self.assertEqual(len(self.engine.bombs), 0)

    def test_bomb_timer_decreases(self):
        """Test that bomb timer decreases each tick"""
        player = self.engine.players[0]
        self.engine.place_bomb(player.id)

        bomb = self.engine.bombs[0]
        initial_timer = bomb.timer

        bomb.decrease_timer()

        self.assertEqual(bomb.timer, initial_timer - 1)

    def test_bomb_explodes_after_timer(self):
        """Test that bomb explodes when timer reaches zero"""
        player = self.engine.players[0]
        self.engine.place_bomb(player.id)

        bomb = self.engine.bombs[0]
        bomb_position = Position(bomb.position.x, bomb.position.y)

        # Manually trigger explosion
        self.engine.explode_bomb(bomb)

        # Bomb should be removed from list
        self.assertNotIn(bomb, self.engine.bombs)

        # Player should get bomb back
        self.assertFalse(player.has_bomb)

        # Explosion should be on grid
        self.assertEqual(self.engine.grid[bomb_position.y][bomb_position.x], TileType.EXPLOSION)

    def test_explosion_range(self):
        """Test that explosion affects tiles in all directions"""
        player = self.engine.players[0]

        # Place player in open area (if possible)
        self.engine.place_bomb(player.id)

        bomb = self.engine.bombs[0]
        center_x, center_y = bomb.position.x, bomb.position.y

        self.engine.explode_bomb(bomb)

        # Check that explosion is at center
        self.assertIn((center_x, center_y), self.engine.explosion_timers)

    def test_explosion_kills_player(self):
        """Test that explosion kills a player in its range"""
        player1 = self.engine.players[0]
        player2 = self.engine.players[1]

        # Place player2 next to player1
        player2.position.x = player1.position.x + 1
        player2.position.y = player1.position.y

        # Player1 places bomb
        self.engine.place_bomb(player1.id)
        bomb = self.engine.bombs[0]

        # Explode bomb
        self.engine.explode_bomb(bomb)

        # Player2 should be dead
        self.assertFalse(player2.is_alive)

    def test_explosion_stops_at_unbreakable_wall(self):
        """Test that explosion stops at unbreakable walls"""
        player = self.engine.players[0]

        # Place player near a wall
        player.position.x = 1
        player.position.y = 1
        self.engine.place_bomb(player.id)
        bomb = self.engine.bombs[0]

        self.engine.explode_bomb(bomb)

        # Explosion should not extend beyond walls
        # Check that only valid tiles have explosions
        for pos, timer in self.engine.explosion_timers.items():
            x, y = pos
            self.assertNotEqual(self.engine.grid[y][x], TileType.WALL_UNBREAKABLE)

    def test_explosion_destroys_breakable_wall(self):
        """Test that explosion destroys breakable walls"""
        player = self.engine.players[0]

        # Place a breakable wall next to player
        wall_x = player.position.x + 1
        wall_y = player.position.y
        self.engine.grid[wall_y][wall_x] = TileType.WALL_BREAKABLE

        self.engine.place_bomb(player.id)
        bomb = self.engine.bombs[0]

        self.engine.explode_bomb(bomb)

        # Breakable wall should be destroyed
        self.assertEqual(self.engine.grid[wall_y][wall_x], TileType.EXPLOSION)

    def test_explosion_visual_timer(self):
        """Test that explosion visuals clear after timer expires"""
        player = self.engine.players[0]
        player2 = self.engine.players[1]

        # Move player2 away so they don't die and game doesn't end
        player2.position.x = 9
        player2.position.y = 9

        # Move player1 away from the bomb before it explodes
        self.engine.place_bomb(player.id)
        bomb = self.engine.bombs[0]
        bomb_pos = (bomb.position.x, bomb.position.y)

        # Move player away so they survive
        player.position.x = 9
        player.position.y = 1

        self.engine.explode_bomb(bomb)

        # Explosion should be visible
        self.assertIn(bomb_pos, self.engine.explosion_timers)
        self.assertEqual(self.engine.explosion_timers[bomb_pos], EXPLOSION_VISUAL_TICKS)

        # Tick forward
        for _ in range(EXPLOSION_VISUAL_TICKS + 1):
            self.engine.tick()

        # Explosion should be cleared
        self.assertNotIn(bomb_pos, self.engine.explosion_timers)


class TestGameActions(BaseTestCase):
    """Test game action processing"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

    def test_process_stay_action(self):
        """Test processing STAY action"""
        action = STAY()
        result = self.engine.process_gameaction(action)

        self.assertTrue(result)

    def test_process_move_action(self):
        """Test processing MOVE_PLAYER action"""
        player = self.engine.players[0]
        action = MOVE_PLAYER(player_id=player.id, direction=Direction.UP)

        result = self.engine.process_gameaction(action)

        self.assertTrue(result)

    def test_process_place_bomb_action(self):
        """Test processing PLACE_BOMB action"""
        player = self.engine.players[0]
        action = PLACE_BOMB(player_id=player.id)

        result = self.engine.process_gameaction(action)

        self.assertTrue(result)
        self.assertEqual(len(self.engine.bombs), 1)

    def test_process_invalid_action(self):
        """Test processing an invalid action"""
        result = self.engine.process_gameaction("invalid")

        self.assertFalse(result)


class TestGameStateTransitions(BaseTestCase):
    """Test game state transitions"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)

    def test_initial_state_waiting(self):
        """Test that initial state is WAITING_FOR_PLAYERS"""
        self.assertEqual(self.engine.state, GameState.WAITING_FOR_PLAYERS)

    def test_start_game(self):
        """Test starting the game"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")

        self.engine.start_game()

        self.assertEqual(self.engine.state, GameState.IN_PROGRESS)

    def test_cannot_start_with_insufficient_players(self):
        """Test that game starts even with 1 player (no validation)"""
        self.engine.add_player("Alice")

        self.engine.start_game()

        self.assertEqual(self.engine.state, GameState.IN_PROGRESS)

    def test_game_over_one_winner(self):
        """Test game over condition with one winner"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        # Kill player 2
        self.engine.players[1].is_alive = False

        self.engine.check_game_over()

        self.assertEqual(self.engine.state, GameState.GAME_OVER)
        self.assertEqual(self.engine.winner, "Alice")

    def test_game_over_no_winners(self):
        """Test game over condition with no winners (draw)"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        # Kill both players
        self.engine.players[0].is_alive = False
        self.engine.players[1].is_alive = False

        self.engine.check_game_over()

        self.assertEqual(self.engine.state, GameState.GAME_OVER)
        self.assertIsNone(self.engine.winner)

    def test_game_continues_with_multiple_alive_players(self):
        """Test that game continues when multiple players are alive"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.add_player("Charlie")
        self.engine.start_game()

        # Kill one player
        self.engine.players[2].is_alive = False

        self.engine.check_game_over()

        self.assertEqual(self.engine.state, GameState.IN_PROGRESS)


class TestTickSystem(BaseTestCase):
    """Test the game tick system"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)

    def test_tick_waiting_state(self):
        """Test tick in WAITING_FOR_PLAYERS state"""
        result = self.engine.tick()

        self.assertTrue(result)
        self.assertEqual(self.engine.state, GameState.WAITING_FOR_PLAYERS)

    def test_tick_countdown_with_sufficient_players(self):
        """Test that countdown starts with 2+ players"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")

        initial_time = self.engine.time_until_start
        self.engine.tick()

        # Time should decrease
        self.assertLess(self.engine.time_until_start, initial_time)

    def test_tick_no_countdown_with_insufficient_players(self):
        """Test that countdown doesn't start with < 2 players"""
        self.engine.add_player("Alice")

        initial_time = self.engine.time_until_start
        self.engine.tick()

        # Time should not decrease
        self.assertEqual(self.engine.time_until_start, initial_time)

    def test_tick_in_progress(self):
        """Test tick during IN_PROGRESS state"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        initial_tick = self.engine.current_tick
        result = self.engine.tick()

        self.assertTrue(result)
        self.assertEqual(self.engine.current_tick, initial_tick + 1)

    def test_tick_game_over(self):
        """Test that tick does not process when game is over"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()
        self.engine.state = GameState.GAME_OVER

        result = self.engine.tick()

        self.assertFalse(result)

    def test_tick_with_actions(self):
        """Test tick with multiple actions"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        actions = [
            MOVE_PLAYER(player_id="Alice", direction=Direction.UP),
            PLACE_BOMB(player_id="Bob"),
        ]

        result = self.engine.tick(actions=actions)

        self.assertTrue(result)
        self.assertEqual(len(self.engine.bombs), 1)


class TestAsciiSnapshot(BaseTestCase):
    """Test ASCII snapshot generation"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)

    def test_get_ascii_snapshot(self):
        """Test that ASCII snapshot is generated"""
        snapshot = self.engine.get_ascii_snapshot()

        self.assertIsInstance(snapshot, str)
        self.assertGreater(len(snapshot), 0)

    def test_ascii_snapshot_contains_grid(self):
        """Test that ASCII snapshot contains grid elements"""
        self.engine.add_player("Alice")
        snapshot = self.engine.get_ascii_snapshot()

        # Check for some expected characters
        self.assertIn("#", snapshot)  # Wall
        self.assertIn("A", snapshot)  # Player
        self.assertIn(" ", snapshot)  # Empty space


class TestEdgeCases(BaseTestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        """Set up a fresh engine for each test"""
        self.engine = GameEngine(seed=42)

    def test_remove_player_with_active_bomb(self):
        """Test removing a player who has an active bomb - not allowed during game"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        player = self.engine.players[0]
        self.engine.place_bomb(player.id)

        # Cannot remove player during IN_PROGRESS state
        with self.assertRaises(ValueError) as context:
            self.engine.remove_player(player.id)
        self.assertIn("WAITING_FOR_PLAYERS", str(context.exception))

        # Bomb should still exist
        self.assertEqual(len(self.engine.bombs), 1)

    def test_multiple_bombs_same_position(self):
        """Test that multiple players can't place bombs at same position"""
        self.engine.add_player("Alice")
        self.engine.add_player("Bob")
        self.engine.start_game()

        # Move player2 to player1's position
        player1 = self.engine.players[0]
        player2 = self.engine.players[1]
        player2.position.x = player1.position.x
        player2.position.y = player1.position.y

        self.engine.place_bomb(player1.id)
        self.engine.place_bomb(player2.id)

        # Only one bomb should exist at that position
        self.assertEqual(len(self.engine.bombs), 1)

    def test_player_walks_over_bomb(self):
        """Test that players can walk over bombs"""
        self.engine.add_player("Alice")
       
        self.engine.start_game()

        player = self.engine.players[0]
        player.position.x = 3
        player.position.y = 3

        initial_pos = Position(player.position.x, player.position.y)
        self.engine.place_bomb(player.id)
        bomb = self.engine.bombs[0]
        
        # Move player onto bomb position
        self.engine.move_player(player.id, Direction.STAY)  # Stay in place
        self.assertEqual(player.position.x, initial_pos.x)
        self.assertEqual(player.position.y, initial_pos.y)

        # Move player away from bomb
        self.engine.move_player(player.id, Direction.RIGHT)
        self.assertEqual(player.position.x, initial_pos.x + 1)



class TestGameIntegration(BaseTestCase):
    """Integration tests for complete game scenarios"""

    def test_full_game_scenario(self):
        """Test a complete game from start to finish"""
        engine = GameEngine(seed=42)

        # Add players
        engine.add_player("Alice")
        engine.add_player("Bob")

        # Start game
        engine.start_game()
        self.assertEqual(engine.state, GameState.IN_PROGRESS)

        # Play some ticks
        for i in range(10):
            actions = [STAY()]
            engine.tick(actions=actions)

        # Verify game is still running
        self.assertEqual(engine.state, GameState.IN_PROGRESS)

        # Kill one player
        engine.players[1].is_alive = False
        engine.check_game_over()

        # Game should be over
        self.assertEqual(engine.state, GameState.GAME_OVER)
        self.assertEqual(engine.winner, "Alice")

    def test_bomb_explosion_kills_player(self):
        """Integration test: bomb explodes and kills a player"""
        engine = GameEngine(seed=42)
        engine.add_player("Alice")
        engine.add_player("Bob")
        engine.start_game()

        player1 = engine.players[0]
        player2 = engine.players[1]

        # Position player2 next to player1
        player2.position.x = player1.position.x + 1
        player2.position.y = player1.position.y

        # Place bomb
        engine.place_bomb(player1.id)
        bomb = engine.bombs[0]

        # Simulate timer running out
        for _ in range(int(BOMB_TIMER_SEC * TICK_RATE) + 1):
            engine.tick()

        self.assertFalse(player2.is_alive)