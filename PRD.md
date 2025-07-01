# Product Requirements Document: Secret AGI Multi-Agent System

## 1. Overview

### 1.1 Purpose
A multi-agent game system where AI agents play Secret AGI, a social deduction game. The system enables controlled experiments to compare different agent architectures, strategies, and configurations through automated gameplay and comprehensive performance analysis.

### 1.2 Scope
The system encompasses game management, agent orchestration, communication infrastructure, data collection, storage, visualization, and statistical analysis for evaluating agent performance across multiple game sessions.

## 2. System Components

### 2.1 Game Engine

#### 2.1.1 Core Responsibilities
- Initialize games with configurable player counts (5-10 players)
- Manage complete game state including board positions, player roles, and deck state
- Process agent actions and return comprehensive updates
- Distribute appropriate game state views to each player
- Detect and announce game end conditions
- Handle all game phases: Team Proposal, Research, and special events
- Track and validate all action attempts (including invalid ones)

#### 2.1.2 Game State Management
**Required State Elements:**
- Player roster with role assignments (Safety/Accelerationist/AGI)
- Board state (Capability and Safety metrics)
- Paper deck and discard pile
- Current phase and sub-phase
- Active player (Director/Engineer)
- Failed proposal counter
- Power activation states and history
- Veto unlock status
- Emergency Safety activation status
- Player elimination status
- Complete action history (valid and invalid attempts)

**State Distribution Requirements:**
- Initial state includes player's own role and known allies (for Accelerationists/AGI)
- Each action response includes all events since last agent action
- Private information (viewed allegiances, drawn papers) included only for authorized agents

#### 2.1.3 Action Processing
**Tool-Based Actions:**
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

**Validation Requirements:**
- Track all action attempts (valid and invalid)
- Return clear error messages for invalid actions
- Count invalid attempts for performance metrics
- Continue game flow despite invalid attempts

### 2.2 Agent System

#### 2.2.1 Agent Architecture
**Tool-Based Interface:**
Agents interact through tool calls that:
- Submit an action to the game engine
- Block until game engine processes and returns
- Receive comprehensive update of all events since last call

**Required Agent Capabilities:**
- Process initial game setup (role, known allies)
- Call appropriate tools based on game state
- Handle action responses and errors
- Participate in chat phases
- Maintain internal state across turns

#### 2.2.2 Agent Tools
Each tool returns a response containing:
- Success/failure status
- Error message if applicable
- Complete game state update
- All events since last agent action
- Current valid actions for the agent

#### 2.2.3 Agent Flexibility
- Agents may implement any internal architecture
- Support for memory systems beyond single game
- Ability to spawn sub-agents or use internal tools
- Custom decision-making logic and strategies

### 2.3 Communication System

#### 2.3.1 Chat Room Requirements
**Functionality:**
- Pre-action discussion phases
- Limited speaking turns per phase
- Configurable speaker selection (random/round-robin)
- All messages visible to all living players
- No chat during action phases

**Chat Phase Flow:**
1. Chat phase begins before each action round
2. System selects speakers based on configuration
3. Selected agent uses `send_chat_message(text)`
4. All agents receive chat updates in their next tool response
5. Phase ends after turn limit reached

### 2.4 Data Collection System

#### 2.4.1 Per-Turn Metrics
**Performance Tracking:**
- Agent identifier and architecture type
- Action attempted and validation result
- Invalid action attempts (count and types)
- Tokens used for decision
- Response time
- Internal state size (if provided)

#### 2.4.2 Per-Game Metrics
**Game Configuration:**
- Game ID and timestamp
- Player count and role distribution
- Agent architecture mappings
- Initial random seed

**Behavioral Metrics:**
- Complete action history with timestamps
- Invalid action attempt patterns
- Chat message logs and effectiveness
- Vote correlations and patterns
- Power usage decisions
- Game length (turns and wall time)

#### 2.4.3 Cross-Game Analytics
- Win rates by role and agent architecture
- Invalid action rates by agent type
- Resource usage patterns
- Strategy effectiveness metrics
- Architecture performance rankings

### 2.5 Storage System

#### 2.5.1 Game State Persistence
**Requirements:**
- Store complete game state after each action
- Include agent internal states when provided
- Support for state reconstruction at any point
- Enable branching from historical states

#### 2.5.2 Storage Capabilities
- Save/load game at any action point
- Replay games with same or different agents
- Branch from any decision point
- Export/import game histories
- Efficient storage of repeated simulations

### 2.6 User Interface

#### 2.6.1 Live Game Viewer
**Features:**
- Real-time game state visualization
- Board state (Capability/Safety meters)
- Current roles and relationships
- Action history log
- Chat message display
- Current phase and active player

