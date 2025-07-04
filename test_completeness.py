#!/usr/bin/env python3
"""Test script to validate game completeness with RandomPlayer automated runs."""

import asyncio
import sys
import time
from statistics import mean, median

from secret_agi.engine.game_engine import create_game


def test_game_completeness(num_games: int = 100, player_count: int = 5) -> bool:
    """Test that games complete reliably with random players."""
    print(f"Testing {num_games} random games with {player_count} players...")

    completed_games = 0
    failed_games = 0
    turn_counts = []
    winner_counts = {"Safety": 0, "Accelerationist": 0, "AGI": 0}

    start_time = time.time()

    for i in range(num_games):
        if i % 10 == 0:
            print(f"  Progress: {i}/{num_games}")

        try:
            player_ids = [f"player_{j}" for j in range(player_count)]
            engine = asyncio.run(
                create_game(player_ids, seed=i, database_url="sqlite:///:memory:")
            )
            # Use higher turn limit for more reliable completion
            result = asyncio.run(engine.simulate_to_completion(max_turns=2000))

            if result["completed"]:
                completed_games += 1
                turn_counts.append(result["turns_taken"])

                # Count winners
                winners = result["winners"]
                if "Safety" in winners:
                    winner_counts["Safety"] += 1
                if "Accelerationist" in winners or "AGI" in winners:
                    if "Accelerationist" in winners:
                        winner_counts["Accelerationist"] += 1
                    if "AGI" in winners:
                        winner_counts["AGI"] += 1
            else:
                failed_games += 1
                print(
                    f"    Game {i} failed to complete after {result['turns_taken']} turns"
                )

        except Exception as e:
            failed_games += 1
            print(f"    Game {i} crashed: {e}")

    end_time = time.time()

    # Results
    completion_rate = completed_games / num_games

    print("\n=== Results ===")
    print(f"Completed games: {completed_games}/{num_games} ({completion_rate:.1%})")
    print(f"Failed games: {failed_games}")
    print(f"Total time: {end_time - start_time:.2f}s")
    print(f"Avg time per game: {(end_time - start_time) / num_games:.3f}s")

    if turn_counts:
        print("\nTurn statistics:")
        print(f"  Mean turns: {mean(turn_counts):.1f}")
        print(f"  Median turns: {median(turn_counts):.1f}")
        print(f"  Min turns: {min(turn_counts)}")
        print(f"  Max turns: {max(turn_counts)}")

    print("\nWinner distribution:")
    for faction, count in winner_counts.items():
        if completed_games > 0:
            percentage = count / completed_games * 100
            print(f"  {faction}: {count} ({percentage:.1f}%)")

    # Validation
    success = True

    if completion_rate < 0.95:
        print(f"\n❌ FAIL: Completion rate {completion_rate:.1%} below 95%")
        success = False
    else:
        print(f"\n✅ PASS: Completion rate {completion_rate:.1%}")

    if turn_counts and max(turn_counts) > 500:
        print(f"❌ FAIL: Some games took too long (max: {max(turn_counts)} turns)")
        success = False
    else:
        print("✅ PASS: All games completed in reasonable time")

    # Check that both sides can win
    safety_wins = winner_counts["Safety"]
    evil_wins = winner_counts["Accelerationist"] + winner_counts["AGI"]

    if completed_games > 20:  # Only check balance if we have enough games
        if safety_wins == 0 or evil_wins == 0:
            print(
                f"❌ FAIL: Unbalanced outcomes (Safety: {safety_wins}, Evil: {evil_wins})"
            )
            success = False
        else:
            print("✅ PASS: Both sides can win")

    return success


def test_different_player_counts() -> bool:
    """Test game completeness across different player counts."""
    print("Testing different player counts...")

    all_success = True

    for player_count in [5, 7, 10]:
        print(f"\n--- Testing {player_count} players ---")
        success = test_game_completeness(num_games=20, player_count=player_count)
        if not success:
            all_success = False

    return all_success


def main() -> int:
    """Main test runner."""
    print("Secret AGI Game Engine Completeness Test")
    print("=" * 50)

    # Test basic completeness
    success1 = test_game_completeness(num_games=50, player_count=5)

    print("\n" + "=" * 50)

    # Test different player counts
    success2 = test_different_player_counts()

    print("\n" + "=" * 50)

    if success1 and success2:
        print("🎉 ALL TESTS PASSED!")
        print("The game engine reliably produces complete games.")
        return 0
    else:
        print("💥 SOME TESTS FAILED!")
        print("The game engine needs debugging.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
