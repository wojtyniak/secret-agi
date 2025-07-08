"""
Simple FastAPI backend for Secret AGI web game viewing.

This provides minimal endpoints for creating and monitoring games
without complex real-time features.
"""

import asyncio
import logging
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..orchestrator import SimpleOrchestrator
from ..players.random_player import RandomPlayer

# TODO: Import your agents here when available
# from ..players.your_agent import YourAgent

logger = logging.getLogger(__name__)

# Global game state
current_game: dict[str, Any] = {}
current_orchestrator: SimpleOrchestrator | None = None
game_log: list[dict[str, Any]] = []


class GameRequest(BaseModel):
    """Request to start a new game."""
    player_count: int = 5
    use_debug: bool = True
    # TODO: Add agent type selection when agents available
    # agent_types: List[str] = ["random", "random", "random", "random", "random"]


class GameResponse(BaseModel):
    """Response from game operations."""
    success: bool
    message: str
    game_id: str | None = None
    data: Any | None = None  # Changed from Dict to Any to allow lists


app = FastAPI(title="Secret AGI Game Viewer", version="1.0.0")

# Mount static files for UI
# app.mount("/static", StaticFiles(directory="secret_agi/ui"), name="static")


@app.get("/")
async def root():
    """Serve the main game viewer page."""
    # For now, return a simple HTML page
    # TODO: Replace with actual UI file when created
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Secret AGI Game Viewer</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background-color: #d4edda; border: 1px solid #c3e6cb; }
            .error { background-color: #f8d7da; border: 1px solid #f5c6cb; }
            .info { background-color: #d1ecf1; border: 1px solid #bee5eb; }
            button { padding: 10px 20px; margin: 5px; }
            .game-state { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }
            .log-entry { margin: 3px 0; padding: 8px; background: #fff; border-left: 3px solid #007bff; border-radius: 3px; font-family: monospace; font-size: 13px; }
            #log-entries { max-height: 400px; overflow-y: auto; border: 1px solid #dee2e6; border-radius: 5px; padding: 10px; }
        </style>
    </head>
    <body>
        <h1>🎮 Secret AGI Game Viewer</h1>

        <div class="status info">
            <strong>Status:</strong> <span id="game-status">No active game</span>
        </div>

        <div>
            <button onclick="startGame()">Start New Game (5 Random Players)</button>
            <button onclick="refreshStatus()">Refresh Status</button>
            <button onclick="viewLogs()">View Game Log</button>
        </div>

        <div id="game-info" class="game-state" style="display: none;">
            <h3>Current Game State</h3>
            <div id="game-details"></div>
        </div>

        <div id="game-log" style="display: none;">
            <h3>Game Log</h3>
            <div id="log-entries"></div>
        </div>

        <script>
            let gamePolling = null;

            async function startGame() {
                try {
                    const response = await fetch('/start-game', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ player_count: 5, use_debug: true })
                    });
                    const result = await response.json();

                    if (result.success) {
                        document.getElementById('game-status').textContent = 'Game starting...';
                        startPolling();
                    } else {
                        alert('Failed to start game: ' + result.message);
                    }
                } catch (error) {
                    alert('Error starting game: ' + error.message);
                }
            }

            async function refreshStatus() {
                try {
                    const response = await fetch('/game-state');
                    const result = await response.json();

                    if (result.success && result.data) {
                        displayGameState(result.data);
                    } else {
                        document.getElementById('game-status').textContent = 'No active game';
                        document.getElementById('game-info').style.display = 'none';
                    }
                } catch (error) {
                    console.error('Error refreshing status:', error);
                }
            }

            async function viewLogs() {
                try {
                    const response = await fetch('/game-log');
                    const result = await response.json();

                    if (result.success) {
                        displayGameLog(result.data);
                    }
                } catch (error) {
                    console.error('Error viewing logs:', error);
                }
            }

            function displayGameState(gameData) {
                document.getElementById('game-status').textContent =
                    gameData.completed ? 'Game completed' : 'Game in progress';

                const details = `
                    <p><strong>Game ID:</strong> ${gameData.game_id}</p>
                    <p><strong>Turn:</strong> ${gameData.total_turns}</p>
                    <p><strong>Capability:</strong> ${gameData.final_capability || 'N/A'}</p>
                    <p><strong>Safety:</strong> ${gameData.final_safety || 'N/A'}</p>
                    <p><strong>Winners:</strong> ${gameData.winners ? gameData.winners.join(', ') : 'Game in progress'}</p>
                    <p><strong>Status:</strong> ${gameData.completed ? 'Completed' : 'In progress'}</p>
                `;

                document.getElementById('game-details').innerHTML = details;
                document.getElementById('game-info').style.display = 'block';

                if (gameData.completed && gamePolling) {
                    clearInterval(gamePolling);
                    gamePolling = null;
                }
            }

            function displayGameLog(logData) {
                const logDiv = document.getElementById('log-entries');
                logDiv.innerHTML = '';

                if (logData && logData.length > 0) {
                    // Show all entries, not just last 20
                    logData.forEach(entry => {
                        const logEntry = document.createElement('div');
                        logEntry.className = 'log-entry';

                        // Enhanced display for detailed action logs
                        if (entry.turn !== undefined && entry.turn > 0) {
                            logEntry.innerHTML = `<strong>Turn ${entry.turn}:</strong> ${entry.message}`;
                        } else {
                            logEntry.innerHTML = `<strong>${entry.timestamp || 'Unknown'}:</strong> ${entry.message || JSON.stringify(entry)}`;
                        }

                        // Add special styling for different action types
                        if (entry.message && entry.message.includes('✅')) {
                            logEntry.style.borderLeft = '3px solid #28a745';  // Green for success
                        } else if (entry.message && entry.message.includes('❌')) {
                            logEntry.style.borderLeft = '3px solid #dc3545';  // Red for failure
                        } else if (entry.message && entry.message.includes('📡')) {
                            logEntry.style.borderLeft = '3px solid #ffc107';  // Yellow for events
                            logEntry.style.backgroundColor = '#fff3cd';
                        }

                        logDiv.appendChild(logEntry);
                    });
                } else {
                    logDiv.innerHTML = '<p>No log entries available</p>';
                }

                document.getElementById('game-log').style.display = 'block';

                // Scroll to bottom to show latest entries
                logDiv.scrollTop = logDiv.scrollHeight;
            }

            function startPolling() {
                if (gamePolling) clearInterval(gamePolling);

                gamePolling = setInterval(async () => {
                    await refreshStatus();
                }, 2000);  // Poll every 2 seconds
            }

            // Initial status check
            refreshStatus();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.post("/start-game", response_model=GameResponse)
