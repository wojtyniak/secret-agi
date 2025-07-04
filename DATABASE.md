# Secret AGI Database Schema and Usage

## Overview

The Secret AGI database provides persistent storage for all game data, enabling replay, branching, recovery, and comprehensive performance analysis. The schema is designed with SQLModel as the source of truth, with Alembic handling auto-generated migrations.

## Technology Stack

- **ORM**: SQLModel (Pydantic + SQLAlchemy integration)
- **Database**: SQLite with JSON1 extension
- **Migrations**: Alembic with auto-generation from SQLModel
- **Async**: All operations use async SQLAlchemy

## Database Schema

### Core Game Tables

#### 1. **games** - Game Session Management
```python
class Game(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    created_at: datetime
    updated_at: datetime
    status: GameStatus  # active, completed, failed, paused
    config: dict = Field(sa_column=Column(JSON))  # GameConfig serialized
    current_turn: int = 0
    final_outcome: dict | None = Field(default=None, sa_column=Column(JSON))
    metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
```

**Usage**: Track game sessions, configuration, and lifecycle status.

#### 2. **game_states** - Complete State Snapshots  
```python
class GameState(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    state_data: dict = Field(sa_column=Column(JSON))  # Complete GameState
    created_at: datetime
    checksum: str  # SHA256 of state_data for integrity
```

**Usage**: Store complete game state after each action for exact replay and branching.

**Indexes**: 
- `(game_id, turn_number)` - Primary temporal lookup
- `game_id` - Game-specific queries

#### 3. **players** - Player/Agent Assignments
```python
class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    player_id: str  # In-game identifier (e.g., "player_1")
    agent_type: str  # Agent architecture ("RandomPlayer", "HumanPlayer", etc.)
    agent_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    role: Role  # Safety, Accelerationist, AGI
    allegiance: Allegiance  # Safety, Acceleration
    alive: bool = True
```

**Usage**: Map in-game players to agent implementations and track assignments.

**Indexes**:
- `(game_id, player_id)` - Player lookup within game
- `game_id` - Game-specific player lists

#### 4. **actions** - Complete Action History
```python
class Action(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    player_id: str  # In-game player ID
    action_type: ActionType  # nominate, vote_team, etc.
    action_data: dict = Field(sa_column=Column(JSON))  # Parameters and metadata
    is_valid: bool | None = None  # NULL = processing, True/False = result
    error_message: str | None = None
    processing_time_ms: int | None = None
    created_at: datetime
```

**Usage**: Track all action attempts (valid and invalid) for analysis and recovery.

**Indexes**:
- `(game_id, turn_number)` - Temporal action sequences
- `(game_id, player_id)` - Player-specific action history
- `(game_id, is_valid)` - Filter valid/invalid actions

#### 5. **events** - Game Events Stream
```python
class Event(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    event_type: EventType  # state_changed, power_triggered, etc.
    player_id: str | None = None  # Event initiator (if applicable)
    event_data: dict = Field(sa_column=Column(JSON))
    created_at: datetime
```

**Usage**: Record all game events for replay and analysis.

**Indexes**:
- `(game_id, turn_number)` - Event sequences by turn
- `(game_id, event_type)` - Filter by event type

#### 6. **chat_messages** - Communication History
```python
class ChatMessage(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    turn_number: int = Field(index=True)
    speaker_id: str  # Player who sent message
    message: str  # Message content
    phase: str  # Chat phase identifier
    created_at: datetime
```

**Usage**: Store all chat communications for analysis.

#### 7. **agent_metrics** - Performance Tracking
```python
class AgentMetric(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    game_id: str = Field(foreign_key="games.id", index=True)
    player_id: str = Field(index=True)
    turn_number: int = Field(index=True)
    tokens_used: int | None = None
    response_time_ms: int | None = None
    invalid_attempts: int = 0
    internal_state_size: int | None = None
    memory_usage_mb: float | None = None
    created_at: datetime
```

**Usage**: Track agent performance and resource usage.

### ADK Integration Tables

#### 8. **adk_sessions** - ADK Session Management
```python
class ADKSession(SQLModel, table=True):
    id: str = Field(primary_key=True)  # ADK session.id
    app_name: str = Field(index=True)
    user_id: str = Field(index=True)
    game_id: str | None = Field(foreign_key="games.id", default=None)
    player_id: str | None = None  # Links to game player
    session_state: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime
    last_update_time: datetime  # ADK lastUpdateTime
    is_active: bool = True
```

**Usage**: Bridge ADK Sessions with Secret AGI games.

#### 9. **adk_events** - ADK Session Events
```python
class ADKEvent(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID
    session_id: str = Field(foreign_key="adk_sessions.id", index=True)
    event_data: dict = Field(sa_column=Column(JSON))  # Complete ADK Event
    sequence_number: int = Field(index=True)
    created_at: datetime
```

**Usage**: Store ADK event history for session replay.

## Database Usage Patterns

### 1. Game Lifecycle Management

**Create New Game:**
```python
async def create_game(config: GameConfig) -> str:
    game = Game(
        id=str(uuid.uuid4()),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        status=GameStatus.ACTIVE,
        config=config.model_dump(),
        current_turn=0
    )
    await session.execute(insert(Game).values(**game.model_dump()))
    return game.id
```

**Save Game State:**
```python
async def save_game_state(game_id: str, turn: int, state: GameState):
    state_record = GameStateDB(
        id=str(uuid.uuid4()),
        game_id=game_id,
        turn_number=turn,
        state_data=state.model_dump(),
        created_at=datetime.utcnow(),
        checksum=hashlib.sha256(json.dumps(state.model_dump()).encode()).hexdigest()
    )
    await session.execute(insert(GameStateDB).values(**state_record.model_dump()))
```

