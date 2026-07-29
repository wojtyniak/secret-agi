"""Running games: one game at a time here, whole scheduled runs in `runner.py`."""

from .game_runner import GameResult, GameRunner, run_game, summarise_results

__all__ = ["GameResult", "GameRunner", "run_game", "summarise_results"]