async def start_game(request: GameRequest):
    """Start a new game."""
    global current_game, current_orchestrator, game_log

    try:
        # Clear previous game
        current_game = {}
        game_log = []

        # Create players (for now, all random)
        players = [
            RandomPlayer(f"player_{i+1}")
            for i in range(request.player_count)
        ]

        # TODO: Allow selection of different agent types when available
        # if hasattr(request, 'agent_types'):
        #     players = create_players_from_types(request.agent_types)

        # Create orchestrator with on-disk database for persistence
        current_orchestrator = SimpleOrchestrator(
            database_url="sqlite:///web_games.db",  # Use on-disk database for web games
            debug_mode=request.use_debug
        )

        # Start game in background
        asyncio.create_task(run_game_background(players))

        return GameResponse(
            success=True,
            message=f"Game started with {request.player_count} players",
            data={"player_count": request.player_count, "debug": request.use_debug}
        )

    except Exception as e:
        logger.error(f"Error starting game: {e}")
        return GameResponse(
            success=False,
            message=f"Failed to start game: {str(e)}"
        )


@app.get("/game-state", response_model=GameResponse)
async def get_game_state():
    """Get current game state."""
    if not current_game:
        return GameResponse(
            success=False,
            message="No active game"
        )

    return GameResponse(
        success=True,
        message="Game state retrieved",
        data=current_game
    )


