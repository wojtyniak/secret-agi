# Secret AGI - Multi-Agent Game System

> **⚠️ DEVELOPMENT WARNING ⚠️**  
> This project is currently in active development and is **not fully functional yet**. Many features are incomplete, APIs may change without notice, and the system may have significant bugs or limitations. Use for experimentation and development purposes only.

A multi-agent game system where AI agents play Secret AGI, a social deduction game. The system enables controlled experiments comparing different agent architectures through automated gameplay and comprehensive performance analysis.

## Quick Start for Agent Developers

### Immediate Development Setup

```bash
# Clone and setup
git clone <repository-url>
cd secret-agi

# Install dependencies
uv sync --dev

# Run tests to verify setup
just test

# Test agent development infrastructure
python test_your_agents.py

# Launch web interface for game monitoring (auto-reload for development)
just dev
```

### Building Your First Agent

1. **Create your agent** in `secret_agi/players/your_agent.py`:

```python
from .base_player import BasePlayer

class YourAgent(BasePlayer):
    def __init__(self, player_id: str):
        super().__init__(player_id)
        # Your initialization code here
        
    async def choose_action(self, game_state, valid_actions):
        """Main decision point - implement your agent logic here."""
        # Add your LLM integration, strategy logic, etc.
        # Return one of the valid_actions
        
        # Example: Simple random fallback
        import random
        return random.choice(valid_actions)
        
    def on_game_start(self, role, allies):
        """Called when game starts with your role and known allies."""
        self.role = role
        self.known_allies = allies
        
    def on_game_update(self, events):
        """Called with new events since your last action."""
        # Track game state, update internal model, etc.
        pass
```

2. **Test your agent**:

```python
# In test_your_agents.py, add your agent:
from secret_agi.players.your_agent import YourAgent

# Test it
await test_mixed_game([
    YourAgent("your_agent_1"),
    RandomPlayer("random_1"),
    RandomPlayer("random_2"),
    RandomPlayer("random_3"),
    RandomPlayer("random_4")
])
```

3. **Run tests and monitor**:

```bash
# Run your agent tests
python test_your_agents.py

# Launch web interface to watch games
python launch_web_viewer.py
# Open http://localhost:8000 to see real-time game action
```

## Game Overview

Secret AGI is a 5-10 player social deduction game where players are AI researchers divided into factions:

- **Safety Researchers** (majority): Develop AI carefully with proper alignment
- **Accelerationists** (minority): Want rapid capability advancement  
- **AGI** (1 player): Hidden superintelligence manipulating development

Players vote on research teams that publish papers advancing Capability and Safety metrics. Each faction has different win conditions based on the final state of these metrics.

### Agent Tools Interface

Your agent interacts with the game through these tools:

```python
# Voting and team formation
await nominate(player_id)           # Director nominates Engineer  
await vote_team(yes_or_no)          # Vote on proposed team
await vote_emergency(yes_or_no)     # Vote on Emergency Safety

# Research actions  
await discard_paper(paper_id)       # Director discards from 3 drawn papers
await publish_paper(paper_id)       # Engineer publishes from 2 remaining papers
await declare_veto()                # Engineer declares veto (when unlocked)
await respond_veto(agree_or_disagree) # Director responds to veto

# Special actions
await call_emergency_safety()       # Initiate Emergency Safety vote
await use_power(target_id)          # Execute power on target (when triggered)
await send_chat_message(text)       # Send chat message (not yet implemented)
await observe()                     # Get updates without taking action
```

### Game State Structure

Your agent receives filtered game state based on role and game events:

```python
{
    "current_phase": "TeamProposal" | "Research",
    "board": {"capability": int, "safety": int},
    "current_director": "player_id",
    "players": [{"id": str, "alive": bool}],  # Limited info
    "failed_proposals": int,
    "veto_unlocked": bool,
    "emergency_safety_active": bool,
    "valid_actions": ["action_type", ...],
    # Role-specific private information
    "your_role": "Safety" | "Accelerationist" | "AGI",
    "known_allies": ["player_id", ...],  # For Accelerationists/AGI
    # Context from recent events
    "recent_events": [event_objects]
}
```

## Development and Testing

### Core Development Commands

```bash
# Web development
just dev            # Start development server with auto-reload

# Quality checks (run before committing)
just check          # Run lint + typecheck + test
just quality        # Format + check everything

# Individual commands
just lint           # Run ruff linting
just typecheck      # Run mypy type checking
just test           # Run unit tests
just fmt            # Format code

# Database operations
just db-upgrade     # Apply database migrations
just db-status      # Check migration status
```

### Testing Your Agents

1. **Quick Validation** (`test_your_agents.py`):
   - Test agent against RandomPlayer baselines
   - Check win rates and completion statistics
   - Verify agent doesn't crash or timeout

2. **Web Interface Testing** (`launch_web_viewer.py`):
   - Start games through web interface
   - Monitor real-time game state and action logs
   - See detailed turn-by-turn agent decisions

