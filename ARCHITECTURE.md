# Secret AGI Multi-Agent System Architecture

## Project Overview

A multi-agent game system where AI agents play Secret AGI, a social deduction game. The system enables controlled experiments with different agent architectures through automated gameplay, comprehensive data collection, and performance analysis.

## Technology Stack

- **Language**: Python
- **Web Framework**: FastAPI (REST API and optional WebSocket support)
- **Database**: SQLite with SQLModel ORM (https://sqlmodel.tiangolo.com)
- **Frontend**: Pure HTML/CSS with vanilla JavaScript (no React or other frameworks)
- **Agent Framework**: ADK (https://google.github.io/adk-docs/) for agent implementation
- **Monitoring**: Langfuse for agent performance tracking and observability
- **LLM Configuration**: Managed through ADK framework

## Architectural Principles

1. **Single Process, Multiple Agents**: All agents run within the same Python process but maintain separate ADK sessions for true independence
2. **Sequential Game Execution**: No concurrent games - simplifies state management and debugging
3. **Central Orchestration**: A central orchestrator manages turn coordination between independent agents
4. **Event Sourcing**: Complete state snapshots after each action enable branching and replay functionality
5. **Tool-Based Agent Interface**: Agents interact exclusively through ADK tools for clean abstraction

## System Components

### 1. Game Engine Service

**Purpose**: Implements core Secret AGI game logic and maintains authoritative game state

**Modules**:
- **Game Manager**: Handles game lifecycle operations (create, load, save, delete games)
- **State Machine**: Manages game phases (Team Proposal, Research, etc.) and validates transitions
- **Action Validator**: Ensures all agent actions comply with current game rules and state
- **Event System**: Records and distributes all game events to interested parties
- **State Versioning**: Creates complete state snapshots after each action for replay/branching

**Responsibilities**:
- Process agent actions and return comprehensive state updates
- Detect win conditions and game endings
- Manage paper deck, board state, and player eliminations
- Handle special powers and emergency safety mechanics
- Track both valid and invalid action attempts for analysis

### 2. Agent Orchestrator Service

**Purpose**: Coordinates independent ADK agents and manages game flow

**Modules**:
- **Turn Manager**: Determines which agent(s) should act based on game phase
- **Agent Registry**: Maps player IDs to agent instances and tracks agent metadata
- **Action Dispatcher**: Routes agent tool calls to game engine and returns responses
- **Context Builder**: Prepares role-appropriate game views for each agent
- **Timeout Handler**: Manages agent response timeouts with graceful fallbacks

**Responsibilities**:
- Sequential agent activation based on game state
- Build appropriate information views (public vs private info)
- Handle agent failures without blocking game progress
- Maintain agent session lifecycle

### 3. Agent Framework

**Purpose**: Provides standardized interface for diverse agent implementations

**Components**:
- **Base Agent Class**: Abstract interface defining required agent methods
- **ADK Session Manager**: Creates and maintains separate ADK sessions per agent
- **State Persistence**: Allows agents to maintain memory across turns
- **Tool Interface**: Standardized ADK tools for all game actions

**Available Agent Tools**:
- `nominate(player_id)` - Director nominates Engineer
- `vote_team(yes/no)` - Vote on proposed team
- `vote_emergency(yes/no)` - Vote on Emergency Safety
- `call_emergency_safety()` - Initiate Emergency Safety vote
- `discard_paper(paper_id)` - Director discards from drawn papers
- `publish_paper(paper_id)` - Engineer publishes selected paper
- `declare_veto()` - Engineer declares veto
- `respond_veto(agree/disagree)` - Director responds to veto
- `use_power(target_id)` - Execute power on target
- `send_chat_message(text)` - Send message during chat phase
- `observe()` - Get updates without taking action

**Agent Implementation Notes**:
- Agents are defined in code with their prompts and strategies
- Each agent type is registered with the orchestrator at startup
- Agents can implement custom memory systems and decision logic
- All agents receive role assignment and known allies at game start

### 4. Storage Layer (SQLModel + SQLite)

**Purpose**: Persistent storage for all game data, enabling replay and analysis

**Database Schema**:

**Games Table**:
- Game configuration and metadata
- Start/end timestamps
- Final outcome and winners

**GameStates Table**:
- Complete game state JSON snapshots
- Indexed by game_id and turn_number
- Enables branching from any point

**Players Table**:
- Player-agent assignments
- Roles (Safety/Accelerationist/AGI)
- Agent architecture type

**Actions Table**:
- Complete action history
- Validation results and error messages
- Response times and token usage

**Events Table**:
- All game events in sequence
- Event types and associated data
- Timestamps for replay accuracy

**ChatMessages Table**:
- Chat phase communications
- Speaker identification
- Message timing

**Metrics Table**:
- Performance data per agent per turn
- Token usage, response times
- Invalid action attempts

### 5. Web API (FastAPI)

**Purpose**: RESTful API for UI and external control

**Endpoint Categories**:

**Game Management**:
- `POST /games` - Create new game with configuration
- `GET /games/{id}` - Get game state and metadata
- `DELETE /games/{id}` - Remove game from system
- `POST /games/{id}/branch` - Create branch from historical state

**Game Control**:
- `POST /games/{id}/start` - Begin game execution
- `POST /games/{id}/pause` - Pause game execution
- `POST /games/{id}/resume` - Resume paused game

**Monitoring**:
- `GET /games/{id}/state` - Current game state
- `GET /games/{id}/events?since={turn}` - Event stream
- `GET /games/{id}/metrics` - Performance metrics
- `WS /ws/games/{id}` - WebSocket for real-time updates (if implemented)

**Analytics**:
- `GET /analytics/agents` - Agent performance statistics
- `GET /analytics/games` - Game outcome analysis
- `GET /analytics/strategies` - Strategy effectiveness

**History**:
- `GET /games` - List all games with filtering
- `GET /games/{id}/history` - Complete game history
- `GET /games/{id}/replay` - Replay data for UI

### 6. Web UI (HTML/CSS/JavaScript)

**Purpose**: Browser-based interface for monitoring and control

**Pages**:

**Dashboard** (`/`):
- Active game status
- Quick statistics
- New game launcher
- Recent game history

**Game Viewer** (`/game/{id}`):
- Real-time board state visualization
- Capability and Safety meters
- Current phase and active player
- Action history log
- Chat message display
- Player role indicators (for debug mode)

**History Browser** (`/history`):
- Searchable game archive
- Filters by outcome, agents, configuration
- Game replay controls
- Branch creation interface

**Analytics** (`/analytics`):
- Agent win rates by role
- Strategy effectiveness charts
- Resource usage graphs
- Invalid action patterns

**Debug Panel** (`/debug`):
- Direct state inspection
- Manual action injection
- Agent internal state viewer
- System performance metrics

**Technical Notes**:
- Vanilla JavaScript for interactivity
- Periodic polling for updates (MVP approach)
- Clean, responsive CSS design
- No build process required

### 7. Monitoring Integration (Langfuse)

**Purpose**: Comprehensive observability for agent behavior and system performance

**Trace Hierarchy**:
- **Game Session** (root span): Entire game from start to finish
- **Game Turn** (child span): Each complete turn cycle
- **Agent Decision** (child span): Individual agent action processing
- **Tool Call** (child span): Specific ADK tool invocations

**Tracked Metrics**:
- Agent response times per action
- Token usage per decision
- Invalid action attempt patterns
- Strategy effectiveness indicators
- Chat message impact on outcomes

**Integration Points**:
- Orchestrator logs agent activations
- Agent framework tracks tool usage
- Game engine records action processing
- Automatic correlation by game_id

## Data Flow Patterns

### Game Initialization Flow
1. API receives game configuration request
2. Game Manager creates new game instance
3. Agent Orchestrator instantiates configured agents with separate ADK sessions
4. Initial role assignments distributed to agents
5. Game state snapshot saved to database
6. Game ID returned to caller

### Turn Execution Flow
1. Orchestrator checks game state for active player(s)
2. Context Builder prepares appropriate view for agent
3. Agent receives game state through observe() tool
4. Agent decides and calls appropriate action tool
5. Orchestrator forwards action to Game Engine
6. Game Engine validates and processes action
7. New state snapshot saved to database
8. Events generated and logged
9. All agents notified of state changes
10. UI updated through API

### Branching/Replay Flow
1. User selects historical game state to branch from
2. System loads complete state from GameStates table
3. New game created with loaded state as initial state
4. User can specify different agents for players
5. Game continues from branch point with new game_id
6. Original game remains unchanged

## Error Handling Strategy

### Agent Failures
- Configurable timeout per agent action (default: 30 seconds)
- Automatic retry with exponential backoff
- Fallback to random valid action after retries exhausted
- Game continues without blocking

### Invalid Actions
- Game Engine returns clear error messages
- Invalid attempts logged for analysis
- Agent receives error in tool response
- No state change occurs

### System Recovery
- Database transactions ensure state consistency
- Automatic checkpoint after each action
- Recovery loads latest valid state
- No partial state updates possible

## Extension Points

### Adding New Agent Types
1. Implement base agent class interface
2. Define agent-specific prompts and strategies
3. Register agent type with orchestrator
4. Agent automatically available for games

### Custom Analysis Modules
1. Query database for historical data
2. Implement analysis logic
3. Expose results through new API endpoints
4. Add visualization to UI

### Game Rule Variants
1. Modify game engine validation logic
2. Update state machine for new phases
3. Extend agent tools if needed
4. No changes required to orchestration layer

## Development Workflow

### Local Development Setup
1. SQLite database created automatically on first run
2. Agents defined and registered in Python code
3. FastAPI development server with auto-reload
4. Static file serving for UI assets

### Testing Strategy
1. Unit tests for game engine logic
2. Integration tests for agent-engine interaction
3. Database state verification tests
4. UI interaction tests with game API

### Deployment Considerations
1. Single Python process simplifies deployment
2. SQLite database file for easy backup
3. No external service dependencies
4. Configurable through environment variables

## Performance Characteristics

### Scalability Limits
- Sequential game processing (by design)
- Single SQLite file (sufficient for research use)
- No distributed system complexity
- Focus on correctness over throughput

### Optimization Opportunities
- Batch database writes per turn
- Lazy loading of historical states
- Agent response caching (if deterministic)
- UI polling interval adjustment

This architecture prioritizes simplicity, correctness, and research flexibility over high-performance production concerns. The single-process design with SQLite storage is ideal for controlled experiments and analysis of agent behaviors.