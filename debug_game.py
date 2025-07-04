#!/usr/bin/env python3
"""Debug script to analyze a specific incomplete game from the debug database."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from secret_agi.engine.game_engine import GameEngine, load_game


async def analyze_game(game_id: str, db_path: str = "debug_failed_games.db") -> None:
    """Analyze a specific game from the debug database."""
    
    if not Path(db_path).exists():
        print(f"❌ Debug database not found: {db_path}")
        print("Run test_completeness.py with DEBUG_FAILED_GAMES=True first")
        return
    
    print(f"🔍 Analyzing game {game_id} from {db_path}")
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check if game exists
        cursor = conn.execute("SELECT id FROM games WHERE id = ?", (game_id,))
        if not cursor.fetchone():
            print(f"❌ Game {game_id} not found in database")
            return
        
        # Get final game state
        cursor = conn.execute("""
            SELECT turn_number, state_data 
            FROM game_states 
            WHERE game_id = ? 
            ORDER BY turn_number DESC 
            LIMIT 1
        """, (game_id,))
        
        final_state = cursor.fetchone()
        if not final_state:
            print("❌ No state data found!")
            return
        
        print(f"\n📊 Final Game State (Turn {final_state['turn_number']}):")
        
        # Parse the state data
        state = json.loads(final_state['state_data'])
        
        capability = state.get('capability', 0)
        safety = state.get('safety', 0)
        deck_size = len(state.get('deck', []))
        discard_size = len(state.get('discard', []))
        
        print(f"Capability: {capability}")
        print(f"Safety: {safety}")
        print(f"Capability - Safety: {capability - safety}")
        print(f"Deck size: {deck_size}")
        print(f"Discard size: {discard_size}")
        print(f"Current phase: {state.get('current_phase', 'unknown')}")
        print(f"Failed proposals: {state.get('failed_proposals', 'unknown')}")
        print(f"Is game over: {state.get('is_game_over', 'unknown')}")
        
        # Check players
        players = state.get('players', [])
        alive_count = sum(1 for p in players if p.get('alive', True))
        print(f"Players alive: {alive_count}/{len(players)}")
        
        # Manual win condition analysis
        print(f"\n🏆 Win Condition Analysis:")
        
        # Safety wins
        safety_wins = []
        if safety >= 15:
            safety_wins.append("Safety ≥ 15")
        if capability >= 10 and safety >= capability:
            safety_wins.append(f"C≥10 and S≥C ({capability}≥10 and {safety}≥{capability})")
        if deck_size == 0 and safety >= capability:
            safety_wins.append(f"Deck exhausted and S≥C ({safety}≥{capability})")
        
        # Evil wins  
        evil_wins = []
        if capability >= 15 and safety < 10:
            evil_wins.append(f"C≥15 and S<10 ({capability}≥15 and {safety}<10)")
        if capability - safety >= 6:
            evil_wins.append(f"C-S≥6 ({capability}-{safety}={capability-safety}≥6)")
        if deck_size == 0 and safety < capability:
            evil_wins.append(f"Deck exhausted and S<C ({safety}<{capability})")
        
        if safety_wins:
            print("❌ Safety SHOULD have won:")
            for condition in safety_wins:
                print(f"  • {condition}")
        
        if evil_wins:
            print("❌ Evil SHOULD have won:")
            for condition in evil_wins:
                print(f"  • {condition}")
        
        if not safety_wins and not evil_wins:
            print("✅ No win conditions met - game should continue")
            if deck_size == 0:
                print("⚠️  But deck is empty! This suggests a bug in deck exhaustion handling")
        
        # Get recent actions to see what was happening
        print(f"\n📝 Recent Actions (last 15):")
        cursor = conn.execute("""
            SELECT turn_number, player_id, action_type, is_valid, error_message, action_data
            FROM actions 
            WHERE game_id = ? 
            ORDER BY turn_number DESC 
            LIMIT 15
        """, (game_id,))
        
        recent_actions = cursor.fetchall()
        
        for action in recent_actions:
            status = "✓" if action['is_valid'] else "✗"
            error = f" ({action['error_message']})" if action['error_message'] else ""
            
            # Parse action data for context
            action_info = ""
            try:
                if action['action_data']:
                    action_data = json.loads(action['action_data'])
                    if action_data:
                        action_info = f" {action_data}"
            except:
                pass
            
            print(f"  Turn {action['turn_number']:3d}: {action['player_id']} -> {action['action_type']:<15} {status}{action_info}{error}")
        
        # Pattern analysis
        print(f"\n🔍 Pattern Analysis:")
        
        # Count action types in recent history
        action_counts: dict[str, int] = {}
        invalid_count = 0
        for action in recent_actions:
            action_type = action['action_type']
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
            if not action['is_valid']:
                invalid_count += 1
        
        print(f"Recent action distribution: {dict(action_counts)}")
        print(f"Invalid actions: {invalid_count}/{len(recent_actions)} ({invalid_count/len(recent_actions)*100:.1f}%)")
        
        # Check for loops
        if action_counts.get('vote_team', 0) > 8:
            print("🔄 High vote_team count suggests voting deadlock")
        
        if invalid_count > len(recent_actions) // 3:
            print("❌ High invalid action rate suggests logic bug")
        
        # Check if we can load and continue the game
        print(f"\n🔧 Recovery Analysis:")
        try:
            engine = await load_game(game_id, database_url=f"sqlite+aiosqlite:///{db_path}")
            current_state = engine.get_game_state()
            if current_state:
                print("✅ Game state can be loaded successfully")
                print(f"Loaded state: Turn {current_state.turn_number}, Phase {current_state.current_phase.value}")
            else:
                print("❌ Failed to load game state")
        except Exception as e:
            print(f"❌ Error loading game: {e}")
    
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python debug_game.py <game_id>")
        print("\nTo generate debug data, run:")
        print("  1. Edit test_completeness.py and set DEBUG_FAILED_GAMES = True")
        print("  2. Run test_completeness.py")
        print("  3. Use the game IDs from failed games")
        sys.exit(1)
    
    game_id = sys.argv[1]
    asyncio.run(analyze_game(game_id))


if __name__ == "__main__":
    main()