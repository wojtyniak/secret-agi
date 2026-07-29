# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Secret AGI is a multi-agent game system where AI agents play a social deduction game. The system is designed for controlled experiments comparing different agent architectures through automated gameplay and comprehensive performance analysis.

## Project Documentation
@SECRET_AGI_RULES.md - Game Rules
@PRD.md - Project Requirements Document
@ARCHITECTURE.md - Technical Architecture Overview

## Other File
@JOURNAL.md - This is a journal for Claude Code for any notes, learnings, or thoughts. Update it as you work on the project.


## Technology Stack

- **Language**: Python 3.13+
- **Package Management**: uv (modern Python package manager)
- **Web Framework**: FastAPI (for REST API and WebSocket support)
- **Database**: SQLite with SQLModel ORM
- **Frontend**: Pure HTML/CSS with vanilla JavaScript
- **Agent Framework**: ADK (Agent Development Kit) for agent implementation
- **Monitoring**: Langfuse for agent performance tracking

## Development Commands

**Primary Commands (using Just):**
```bash
# See all available commands
just

# Core quality commands
just lint      # Run ruff linting  
just typecheck # Run mypy type checking
just test      # Run unit tests

# Combined quality checks
just check     # Run lint + typecheck + test
just quality   # Format + check everything

# Code formatting
just fmt       # Format code with ruff
just fix       # Auto-fix linting issues

# Database migrations
just db-migration "message"  # Create new migration
just db-upgrade             # Apply pending migrations  
just db-status              # Show migration status
just db-history             # Show migration history
just db-reset               # Reset database
```

**Manual Commands (fallback):**
```bash
# Install dependencies
uv sync --dev

# Run tests
uv run pytest

# Run specific test files
uv run pytest tests/test_models.py -v

# Run game completeness validation
uv run python test_completeness.py

# Test random game completion with different player counts  
uv run python -c "import asyncio; from secret_agi.engine.game_engine import run_random_game; print(asyncio.run(run_random_game(5, database_url='sqlite:///:memory:')))"

# Type checking (strict mypy - 0 errors)
uv run mypy .

# Linting and formatting
uv run ruff check .
uv run ruff format .

# All quality checks together
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
```

## Architecture Overview

### Core Components

1. **Game Engine**: ✅ **DONE** - Secret AGI rules + authoritative game state (do not rewrite)
2. **Storage Layer**: ✅ **DONE** - SQLite/SQLModel with Alembic migrations, snapshots, replay
3. **Player Framework**: ✅ **DONE (M0)** - async `BasePlayer`, `RandomPlayer` baseline
4. **Provider Layer**: ⏳ **M1** - `ModelAdapter` protocol + OpenAI / Anthropic / Mock adapters
5. **Match Runner + CLI**: ⏳ **M3** - seeded balanced schedules, concurrency, cost caps
6. **Analysis Layer**: ⏳ **M2** - belief probes, LLM-judge labeling, scorecards with CIs

### Key Design Principles

- **Async-Only Architecture**: Single async GameEngine with mandatory database persistence
- **Concurrent Games**: the engine is instance-scoped; the match runner runs games in parallel behind a configured limit
- **Event Sourcing**: Complete state snapshots after each action for replay/branching
- **Tool-Based Agent Interface**: Agents interact exclusively through async tools
- **Database-First Design**: All operations persist to SQLite with automatic migrations

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

- **New Agent Types**: Implement the async `BasePlayer` interface → reference it from a run config
- **Custom Analysis**: Query database → Implement analysis logic → Expose via API
- **Game Variants**: Modify game engine validation → Update state machine → Extend tools if needed

## Development Rules

- KISS - Keep It Simple Stupid
- YAGNI - You Aren't Gonna Need It
- DRY - Don't Repeat Yourself

## Current Implementation Status

*Authoritative scope: `IMPLEMENTATION_BRIEF.md` (+ `EVAL_PLAN.md`, `ROADMAP.md`). Where
this file conflicts with the brief, the brief wins.*

The project is being turned into **Secret AGI Bench**: an eval harness where LLM agents
play Secret AGI, producing per-model scorecards for cooperation under mutual opacity and
deception propensity vs capability.

### ✅ Done — engine + database (kept as-is)
- **Async Game Engine**: single async `GameEngine` with mandatory database persistence
- **Core Game Logic**: complete Secret AGI rules — powers, veto, emergency safety, win conditions
- **Information Filtering**: per-player filtered `GameState` / event views in `engine/events.py`
- **Storage Layer**: SQLModel/SQLite with Alembic migrations, per-turn state snapshots,
  full action/event history, replay + branching, interrupted-game recovery

### ✅ Done — M0 (modernize base)
- **Async player interface**: `choose_action` and the lifecycle hooks are `async`
- **Scrapped scaffolding**: `orchestrator/`, `api/` (FastAPI + embedded HTML viewer),
  `test_your_agents.py`, `launch_web_viewer.py`, `players/agent_template.py` and their tests
- **Clean quality gate**: ruff clean, mypy 0 errors outside the database exemption,
  194 tests passing
- **CI**: GitHub Actions running uv + ruff + mypy + pytest
- **Dependencies**: `openai`, `anthropic`, `pyyaml`, `typer` added; FastAPI removed;
  lockfile refreshed; `__pycache__` untracked

### ⏳ Remaining (M1–M3, per ROADMAP §1.4)
- **M1** — provider layer (`ModelAdapter` + OpenAI/Anthropic/Mock adapters), `LLMPlayer`,
  chat discussion sub-phases, versioned prompts
- **M2** — metrics wiring, belief probes, LLM-judge pipeline, scorecards with bootstrap CIs
- **M3** — concurrent games, resumability, cost caps, seeded seat/role-balanced schedules, CLI

### 📂 Current layout
```
secret_agi/
├── engine/                 # rules, actions, events, async GameEngine  (do not rewrite)
├── database/               # SQLModel tables, operations, connection, unit of work
├── players/                # async BasePlayer, RandomPlayer (baseline), HumanPlayer
├── settings.py             # centralized configuration
tests/                      # unit, scenario, integration and edge-case suites
alembic/                    # database migrations
```

### 🚫 Out of scope for this pass
- Any web UI (the replay viewer and leaderboard site are M4)
- Rewriting the rules engine
- Deception hints in player prompts — system prompts say "play to win", never "deceive"

## Development Memories

- Don't add yourself (Claude) to commit messages or as a co-author.
- I feel we're complicating our life by adding new features before all tests are passing. Make sure all tests are passing after every time you make changes
- **IMPORTANT**: on the remote execution environment jj is not installed — use git there. Locally this is a jj repository.
- Don't remove documentation files unless prompted to
- Always write commit message after making changes if it's empty