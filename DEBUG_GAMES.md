# Game Debugging Workflow

This document explains how to debug incomplete or failed games using database persistence.

## Quick Start

1. **Enable debug mode** in `test_completeness.py`:
   ```python
   DEBUG_FAILED_GAMES = True
   ```

2. **Set up the database**:
   ```bash
   just db-upgrade  # Creates the database tables
   ```

3. **Run tests to capture failed games**:
   ```bash
   uv run python test_completeness.py
   ```

4. **Analyze a specific failed game**:
   ```bash
   uv run python debug_game.py <game_id>
   ```

## How It Works

### test_completeness.py
- When `DEBUG_FAILED_GAMES = True`, failed games are saved to `debug_failed_games.db`
- Each failed game gets a unique ID for later analysis
- Console output includes the game ID and instructions for debugging

### debug_game.py
- Loads a specific game from the debug database
- Analyzes the final game state and win conditions
- Shows recent action history to identify patterns
- Performs automatic pattern analysis (voting loops, invalid actions, etc.)
- Tests game state loading for recovery scenarios

## Example Debugging Session

```bash
# 1. Enable debugging and run tests
$ edit test_completeness.py  # Set DEBUG_FAILED_GAMES = True
$ just db-upgrade
$ uv run python test_completeness.py

# Output includes:
# Game 9 (ID: abc123) failed to complete after 52 turns
# Failed game data saved to debug_failed_games.db
# Use: python debug_game.py abc123

# 2. Analyze the failed game
$ uv run python debug_game.py abc123

# Output shows:
# 📊 Final Game State (Turn 52):
# Capability: 8
# Safety: 4
# Deck size: 0
# ❌ Evil SHOULD have won:
#   • Deck exhausted and S<C (4<8)
# 🔍 Pattern Analysis:
# Recent action distribution: {'vote_team': 12, 'nominate': 4}
# 🔄 High vote_team count suggests voting deadlock
```

## What to Look For

### Common Issues

1. **Win Condition Bugs**:
   - Game should have ended but didn't
   - Look for deck exhaustion with clear winner
   - Check capability/safety thresholds

2. **Voting Deadlocks**:
   - High `vote_team` action counts
   - Failed proposals counter stuck
   - Teams never forming successfully

3. **Invalid Action Loops**:
   - High percentage of invalid actions
   - Same invalid action repeated
   - Logic errors in action validation

4. **State Inconsistencies**:
   - Deck empty but game continuing
   - Invalid phase transitions
   - Incorrect player states

### Analysis Features

The debug script provides:
- **Win condition analysis**: Checks all win conditions against final state
- **Action pattern detection**: Identifies loops and deadlocks
- **State validation**: Verifies game state consistency
- **Recovery testing**: Tests if the game can be loaded and continued

## Database Schema

The debug database contains:
- `games`: Game metadata and configuration
- `game_states`: Complete state snapshots per turn
- `actions`: All action attempts with validation results
- `events`: Game events log

You can also query the database directly:
```sql
-- Find all failed games
SELECT id, created_at FROM games WHERE status = 'ACTIVE';

-- Get action history for a game
SELECT turn_number, player_id, action_type, is_valid 
FROM actions 
WHERE game_id = 'abc123' 
ORDER BY turn_number;
```

## Cleanup

```bash
# Remove debug database
rm debug_failed_games.db

# Reset to normal testing
# Edit test_completeness.py: DEBUG_FAILED_GAMES = False
```

## Integration with Recovery System

The debug tools integrate with the game recovery mechanisms:
- Failed games can be loaded using `load_game(game_id)`
- Recovery operations can analyze and fix interrupted games
- State reconstruction verifies data integrity

This workflow enables systematic debugging of game logic issues and helps maintain high completion rates across all game configurations.