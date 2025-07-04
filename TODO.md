# Database Implementation TODO

## Phase 1: Core Database Setup ✅ CRITICAL

### 1.1 Database Package Structure
- [ ] Create `secret_agi/database/` package directory
- [ ] Create `secret_agi/database/__init__.py`
- [ ] Create `secret_agi/database/models.py` with SQLModel definitions
- [ ] Create `secret_agi/database/connection.py` for async database setup
- [ ] Create `secret_agi/database/enums.py` for database-specific enums

### 1.2 SQLModel Schema Implementation
- [ ] Define all 9 SQLModel tables from DATABASE.md
- [ ] Add proper relationships and foreign keys
- [ ] Implement JSON column handling with SQLAlchemy Column types
- [ ] Add validation methods and constraints
- [ ] Create enum classes for database fields

### 1.3 Alembic Configuration
- [ ] Install alembic: `uv add alembic`
- [ ] Initialize alembic: `alembic init alembic`
- [ ] Configure `alembic.ini` for SQLite with JSON1
- [ ] Update `alembic/env.py` to use SQLModel metadata auto-generation
- [ ] Create initial migration: `alembic revision --autogenerate -m "Initial schema"`

### 1.4 Dependencies Update
- [ ] Add to `pyproject.toml`: `sqlmodel`, `alembic`, `aiosqlite`
- [ ] Update import structure in `secret_agi/database/__init__.py`

## Phase 2: Database Operations Layer ⭐ HIGH PRIORITY

### 2.1 Connection Management
- [ ] Implement async SQLite connection with JSON1 extension
- [ ] Create database initialization functions
- [ ] Add connection pooling and session management
- [ ] Implement transaction handling utilities

### 2.2 CRUD Operations
- [ ] Create `secret_agi/database/operations.py`
- [ ] Implement game lifecycle operations (create, load, update, delete)
- [ ] Implement state persistence operations (save_state, load_state)
- [ ] Implement action recording operations (record_action, complete_action)
- [ ] Implement event logging operations
- [ ] Implement metrics recording operations

### 2.3 Serialization Layer
- [ ] Create utilities for GameState ↔ JSON conversion
- [ ] Add checksum generation for state integrity
- [ ] Implement proper enum serialization/deserialization
- [ ] Handle nested object serialization (Players, Papers, Events)

## Phase 3: Game Engine Integration 🔧 MEDIUM PRIORITY

### 3.1 GameEngine Database Integration
- [ ] Modify `GameEngine.__init__()` to include database session
- [ ] Update `GameEngine.create_game()` to persist initial state
- [ ] Modify `GameEngine.perform_action()` to save actions and states
- [ ] Add database session management to game lifecycle

### 3.2 State Management Updates
- [ ] Update `GameStateManager` to use database persistence
- [ ] Modify state snapshot saving in `game_engine.py:134-135`
- [ ] Add database transaction handling around action processing
- [ ] Implement atomic action+state+event persistence

### 3.3 New GameEngine Methods
- [ ] Implement `GameEngine.load_game(game_id: str, turn: int | None = None)`
- [ ] Implement `GameEngine.list_games()` for game discovery
- [ ] Add `GameEngine.get_game_history(game_id: str)`
- [ ] Add `GameEngine.branch_game(game_id: str, from_turn: int)`

## Phase 4: Recovery Implementation 🚨 MEDIUM PRIORITY

### 4.1 Recovery Detection
- [ ] Create `secret_agi/database/recovery.py`
- [ ] Implement `find_interrupted_games()` query
- [ ] Implement `analyze_failure_type()` diagnosis
- [ ] Add game health checking utilities

### 4.2 Recovery Operations
- [ ] Implement `recover_game()` main recovery function
- [ ] Add `mark_incomplete_actions_failed()` cleanup
- [ ] Implement `rollback_to_consistent_state()` for transaction failures
- [ ] Add recovery logging and metadata tracking

### 4.3 GameEngine Recovery Integration
- [ ] Add `GameEngine.recover_interrupted_games()` startup method
- [ ] Implement automatic recovery in game initialization
- [ ] Add recovery status reporting
- [ ] Create recovery configuration options

## Phase 5: Testing and Validation 🧪 LOW PRIORITY

### 5.1 Database Integration Tests
- [ ] Update `test_completeness.py` to use database persistence
- [ ] Create database-specific unit tests
- [ ] Add state serialization/deserialization tests
- [ ] Test database migration workflows

### 5.2 Recovery Testing
- [ ] Create `tests/test_recovery.py`
- [ ] Test recovery from agent timeout scenarios
- [ ] Test recovery from engine crash scenarios
- [ ] Test recovery from database transaction failures
- [ ] Add recovery performance benchmarks

### 5.3 Integration Validation
- [ ] Run existing test suite with database backend
- [ ] Validate game completion rates with persistence
- [ ] Test game replay from database
- [ ] Verify data integrity across restarts

## Phase 6: Performance and Optimization 🏎️ LOW PRIORITY

### 6.1 Query Optimization
- [ ] Add database indexes for common query patterns
- [ ] Optimize state serialization performance
- [ ] Implement batch operations for bulk data
- [ ] Add query performance monitoring

### 6.2 Storage Optimization
- [ ] Implement JSON compression for large states
- [ ] Add data retention policies
- [ ] Optimize database file size management
- [ ] Add database maintenance utilities

## Phase 7: ADK Integration (Future) 🔮 PLANNED

### 7.1 ADK Session Tables
- [ ] Implement ADK session persistence
- [ ] Add ADK event storage
- [ ] Create ADK↔SecretAGI data bridge
- [ ] Implement ADK DatabaseSessionService interface

### 7.2 Session Management
- [ ] Add session lifecycle management
- [ ] Implement session state synchronization
- [ ] Add cross-framework compatibility layer

## Implementation Notes

### Critical Dependencies
```toml
[tool.uv.dependencies]
sqlmodel = "^0.0.14"
alembic = "^1.13.0"  
aiosqlite = "^0.19.0"
```

### Key Files to Create
```
secret_agi/
├── database/
│   ├── __init__.py          # Package exports
│   ├── models.py            # SQLModel table definitions  
│   ├── connection.py        # Database connection management
│   ├── operations.py        # CRUD operations
│   ├── recovery.py          # Recovery mechanisms
│   └── enums.py            # Database-specific enums
├── alembic.ini             # Alembic configuration
└── alembic/
    ├── env.py              # Migration environment
    └── versions/           # Migration files
```

### Integration Points
1. **GameEngine.create_game()** → Save initial game + state
2. **GameEngine.perform_action()** → Persist action + new state + events  
3. **GameStateManager.save_state_snapshot()** → Database persistence
4. **New: GameEngine.load_game()** → Restore from database
5. **New: GameEngine.recover_game()** → Handle interruptions

### Success Criteria
- [ ] All existing tests pass with database backend
- [ ] Games can be stopped and restarted from any point
- [ ] Complete action/event history is preserved
- [ ] Recovery handles all failure scenarios gracefully
- [ ] Performance impact < 10% for normal gameplay

## Current Status
- [x] Phase 1.1: Package structure planning
- [x] Phase 1.2: Schema design (DATABASE.md)
- [ ] **NEXT**: Phase 1.2 SQLModel implementation

The goal is database-backed persistence that enables reliable restart capabilities for the existing test games.