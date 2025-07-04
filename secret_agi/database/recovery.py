"""Game recovery mechanisms for Secret AGI."""

from typing import Any

from .connection import get_async_session
from .enums import GameStatus, RecoveryType
from .operations import GameOperations, RecoveryOperations


class GameRecoveryManager:
    """Manages game recovery and restart operations."""

    @staticmethod
    async def check_for_interrupted_games() -> list[str]:
        """Check for games that need recovery on startup."""
        async with get_async_session() as session:
            return await RecoveryOperations.find_interrupted_games(session)

    @staticmethod
    async def recover_game(game_id: str) -> dict[str, Any]:
        """
        Recover a specific interrupted game.

        Returns:
            Recovery report with status and actions taken.
        """
        async with get_async_session() as session:
            # Analyze the failure
            analysis = await RecoveryOperations.analyze_failure_type(session, game_id)

            recovery_report = {
                "game_id": game_id,
                "failure_type": analysis["type"],
                "last_valid_turn": analysis["last_valid_turn"],
                "actions_taken": [],
                "recovered_state": None,
                "success": False,
            }

            try:
                if analysis["type"] == RecoveryType.INCOMPLETE_ACTION:
                    # Mark incomplete actions as failed and load last state
                    marked_count = (
                        await RecoveryOperations.mark_incomplete_actions_failed(
                            session, game_id, "Recovered from process interruption"
                        )
                    )
                    recovery_report["actions_taken"].append(
                        f"Marked {marked_count} incomplete actions as failed"
                    )

                    # Load the last valid state
                    state = await GameOperations.load_game_state(
                        session, game_id, analysis["last_valid_turn"]
                    )
                    if state:
                        recovery_report["recovered_state"] = state
                        recovery_report["success"] = True
                        recovery_report["actions_taken"].append(
                            f"Loaded state from turn {analysis['last_valid_turn']}"
                        )

                elif analysis["type"] == RecoveryType.AGENT_TIMEOUT:
                    # Agent was thinking but never submitted action - just load last state
                    state = await GameOperations.load_game_state(session, game_id)
                    if state:
                        recovery_report["recovered_state"] = state
                        recovery_report["success"] = True
                        recovery_report["actions_taken"].append(
                            "Loaded last complete state"
                        )

                elif analysis["type"] == RecoveryType.TRANSACTION_FAILURE:
                    # Need to find last consistent state
                    consistent_state = (
                        await RecoveryOperations.get_last_consistent_state(
                            session, game_id
                        )
                    )
                    if consistent_state:
                        turn, state = consistent_state
                        recovery_report["recovered_state"] = state
                        recovery_report["last_valid_turn"] = turn
                        recovery_report["success"] = True
                        recovery_report["actions_taken"].append(
                            f"Rolled back to consistent state at turn {turn}"
                        )

                # Update game status if recovery successful
                if recovery_report["success"]:
                    await GameOperations.update_game_status(
                        session,
                        game_id,
                        GameStatus.ACTIVE,
                        current_turn=recovery_report["last_valid_turn"],
                    )
                    recovery_report["actions_taken"].append(
                        "Updated game status to ACTIVE"
                    )
                else:
                    await GameOperations.update_game_status(
                        session, game_id, GameStatus.FAILED
                    )
                    recovery_report["actions_taken"].append(
                        "Marked game as FAILED due to unrecoverable state"
                    )

            except Exception as e:
                recovery_report["error"] = str(e)
                recovery_report["actions_taken"].append(
                    f"Recovery failed with error: {e}"
                )

                # Mark game as failed
                await GameOperations.update_game_status(
                    session, game_id, GameStatus.FAILED
                )

            return recovery_report

    @staticmethod
    async def recover_all_interrupted_games() -> list[dict[str, Any]]:
        """Recover all interrupted games found in the database."""
        interrupted_games = await GameRecoveryManager.check_for_interrupted_games()

        recovery_reports = []
        for game_id in interrupted_games:
            report = await GameRecoveryManager.recover_game(game_id)
            recovery_reports.append(report)

        return recovery_reports

    @staticmethod
    async def force_recovery_status(
        game_id: str, status: GameStatus, reason: str = "Manual intervention"
    ) -> None:
        """Force a game to a specific status (for manual recovery)."""
        async with get_async_session() as session:
            await GameOperations.update_game_status(session, game_id, status)

            # Record this as a recovery action in events
            await GameOperations.record_event(
                session,
                game_id,
                0,
                "manual_recovery",
                None,
                {
                    "action": "force_status_change",
                    "new_status": status.value,
                    "reason": reason,
                },
            )