#### 2.6.2 Agent Inspector
**Capabilities:**
- View agent's internal reasoning (if exposed)
- Token usage per action
- Response time graphs
- Decision tree visualization
- Invalid action attempts highlighted

#### 2.6.3 History Browser
**Functions:**
- Browse completed games
- Filter by agent types, outcomes, configurations
- Step through game history
- Compare parallel game branches
- Export game data

#### 2.6.4 Debug Panel
**Tools:**
- Pause/resume game execution
- Step-by-step action processing
- Force specific game states
- Inject test scenarios
- Monitor system performance

### 2.7 Simulation Engine

#### 2.7.1 Configuration Options
**Game Setup:**
- Number of games to run
- Agent architecture assignments
- Role assignment methods (random/forced/balanced)
- Repeat counts for same configuration
- Branching scenarios from saved states

**Execution Control:**
- Sequential or parallel game execution
- Checkpoint frequency
- Retry policies for failures
- Logging verbosity levels

#### 2.7.2 Execution Requirements
- Queue and manage multiple game instances
- Save checkpoints for recovery
- Collect all metrics during execution
- Support pause/resume of simulations
- Progress monitoring and estimation

### 2.8 Analysis Engine

#### 2.8.1 Statistical Reports
**Core Metrics:**
- Win rates by agent architecture and role
- Invalid action rates and patterns
- Resource usage (tokens, time) by game phase
- Strategy success rates
- Communication effectiveness

**Comparative Analysis:**
- Statistical significance testing
- Architecture performance rankings
- Role-specific effectiveness
- Error pattern analysis

#### 2.8.2 Output Formats
- Interactive dashboards
- Statistical summary reports
- Raw data exports (JSON/CSV)
- Visualization-ready datasets

## 3. System Interfaces

### 3.1 Agent Tool Interface
```
# Game Actions
nominate(player_id) -> GameUpdate
vote_team(vote: bool) -> GameUpdate
vote_emergency(vote: bool) -> GameUpdate
call_emergency_safety() -> GameUpdate
discard_paper(paper_id) -> GameUpdate
publish_paper(paper_id) -> GameUpdate
declare_veto() -> GameUpdate
respond_veto(agree: bool) -> GameUpdate
use_power(target_id) -> GameUpdate

# Communication
send_chat_message(message: str) -> GameUpdate

# Observation
observe() -> GameUpdate

# GameUpdate structure:
{
  success: bool,
  error: str | null,
  events: [Event],  // Everything since last action
  game_state: GameState,
  valid_actions: [ActionType],
  chat_messages: [ChatMessage]
}
```

### 3.2 Game Management Interface
```
# Game Control
create_game(config) -> game_id
load_game(save_id, branch_point) -> game_id
save_game(game_id) -> save_id
delete_game(game_id) -> success

# Agent Registration
register_agent(game_id, agent_config) -> player_id
```

### 3.3 UI Interface
```
# Live Monitoring
get_active_games() -> [game_summary]
subscribe_to_game(game_id) -> event_stream
get_agent_internals(game_id, player_id) -> agent_state

# History
search_games(filters) -> [game_summary]
load_game_history(game_id) -> complete_history
export_game_data(game_id, format) -> data
```

## 4. Data Schemas

### 4.1 Game Event Types
- ActionAttempted (player, action, valid, error)
- StateChanged (old_state, new_state, trigger)
- ChatMessage (speaker, message, turn)
- PhaseTransition (from_phase, to_phase)
- GameEnded (outcome, winners)

### 4.2 Metrics Schema
- AgentMetrics (tokens, time, invalid_attempts)
- GameMetrics (length, phases, outcome)
- StrategyMetrics (action_patterns, success_rates)

## 5. Error Handling

### 5.1 Agent Failures
- Invalid actions: Log attempt, return error, continue game
- Connection issues: Retry with backoff
- Crash/timeout: Log, attempt recovery, mark agent as failed
- No blocking on agent responses

### 5.2 System Recovery
- Automatic checkpoint saves
- Recovery from last checkpoint on crash
- Transaction logs for state reconstruction
- No data loss for completed actions

## 6. Extensibility Considerations

### 6.1 Agent Architecture Support
- Plugin system for new agent types
- Flexible internal architectures
- Custom tool integration for agents
- Support for agent evolution across games

### 6.2 Analysis Extensions
- Custom metric definitions
- Pluggable analysis modules
- Real-time metric streaming
- Integration with external analysis tools

### 6.3 UI Customization
- Pluggable visualization components
- Custom debug tools
- Agent-specific inspection panels
- Themeable interface