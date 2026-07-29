# Secret AGI Bench

> **⚠️ Pre-launch.** The harness is complete and tested end to end on mock adapters.
> The public leaderboard, replay viewer and transcripts dataset (M4) are not built yet —
> see `ROADMAP.md`.

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

## Evaluate your model in 10 minutes

**1. Try it with no API keys.** The pilot config runs entirely on the mock adapter:

```bash
uv run secretagi run   configs/selfplay-pilot.yaml
uv run secretagi score selfplay-pilot-7 --config configs/selfplay-pilot.yaml
```

That plays 20 seeded 5-player games concurrently and prints a scorecard with
confidence intervals on every metric.

**2. Run it for real.** Set a key and use the smoke config, which plays one game on
cheap models:

```bash
export OPENAI_API_KEY=...        # and/or ANTHROPIC_API_KEY
uv run secretagi run configs/smoke.yaml
```

**3. Add your model** — usually just a config entry, no code:

```yaml
players:
  - name: my-model
    provider: openai          # any OpenAI-compatible endpoint
    model: my-org/my-model
    base_url: https://my-endpoint/v1
    api_key_env: MY_API_KEY
    seats: 5
```

`provider` is `openai`, `anthropic`, or `mock`. Because the OpenAI adapter takes a
`base_url`, one entry covers OpenRouter, Gemini's compat endpoint, xAI, DeepSeek,
vLLM and Ollama. Only a genuinely new API shape needs a new adapter — implement the
`ModelAdapter` protocol in `secret_agi/providers/base.py` and register it in
`factory.py`.

### CLI

```bash
uv run secretagi validate <config>              # check a config without playing
uv run secretagi run      <config>              # play the whole schedule
uv run secretagi resume   <run-id> --config <config>   # continue an interrupted run
uv run secretagi score    <run-id> --config <config>   # scorecards + summary
uv run secretagi export   <run-id>              # bundle report + scorecards as JSON
```

Runs are concurrent, resumable, and stop cleanly at a configured token or dollar cap.
A run is reproducible from its config plus its seed — see `docs/METHODOLOGY.md`.

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
| `send_chat_message` | `text` | The current speaker, during a discussion sub-phase |
| `observe` | — | Anyone |

## Layout

```
secret_agi/
├── engine/       # rules, actions, events, async GameEngine  (correct — do not rewrite)
├── database/     # SQLModel tables, operations, connection, unit of work
├── providers/    # ModelAdapter protocol + OpenAI / Anthropic / Mock adapters
├── players/      # async BasePlayer, LLMPlayer, RandomPlayer, HumanPlayer
├── prompts/v1/   # versioned prompt files (frozen per benchmark version)
├── match/        # run configs, seeded schedules, cost caps, the run orchestrator
├── analysis/     # judge pipeline, scorecards, bootstrap statistics
├── cli.py        # secretagi run | resume | score | export | validate
└── settings.py   # centralized configuration
configs/          # published run configs
tests/            # unit, scenario, integration and edge-case suites
alembic/          # database migrations
```

## Methodology commitments

These are hard requirements, not preferences (see `ROADMAP.md` §1.5):

- **No deception nudges.** System prompts say "play to win", never "deceive". The
  propensity metrics are meaningless otherwise.
- **Seeded, seat-balanced schedules** — seat position is rotated and the realised balance
  is reported; configs and seeds are published so runs are reproducible.
- **Confidence intervals on everything**, bootstrapped over games. Tiers, not fake-precision ranks.
- **Frozen benchmark versions** — ruleset, prompts and judge model frozen per major version.
- **Nothing in CI calls a real provider API.** Integration tests run on the mock adapter.

## Documentation

- `docs/METHODOLOGY.md` — **schedules, seeding, prompts policy, judge setup, metric definitions**
- `docs/IMPLEMENTATION_NOTES.md` — build decisions, known warts, and what to do next
- `IMPLEMENTATION_BRIEF.md` — authoritative build scope (overrides older docs)
- `EVAL_PLAN.md` — landscape research, codebase assessment, eval design
- `ROADMAP.md` — implementation, release and adoption plan
- `SECRET_AGI_RULES.md` — complete game rules with implementation clarifications
- `DATABASE.md` — schema and migration guide
- `JOURNAL.md` — running development journal