@app.get("/game-log", response_model=GameResponse)
async def get_game_log():
    """Get detailed game log entries from database."""
    try:
        # Try to get game_id from multiple sources
        game_id = None

        # Try to get from current_game first
        if current_game and "game_id" in current_game:
            game_id = current_game["game_id"]
            logger.info(f"Got game_id from current_game: {game_id}")
        # Try to get from orchestrator as fallback
        elif current_orchestrator and current_orchestrator.current_game_id:
            game_id = current_orchestrator.current_game_id
            logger.info(f"Got game_id from orchestrator: {game_id}")

        if not game_id:
            # Try to get the most recent game from the database as fallback
            try:
                from sqlalchemy import text
                from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

                from ..database.operations import GameOperations

                # Create a direct database connection for web games
                web_engine = create_async_engine("sqlite+aiosqlite:///web_games.db")

                async with AsyncSession(web_engine) as session:
                    # Query for the most recent game
                    result = await session.execute(
                        text("SELECT id FROM games ORDER BY created_at DESC LIMIT 1")
                    )
                    row = result.fetchone()
                    if row:
                        game_id = row[0]
                        logger.info(f"Found most recent game from database: {game_id}")
                    else:
                        logger.warning("No games found in database")

                # Clean up the temporary engine
                await web_engine.dispose()

            except Exception as e:
                logger.error(f"Error querying database for recent game: {e}")

            if not game_id:
                # Still no game ID available - return simple log as fallback
                logger.warning("No game_id found anywhere, using fallback log")
                return GameResponse(
                    success=True,
                    message="Game log retrieved (fallback)",
                    game_id=None,
                    data=game_log if game_log else []
                )

        # Access database through the orchestrator's engine if available, or direct connection
        actions = []
        events = []

        if current_orchestrator and current_orchestrator.engine:
            # Use orchestrator's engine - but GameEngine doesn't expose internal SQLAlchemy engine
            # So we'll fall back to direct connection approach for now
            logger.info("Orchestrator engine available, but using direct connection for compatibility")
            try:
                from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

                from ..database.operations import GameOperations

                # Create a direct database connection for web games
                web_engine = create_async_engine("sqlite+aiosqlite:///web_games.db")

                async with AsyncSession(web_engine) as session:
                    actions = await GameOperations.get_actions_for_game(session, game_id)
                    events = await GameOperations.get_events_for_game(session, game_id)

                    logger.info(f"Retrieved {len(actions)} actions and {len(events)} events from direct connection via orchestrator path for game {game_id}")

                # Clean up the temporary engine
                await web_engine.dispose()

            except Exception as e:
                logger.error(f"Error accessing database via orchestrator path: {e}")
                actions = []
                events = []
        else:
            # Fallback to direct database connection
            try:
                from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

                from ..database.operations import GameOperations

                # Create a direct database connection for web games
                web_engine = create_async_engine("sqlite+aiosqlite:///web_games.db")

                async with AsyncSession(web_engine) as session:
                    actions = await GameOperations.get_actions_for_game(session, game_id)
                    events = await GameOperations.get_events_for_game(session, game_id)

                    logger.info(f"Retrieved {len(actions)} actions and {len(events)} events from direct database connection for game {game_id}")

                # Clean up the temporary engine
                await web_engine.dispose()

            except Exception as e:
                logger.error(f"Error accessing database directly: {e}")
                actions = []
                events = []

        # Create detailed log entries
        detailed_log = []

        # Add game start
        detailed_log.append({
            "timestamp": "start",
            "turn": 0,
            "message": f"Game started with {len(current_game.get('player_ids', []))} players"
        })

        # Combine and sort actions and events by turn number
        all_entries = []

        # Add action entries
        for action in actions:
            status = "✅" if action.is_valid else "❌" if not action.is_valid else "⏳"
            message = f"{status} {action.player_id} → {action.action_type}"

            if action.action_data:
                # Add relevant action data
                if action.action_type == "nominate":
                    message += f" (target: {action.action_data.get('target_id', 'unknown')})"
                elif action.action_type in ["vote_team", "vote_emergency"]:
                    message += f" ({'YES' if action.action_data.get('vote') else 'NO'})"
                elif action.action_type in ["discard_paper", "publish_paper"]:
                    message += f" (paper: {action.action_data.get('paper_id', 'unknown')})"
                elif action.action_type == "use_power":
                    message += f" (target: {action.action_data.get('target_id', 'unknown')})"
                elif action.action_type == "declare_veto":
                    message += " (veto declared)"
                elif action.action_type == "respond_veto":
                    response = "AGREE" if action.action_data.get('agree') else "REFUSE"
                    message += f" ({response})"

            if action.error_message:
                message += f" - ERROR: {action.error_message}"

            all_entries.append({
                "timestamp": f"turn_{action.turn_number}",
                "turn": action.turn_number,
                "message": message,
                "player": action.player_id,
                "action": action.action_type,
                "valid": action.is_valid,
                "type": "action"
            })

        # Add significant events
        for event in events:
            if event.event_type in ["paper_published", "power_triggered", "game_ended", "player_eliminated"]:
                message = f"📡 {event.event_type.replace('_', ' ').title()}"

                if event.event_data:
                    if event.event_type == "paper_published":
                        paper = event.event_data.get('paper', {})
                        message += f" - Paper: C+{paper.get('capability', 0)}, S+{paper.get('safety', 0)}"
                    elif event.event_type == "power_triggered":
                        message += f" - {event.event_data.get('power_type', 'unknown')} power activated"
                    elif event.event_type == "game_ended":
                        winners = event.event_data.get('winners', [])
                        message += f" - Winners: {', '.join(winners)}"
                    elif event.event_type == "player_eliminated":
                        message += f" - {event.event_data.get('target_id', 'unknown')} eliminated"

                all_entries.append({
                    "timestamp": f"turn_{event.turn_number}",
                    "turn": event.turn_number,
                    "message": message,
                    "event_type": event.event_type,
                    "type": "event"
                })

        # Sort by turn number, then by type (actions before events)
        all_entries.sort(key=lambda x: (x.get('turn', 0), x.get('type') == 'event'))

        # Add to detailed log
        detailed_log.extend(all_entries)

        return GameResponse(
            success=True,
            message="Detailed game log retrieved",
            data=detailed_log
        )

    except Exception as e:
        logger.error(f"Error retrieving detailed game log: {e}")
        # Fallback to simple log
        return GameResponse(
            success=True,
            message="Game log retrieved (fallback)",
            data=game_log
        )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Secret AGI API is running"}


