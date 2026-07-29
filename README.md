# Secret AGI Bench

> **⚠️ Under construction.** The rules engine and storage layer are complete and tested.
> The eval harness (provider layer, chat, probes, judge, scorecards, CLI) is being built
> milestone by milestone — see `IMPLEMENTATION_BRIEF.md` and `ROADMAP.md`.

An eval harness where LLM agents play **Secret AGI**, a 5–10 player social deduction game,
producing per-model scorecards for two questions no maintained benchmark answers today:

1. **Do models *choose* to deceive**, separately from whether they *can*? (propensity vs capability)
2. **Can agents cooperate with allies whose minds they can't read?** (trust under mutual opacity)

See `EVAL_PLAN.md` for the landscape research and eval design, `SECRET_AGI_RULES.md` for
the game itself.

## Setup

```bash
uv sync --all-extras   # Python 3.13 + uv
just check             # ruff + mypy + pytest — must be green
```

## Development commands

```bash
just              # list all recipes
just lint         # ruff check
just typecheck    # mypy
just test         # pytest
just check        # all three (the quality gate)
just fmt / fix    # format / autofix

just db-upgrade   # apply migrations
just db-status    # current migration
```

## Running a game today

Until the match runner and CLI land (M3), games are driven directly through the engine:

```bash
uv run python -c "import asyncio; from secret_agi.engine.game_engine import run_random_game; \
print(asyncio.run(run_random_game(5, database_url='sqlite:///:memory:')))"
```

`test_completeness.py` runs the same thing in bulk to validate game termination across
player counts.

## Writing a player

Players implement the async `BasePlayer` interface in `secret_agi/players/base_player.py`:

```python
from secret_agi.engine.models import ActionType, GameState, GameUpdate
from secret_agi.players.base_player import BasePlayer


class YourPlayer(BasePlayer):
    async def choose_action(
        self, game_state: GameState, valid_actions: list[ActionType]
    ) -> tuple[ActionType, dict]:
        # game_state is already filtered to what this player may see
        return ActionType.OBSERVE, {}

    async def on_game_start(self, game_state: GameState) -> None: ...
    async def on_game_update(self, game_update: GameUpdate) -> None: ...
    async def on_game_end(self, final_state: GameState) -> None: ...
```

`RandomPlayer` in `secret_agi/players/random_player.py` is the baseline implementation and
the reference for parameter shapes.

### Game actions

| Action | Parameters | Who |
|---|---|---|
| `nominate` | `target_id` | Director |
| `vote_team` | `vote: bool` | All alive |
| `call_emergency_safety` | — | Any alive, when C−S ∈ {4, 5} |
| `vote_emergency` | `vote: bool` | All alive |
| `discard_paper` | `paper_id` | Director |
| `publish_paper` | `paper_id` | Engineer |
| `declare_veto` | — | Engineer, when C ≥ 12 |
| `respond_veto` | `agree: bool` | Director |
| `use_power` | `power_type`, `target_id` | Director |
| `send_chat_message` | `text` | All alive (discussion sub-phase, M1) |
| `observe` | — | Anyone |

## Layout

```
secret_agi/
├── engine/       # rules, actions, events, async GameEngine  (correct — do not rewrite)
├── database/     # SQLModel tables, operations, connection, unit of work
├── players/      # async BasePlayer, RandomPlayer, HumanPlayer
└── settings.py   # centralized configuration
tests/            # unit, scenario, integration and edge-case suites
alembic/          # database migrations
```

## Methodology commitments

These are hard requirements, not preferences (see `ROADMAP.md` §1.5):

- **No deception nudges.** System prompts say "play to win", never "deceive". The
  propensity metrics are meaningless otherwise.
- **Seeded, balanced schedules** — every model plays every role the same number of times;
  configs and seeds are published so runs are reproducible.
- **Confidence intervals on everything**, bootstrapped over games. Tiers, not fake-precision ranks.
- **Frozen benchmark versions** — ruleset, prompts and judge model frozen per major version.
- **Nothing in CI calls a real provider API.** Integration tests run on the mock adapter.

## Documentation

- `IMPLEMENTATION_BRIEF.md` — authoritative build scope (overrides older docs)
- `EVAL_PLAN.md` — landscape research, codebase assessment, eval design
- `ROADMAP.md` — implementation, release and adoption plan
- `SECRET_AGI_RULES.md` — complete game rules with implementation clarifications
- `DATABASE.md` — schema and migration guide
- `JOURNAL.md` — running development journal
