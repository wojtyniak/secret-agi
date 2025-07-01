# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Secret AGI is a multi-agent game system where AI agents play a social deduction game. The system is designed for controlled experiments comparing different agent architectures through automated gameplay and comprehensive performance analysis.

## Technology Stack

- **Language**: Python 3.13+
- **Package Management**: uv (modern Python package manager)
- **Web Framework**: FastAPI (for REST API and WebSocket support)
- **Database**: SQLite with SQLModel ORM
- **Frontend**: Pure HTML/CSS with vanilla JavaScript
- **Agent Framework**: ADK (Agent Development Kit) for agent implementation
- **Monitoring**: Langfuse for agent performance tracking

## Development Commands

```bash
# Install dependencies
uv sync

# Run the application
uv run python main.py

# Run with development server (when FastAPI is implemented)
uv run uvicorn main:app --reload

# Run tests (when test suite is implemented)
uv run pytest

# Type checking (when mypy is configured)
uv run mypy .

# Formatting (when configured)
uv run ruff format .
uv run ruff check .
```

## Architecture Overview

### Core Components

1. **Game Engine Service**: Implements Secret AGI game logic and maintains authoritative game state
2. **Agent Orchestrator Service**: Coordinates independent ADK agents and manages game flow
3. **Agent Framework**: Provides standardized interface for diverse agent implementations
4. **Storage Layer**: SQLite database for game data persistence and replay functionality
5. **Web API**: FastAPI-based REST API for UI and external control
6. **Web UI**: Browser-based interface for monitoring and control

### Key Design Principles

- **Single Process, Multiple Agents**: All agents run within the same Python process with separate ADK sessions
- **Sequential Game Execution**: No concurrent games - simplifies state management
- **Event Sourcing**: Complete state snapshots after each action for replay/branching
- **Tool-Based Agent Interface**: Agents interact exclusively through ADK tools

## Game Rules Implementation

The game follows the complete rules defined in `SECRET_AGI_RULES.md`:
- 5-10 player social deduction game
- Safety Researchers vs Accelerationists vs AGI
- Research phases with paper publishing mechanics
- Powers, veto system, and emergency safety mechanics
- Multiple win conditions based on Capability/Safety metrics

## Agent Tools Interface

Agents interact through these standardized tools:
- `nominate(player_id)` - Director nominates Engineer
- `vote_team(yes/no)` - Vote on proposed team
- `vote_emergency(yes/no)` - Vote on Emergency Safety
- `call_emergency_safety()` - Initiate Emergency Safety vote
- `discard_paper(paper_id)` - Director discards papers
- `publish_paper(paper_id)` - Engineer publishes papers
- `declare_veto()` - Engineer declares veto
- `respond_veto(agree/disagree)` - Director responds to veto
- `use_power(target_id)` - Execute power on target
- `send_chat_message(text)` - Send chat messages
- `observe()` - Get updates without action

## Data Flow

1. **Game Initialization**: API creates game → Agent Orchestrator instantiates agents → Role assignments
2. **Turn Execution**: Context building → Agent decision → Action validation → State update → Event logging
3. **Branching/Replay**: Load historical state → Create new game → Continue from branch point

## Database Schema

Key tables include:
- `Games`: Game configuration and metadata
- `GameStates`: Complete state snapshots for replay
- `Players`: Player-agent assignments and roles
- `Actions`: Complete action history with validation
- `Events`: Sequential game events
- `ChatMessages`: Chat communications
- `Metrics`: Performance data per agent per turn

## Error Handling

- **Agent Failures**: Configurable timeouts, retry with backoff, fallback to random valid actions
- **Invalid Actions**: Clear error messages, logged for analysis, no state changes
- **System Recovery**: Database transactions, automatic checkpoints, recovery from latest valid state

## Extension Points

- **New Agent Types**: Implement base agent interface → Register with orchestrator
- **Custom Analysis**: Query database → Implement analysis logic → Expose via API
- **Game Variants**: Modify game engine validation → Update state machine → Extend tools if needed