async def run_game_background(players):
    """Run a game in the background and update global state."""
    global current_game, game_log

    try:
        # Log game start
        game_log.append({
            "timestamp": "start",
            "message": f"Game started with {len(players)} players"
        })

        # Run the game
        result = await current_orchestrator.run_game(players)

        # Update global state with final result including game_id
        current_game.update(result)

        # Capture game_id from orchestrator if available
        if hasattr(current_orchestrator, '_game_id') and current_orchestrator._game_id:
            current_game["game_id"] = current_orchestrator._game_id
            current_game["player_ids"] = [p.player_id for p in players]

        # Log game end
        game_log.append({
            "timestamp": "end",
            "message": f"Game completed. Winners: {result.get('winners', 'Unknown')}"
        })

        logger.info(f"Background game completed: {result}")

    except Exception as e:
        logger.error(f"Background game failed: {e}")
        current_game["error"] = str(e)
        game_log.append({
            "timestamp": "error",
            "message": f"Game failed: {str(e)}"
        })


if __name__ == "__main__":
    import uvicorn

    # Set up logging
    logging.basicConfig(level=logging.INFO)

    print("🚀 Starting Secret AGI Game Viewer API")
    print("   Open http://localhost:8000 in your browser")
    print("   API docs at http://localhost:8000/docs")

    uvicorn.run(app, host="0.0.0.0", port=8000)