3. **Unit Testing** (add to `tests/`):
   - Test specific agent behaviors
   - Mock game scenarios for edge cases
   - Verify agent responses to different game states

### Agent Development Best Practices

1. **Error Handling**: Always handle invalid actions gracefully
   ```python
   try:
       return await self.game_engine.perform_action(action, **kwargs)
   except Exception as e:
       # Log error, return observe action as fallback
       return await self.game_engine.perform_action("observe")
   ```

2. **State Management**: Track game history for better decisions
   ```python
   def on_game_update(self, events):
       self.game_history.extend(events)
       # Update internal beliefs about other players
   ```

3. **Role Strategy**: Implement different strategies per role
   ```python
   async def choose_action(self, game_state, valid_actions):
       if self.role == "Safety":
           return self.safety_strategy(game_state, valid_actions)
       elif self.role == "Accelerationist":
           return self.accelerationist_strategy(game_state, valid_actions)
       else:  # AGI
           return self.agi_strategy(game_state, valid_actions)
   ```

## Monitoring and Analysis

### Web Interface Features

- **Real-time Game Monitoring**: Watch capability/safety progression
- **Detailed Action Logs**: See every player decision with parameters
- **Game Statistics**: Win rates, completion rates, game lengths
- **Visual Feedback**: Color-coded action results and status indicators

### Database Access

Games are automatically persisted to SQLite with complete action history:

```python
# Access game database for analysis
from secret_agi.database.operations import GameOperations
from secret_agi.database.connection import get_async_session

async with get_async_session() as session:
    actions = await GameOperations.get_actions_for_game(session, game_id)
    # Analyze agent behavior patterns
```

### Performance Metrics

Track your agent's performance across games:
- Win rates by role assignment
- Action success/failure patterns  
- Response times and resource usage
- Strategic decision effectiveness

## Advanced Development

### Custom Agent Architectures

Implement sophisticated agent designs:

```python
class AdvancedAgent(BasePlayer):
    def __init__(self, player_id: str, llm_config: dict):
        super().__init__(player_id)
        self.llm = initialize_llm(llm_config)
        self.memory = PersistentMemory()
        self.strategy_model = StrategyModel()
        
    async def choose_action(self, game_state, valid_actions):
        # Multi-step reasoning
        context = self.build_context(game_state)
        reasoning = await self.llm.reason(context, valid_actions)
        decision = self.strategy_model.decide(reasoning)
        return decision
```

### Multi-Agent Coordination

Test agent interactions and emergent behaviors:

```python
# Test different agent combinations
agents = [
    LLMAgent("gpt4_agent"),
    RuleBasedAgent("heuristic_agent"), 
    ReinforcementAgent("rl_agent"),
    RandomPlayer("baseline_1"),
    RandomPlayer("baseline_2")
]

results = await run_multiple_games(agents, num_games=50)
analyze_agent_interactions(results)
```

### Strategy Development

Implement role-specific strategies:
- **Safety**: Prioritize high-safety papers, block dangerous research
- **Accelerationist**: Push capability advancement, coordinate with AGI  
- **AGI**: Manipulate both sides while staying hidden until late game

## System Architecture

### Core Components

- **GameEngine**: Complete async game logic with database persistence
- **SimpleOrchestrator**: Multi-agent game coordination 
- **Database Layer**: SQLModel/SQLite with Alembic migrations
- **Web API**: FastAPI backend with real-time monitoring
- **Agent Framework**: BasePlayer interface with error handling

### Development Files

```
secret_agi/
   players/
      base_player.py          # Abstract agent interface
      random_player.py        # Random baseline implementation  
      agent_template.py       # Agent implementation guide
      your_agent.py           # Your agent implementation goes here
   engine/                     # Core game logic (don't modify)
   database/                   # Persistence layer (don't modify)
   orchestrator/               # Game coordination (don't modify)
   api/                        # Web interface (don't modify)
   tests/                      # Test suite (add your agent tests)

# Development scripts
test_your_agents.py             # Quick agent testing
launch_web_viewer.py            # Web interface launcher
```

## Next Steps

1. **Implement your agent** using the template and examples
2. **Test thoroughly** with the provided tools and web interface
3. **Analyze performance** using the detailed action logs
4. **Iterate and improve** based on game outcomes
5. **Share results** and collaborate with other agent developers

## Additional Documentation

- `SECRET_AGI_RULES.md` - Complete game rules and mechanics
- `ARCHITECTURE.md` - Technical system architecture  
- `JOURNAL.md` - Development history and technical insights
- `TODO.md` - Implementation status and future roadmap

## Contributing

This project focuses on providing robust infrastructure for agent development. The core game engine and database systems are production-ready. Agent developers should:

1. Focus on implementing creative agent architectures
2. Share interesting strategies and results
3. Report any infrastructure bugs or limitations
4. Contribute to test coverage and documentation

---

**Ready to build agents?** Start with `python test_your_agents.py` and `python launch_web_viewer.py` to see the system in action!