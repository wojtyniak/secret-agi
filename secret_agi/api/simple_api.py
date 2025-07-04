"""
Simple FastAPI backend for Secret AGI web game viewing.

This provides minimal endpoints for creating and monitoring games
without complex real-time features.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..orchestrator import SimpleOrchestrator
from ..players.random_player import RandomPlayer
# TODO: Import your agents here when available
# from ..players.your_agent import YourAgent

logger = logging.getLogger(__name__)

# Global game state
current_game: Dict[str, Any] = {}
current_orchestrator: Optional[SimpleOrchestrator] = None
game_log: List[Dict[str, Any]] = []


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
    game_id: Optional[str] = None
    data: Optional[Any] = None  # Changed from Dict to Any to allow lists


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
            .log-entry { margin: 5px 0; padding: 5px; background: #fff; border-left: 3px solid #007bff; }
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
                    logData.slice(-20).forEach(entry => {  // Show last 20 entries
                        const logEntry = document.createElement('div');
                        logEntry.className = 'log-entry';
                        logEntry.innerHTML = `<strong>${entry.timestamp || 'Unknown'}:</strong> ${entry.message || JSON.stringify(entry)}`;
                        logDiv.appendChild(logEntry);
                    });
                } else {
                    logDiv.innerHTML = '<p>No log entries available</p>';
                }
                
                document.getElementById('game-log').style.display = 'block';
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
        
        # Create orchestrator
        current_orchestrator = SimpleOrchestrator(
            database_url="sqlite:///:memory:",  # Use in-memory for web games
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
    """Get game log entries."""
    return GameResponse(
        success=True,
        message="Game log retrieved",
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
        
        # Update global state with final result
        current_game.update(result)
        
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