**Load Game State:**
```python
async def load_game_state(game_id: str, turn: int | None = None) -> GameState:
    query = select(GameStateDB).where(GameStateDB.game_id == game_id)
    if turn is not None:
        query = query.where(GameStateDB.turn_number == turn)
    else:
        query = query.order_by(GameStateDB.turn_number.desc()).limit(1)
    
    result = await session.execute(query)
    state_record = result.scalar_one()
    return GameState.model_validate(state_record.state_data)
```

### 2. Action Processing and Recovery

**Record Action Attempt:**
```python
async def record_action(game_id: str, turn: int, player_id: str, 
                       action_type: ActionType, action_data: dict) -> str:
    action = Action(
        id=str(uuid.uuid4()),
        game_id=game_id,
        turn_number=turn,
        player_id=player_id,
        action_type=action_type,
        action_data=action_data,
        is_valid=None,  # Processing state
        created_at=datetime.utcnow()
    )
    await session.execute(insert(Action).values(**action.model_dump()))
    return action.id
```

**Complete Action Processing:**
```python
async def complete_action(action_id: str, is_valid: bool, 
                         error_message: str | None = None,
                         processing_time_ms: int | None = None):
    await session.execute(
        update(Action)
        .where(Action.id == action_id)
        .values(
            is_valid=is_valid,
            error_message=error_message,
            processing_time_ms=processing_time_ms
        )
    )
```

### 3. Recovery and Restart

**Detect Interrupted Games:**
```python
async def find_interrupted_games() -> list[str]:
    # Find games with incomplete actions
    query = select(Game.id).where(
        Game.status == GameStatus.ACTIVE
    ).where(
        exists(select(1).where(
            and_(Action.game_id == Game.id, Action.is_valid.is_(None))
        ))
    )
    result = await session.execute(query)
    return [row[0] for row in result.fetchall()]
```

**Analyze Recovery Type:**
```python
async def analyze_failure_type(game_id: str) -> dict:
    # Get last complete state
    last_state_query = select(GameStateDB.turn_number).where(
        GameStateDB.game_id == game_id
    ).order_by(GameStateDB.turn_number.desc()).limit(1)
    
    # Get incomplete actions
    incomplete_actions_query = select(Action).where(
        and_(Action.game_id == game_id, Action.is_valid.is_(None))
    )
    
    # Return analysis for recovery strategy
    return {
        "type": "incomplete_action" | "agent_timeout" | "transaction_failure",
        "last_valid_turn": last_turn,
        "incomplete_actions": incomplete_actions
    }
```

### 4. Analysis and Metrics

**Agent Performance Analysis:**
```python
async def get_agent_performance(game_id: str) -> dict:
    query = select(
        AgentMetric.player_id,
        func.avg(AgentMetric.response_time_ms).label('avg_response_time'),
        func.sum(AgentMetric.invalid_attempts).label('total_invalid_attempts'),
        func.avg(AgentMetric.tokens_used).label('avg_tokens')
    ).where(AgentMetric.game_id == game_id).group_by(AgentMetric.player_id)
    
    result = await session.execute(query)
    return {row.player_id: {
        'avg_response_time': row.avg_response_time,
        'invalid_attempts': row.total_invalid_attempts,
        'avg_tokens': row.avg_tokens
    } for row in result}
```

**Game History Queries:**
```python
async def get_game_timeline(game_id: str) -> list[dict]:
    # Combined timeline of actions and events
    query = select(
        Action.turn_number,
        Action.action_type,
        Action.player_id,
        Action.is_valid,
        Event.event_type,
        Event.event_data
    ).select_from(
        Action.join(Event, and_(
            Action.game_id == Event.game_id,
            Action.turn_number == Event.turn_number
        ), isouter=True)
    ).where(Action.game_id == game_id).order_by(Action.turn_number)
    
    return await session.execute(query).fetchall()
```

## Recovery Mechanisms

### Automatic Recovery Process

1. **Detection**: On startup, scan for games with `status='active'` and incomplete actions
2. **Classification**: Determine failure type (agent timeout, engine crash, transaction failure)
3. **State Recovery**: Load last complete game state before failure point
4. **Action Cleanup**: Mark incomplete actions as failed with recovery metadata
5. **Game Resumption**: Restart game engine with recovered state

### Recovery Guarantees

- **No Data Loss**: All committed actions and states are preserved
- **Consistency**: Database transactions ensure atomic state updates
- **Idempotency**: Recovery operations can be safely repeated
- **Auditability**: All recovery actions are logged with metadata

## Performance Considerations

### Indexing Strategy
- Primary indexes on temporal patterns: `(game_id, turn_number)`
- Secondary indexes for analysis: `(game_id, player_id)`, `(game_id, event_type)`
- Composite indexes for common query patterns

### Storage Optimization
- JSON compression for large state objects
- Periodic cleanup of old game data
- Efficient serialization of game state objects

### Query Optimization
- Use prepared statements for common operations
- Batch inserts for multiple events/actions
- Connection pooling for concurrent access

## Migration Strategy

SQLModel serves as the source of truth for database schema:

1. **Model Changes**: Update SQLModel class definitions
2. **Auto-Generation**: Run `alembic revision --autogenerate -m "description"`
3. **Review**: Examine generated migration for correctness
4. **Apply**: Run `alembic upgrade head` to apply changes

This ensures schema consistency and proper version control of database changes.