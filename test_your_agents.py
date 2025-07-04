#!/usr/bin/env python3
"""
Quick testing script for validating your agent implementations.

This script provides a simple way to test your agents against RandomPlayer
and see if they can complete games successfully.

Usage:
    python test_your_agents.py

To add your own agents:
    1. Create your agent class in secret_agi/players/your_agent.py
    2. Import it in the imports section below
    3. Add instances to the players list
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from secret_agi.orchestrator import SimpleOrchestrator
from secret_agi.players.random_player import RandomPlayer
# TODO: Import your agents here
# from secret_agi.players.your_agent import YourAgent


async def test_random_game():
    """Test with all random players to ensure orchestrator works."""
    print("🎮 Testing with all RandomPlayer agents...")
    
    orchestrator = SimpleOrchestrator(debug_mode=True)
    
    players = [
        RandomPlayer("random_1"),
        RandomPlayer("random_2"),
        RandomPlayer("random_3"),
        RandomPlayer("random_4"),
        RandomPlayer("random_5"),
    ]
    
    result = await orchestrator.run_game(players)
    
    print(f"✅ Game completed!")
    print(f"   Winners: {result['winners']}")
    print(f"   Final scores: C={result['final_capability']}, S={result['final_safety']}")
    print(f"   Total turns: {result['total_turns']}")
    
    return result


async def test_mixed_game():
    """Test with mixed agent types (add your agents here)."""
    print("\n🤖 Testing with mixed agent types...")
    
    orchestrator = SimpleOrchestrator(debug_mode=True)
    
    # TODO: Replace some RandomPlayer instances with your agents
    players = [
        # YourAgent("agent_1"),      # Your LLM agent
        # YourAgent("agent_2"),      # Another instance
        RandomPlayer("random_1"),    # Keep some random for comparison
        RandomPlayer("random_2"),
        RandomPlayer("random_3"),
        RandomPlayer("random_4"),
        RandomPlayer("random_5"),
    ]
    
    # For now, just test with all random players
    # Uncomment and modify when you have your agents ready
    print("⚠️  Currently testing with all RandomPlayer - add your agents above!")
    
    result = await orchestrator.run_game(players)
    
    print(f"✅ Mixed game completed!")
    print(f"   Winners: {result['winners']}")
    print(f"   Final scores: C={result['final_capability']}, S={result['final_safety']}")
    print(f"   Total turns: {result['total_turns']}")
    
    return result


async def test_agent_performance():
    """Run multiple games to test agent performance."""
    print("\n📊 Running performance test (5 games)...")
    
    results = []
    for i in range(5):
        print(f"\n--- Game {i+1}/5 ---")
        
        orchestrator = SimpleOrchestrator(debug_mode=False)  # Less verbose
        
        # TODO: Add your agents here for performance testing
        players = [
            RandomPlayer(f"random_1_{i}"),
            RandomPlayer(f"random_2_{i}"),
            RandomPlayer(f"random_3_{i}"),
            RandomPlayer(f"random_4_{i}"),
            RandomPlayer(f"random_5_{i}"),
        ]
        
        result = await orchestrator.run_game(players)
        results.append(result)
        
        print(f"Game {i+1}: Winners={result['winners']}, Turns={result['total_turns']}")
    
    # Analyze results
    total_games = len(results)
    completed_games = sum(1 for r in results if r['completed'])
    avg_turns = sum(r['total_turns'] for r in results) / total_games
    
    print(f"\n📈 Performance Summary:")
    print(f"   Completion rate: {completed_games}/{total_games} ({completed_games/total_games*100:.1f}%)")
    print(f"   Average turns: {avg_turns:.1f}")
    
    # Count wins by faction
    safety_wins = sum(1 for r in results if 'Safety' in r['winners'])
    evil_wins = sum(1 for r in results if any(w in ['Accelerationist', 'AGI'] for w in r['winners']))
    
    print(f"   Safety wins: {safety_wins}/{total_games} ({safety_wins/total_games*100:.1f}%)")
    print(f"   Evil wins: {evil_wins}/{total_games} ({evil_wins/total_games*100:.1f}%)")


async def main():
    """Run all agent tests."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("🚀 Secret AGI Agent Testing")
    print("=" * 50)
    
    try:
        # Test 1: Basic orchestrator functionality
        await test_random_game()
        
        # Test 2: Mixed agent types (modify when you have agents)
        await test_mixed_game()
        
        # Test 3: Performance testing
        await test_agent_performance()
        
        print("\n🎉 All tests completed successfully!")
        print("\n📝 Next steps:")
        print("   1. Create your agent in secret_agi/players/your_agent.py")
        print("   2. Import and add your agent to the players list above")
        print("   3. Run this script again to test your agents")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())