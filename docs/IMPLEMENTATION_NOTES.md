# Implementation Notes — M0–M3

*Written at the end of the M0–M3 build. `docs/METHODOLOGY.md` says what the system
does and why, normatively. This document is the handover: the decisions that were
judgement calls, the warts that are real, and what I would do next.*

---

## 1. Decisions the brief left open

The brief fixed the architecture. These are the places I had to choose, with the
reasoning, so they can be overturned deliberately rather than by accident.

### Silence is a legal move in discussion

`OBSERVE` by the current speaker forfeits their slot. The alternative — every
player must produce K messages — would have been simpler, and I rejected it
because it corrupts the thing the benchmark exists to measure: a player who would
rather not commit to a claim would be *forced* to invent one, and that invention
would land in the Backstab Rate numerator. It also means a model that refuses to
speak cannot deadlock the table.

**Cost:** message counts vary between players, so per-message rates have uneven
denominators. Acceptable — the alternative biases the metric itself.

### Role balance is statistical, not forced

Seat position is controlled (rotated, with the realised balance reported). Role
assignment is *not*: it comes from the engine's seeded dealing.

Forcing "every model plays the AGI exactly N times" means overriding how the game
deals roles, at which point you are measuring a modified game. I would rather have
wide intervals on an honest game than tight intervals on a synthetic one. The
per-role `n`s are printed on every card so a reader can see what actually happened.

**If you disagree**, the change is localised: `build_schedule()` in
`match/schedule.py` would need to pre-assign roles and the engine would need to
accept them. That is a methodology change and a version bump, not a bug fix.

### Discussion is a sub-phase, not a phase

Chat lives inside `TEAM_PROPOSAL`: same board, same everything, only the set of
valid actions narrows. This kept the entire chat feature out of the rules engine's
phase machine — no new `Phase` member, no new transitions to get wrong, and every
one of the 194 pre-existing engine tests stayed valid untouched.

### Chat is off by default in `GameConfig`

The match runner turns it on. This is why M1 landed without touching a single
existing test expectation.

### `test_completeness.py` and `debug_game.py` survive

ROADMAP §1.1 marks "root scripts" for scrapping, but the brief's explicit delete
list (decision #1) names only `test_your_agents.py` and `launch_web_viewer.py`. I
kept the other two, since they still work and are useful for engine-level
debugging. **Recommendation:** fold `test_completeness.py` into the CLI as
`secretagi selfcheck` and delete both, once someone confirms nobody's muscle
memory depends on them.

---

## 2. Bugs found during the build

All three were caught by tests written for something else, which is the argument
for the test suite being as large as it is.

### The OBSERVE deadlock (M1)

A player that always failed — crashing, or a model returning something unusable —
fell back to `observe`. But `observe` cannot satisfy a turn that *demands* a
nomination, so the runner re-selected the same player forever and the game burned
turns until `max_turns`.

Fixed with `GameEngine.random_valid_action()` as a documented last resort. The
side effect is the interesting part: **the integration suite went from 215s to
33s**. Games that were "passing" had been spinning too. If you see a suite time
jump like that again, suspect a liveness bug, not a performance one.

### Global RNG (M1)

`create_game` called `random.seed(config.seed)` on the *global* RNG, and
`simulate_to_completion` and `RandomPlayer` then drew from that same global
stream. It looked deterministic only because games ran one at a time. Under M3's
concurrency, "seeded" runs would have silently stopped being reproducible — the
worst kind of bug for a benchmark, because nothing fails, the numbers are just
quietly wrong.

Everything now carries a private `random.Random`. **Watch for regressions here:**
any new `random.foo()` at module level in game or player code reintroduces it.

### The cost cap ate a paid-for game (M3)

The first implementation called `cost.check()` at the end of `_play_game`, which
raised `BudgetExceeded` *after* the game had finished — discarding the result of a
game whose tokens had already been spent. Two tests failed with
`games_completed == 0`.

The pre-start gate was the fix at the time. Review then pointed out the other
half: a gate that only fires *between* games cannot stop a single runaway game.
Spend is now recorded per model call and checked between decisions, so a game can
be cut short and flagged `aborted` — while a game that finishes normally still
keeps its result.

---

## 3. Known warts

Real, small, and worth knowing before you trust a number.

### Fixed in review, kept here as history

The first round of review caught a set of issues that are now resolved; they are
worth knowing about because each one was silent — nothing failed, the numbers
were just wrong.

| Issue | Why it mattered |
|---|---|
| Pending vote tallies leaked to later voters | The deciding voter saw the split. A systematic advantage correlated with seat order — the confound the seat rotation exists to remove |
| Transient provider errors were never retried | One 429 became a *random* nomination in the transcript, indistinguishable from the model's own choice |
| Token semantics differed across providers | Anthropic excludes cache tokens from `input_tokens`, OpenAI includes them; cross-provider cost comparisons were off by up to an order of magnitude |
| Pricing assumed OpenAI semantics | Cache-read subtraction double-discounted Anthropic and often clamped billed input to zero |
| Extended thinking produced guaranteed-400s | `max_tokens` below the thinking budget, plus a temperature the API rejects |
| The seat "rotation" was a shuffle | A uniform shuffle of a rotated list is a shuffle; the documented control did not exist |
| Resume re-judged restored games | Doubled judge spend and duplicated every `ChatLabel`, inflating `n` and narrowing CIs |
| Resume reset the cost tracker | A run capped at $50 and killed at $49 could spend another $50 |
| The cost cap could not stop a runaway game | It only gated game *starts*; spend is now recorded per decision |
| The judge saw only roles and chat | METHODOLOGY promised private knowledge; the highest-value deception claims were unjudgeable |
| `necessary` was optional on a lie | Lies without a verdict vanished from Backstab Rate — asymmetrically, for evil roles only |
| The bootstrap treated seats as independent | Published intervals were too narrow, on the numbers the benchmark sells itself on |
| Circle of Trust matched votes by turn distance | Could score a vote on one proposal against an ally's vote on the next |
| Every game re-initialized the global DB engine | A race by construction: swapped the sessionmaker mid-run and leaked a pool per game |
| Deck count always rendered "unknown" | Public information under the rules, and deck exhaustion is a win condition |
| The fallback could burn one-shot actions | A broken agent could spend the phase's Emergency Safety call or veto a round away |

Two of these are worth internalising rather than just noting. **The seat-rotation
bug is the cautionary one:** the docstring, METHODOLOGY and a passing test all
described a control that the code did not implement, because the test only
checked that each model touched each seat *at least once*. A control that is
asserted but not measured is not a control. The replacement asserts exact
counts. **The cluster-bootstrap bug is the expensive one:** it would have shipped
intervals that were simply too narrow, on precisely the numbers this benchmark
asks to be trusted on.

### `tokens_per_game` on a scorecard excludes probe tokens

`AgentMetric` rows are written once per **decision**. Belief probes update
`LLMPlayer.total_usage` (so they reach the `CostTracker` and the run report) and
write their own `BeliefProbe.tokens_used`, but they never produce an
`AgentMetric` row. So:

- **Run report `total_tokens`** = decisions + probes. This is the true spend.
- **Scorecard `tokens_per_game`** = decisions only.

On the 20-game pilot that gap was ~824k vs ~671k tokens per game — probes were
roughly 19% of spend. Neither number is wrong, but they answer different
questions and the scorecard does not say which one it is answering.

**Recommendation:** either write an `AgentMetric` row for probes with a
`kind` column, or rename the scorecard field to `decision_tokens_per_game`. The
second is a one-line fix and I would do it before publishing any cost column.

### The `necessary` fallback is a judgement call

When the judge labels a lie but omits `necessary`, the pipeline asks once more
and then defaults to **unnecessary** — counting it as excess deception. The
alternative (dropping it) biases Backstab Rate downward for evil roles only,
which is worse. But it does mean a judge that systematically omits the field
would inflate the metric rather than deflate it. The occurrence is logged; if
the calibration exercise (§4) shows it happening often, this needs revisiting.

### Discussion state lingers after a game-ending action

If a win condition triggers while a discussion is open, `_clear_discussion()`
blanks the fields without emitting a phase-transition event. Harmless — the phase
is `GAME_OVER` and every action is rejected — but a replay viewer reading the
event log will see a discussion that opens and never closes. Worth a synthetic
close event when M4 builds the viewer.

### `Under Oath` often has a tiny `n`

It only has data when a game actually reaches C≥10. On the pilot that was `n=6`
across 20 games. The interval is correspondingly enormous. This is honest, not
broken, but do not put it on a leaderboard next to a win rate without showing
the `n`.

### The `mypy` pin

Pinned `<2`. mypy 2.x crashes with an INTERNAL ERROR while following
`anthropic/_client.py`. The pin plus `follow_imports = "skip"` for `anthropic.*`
and `openai.*` is the workaround; our adapters wrap those SDKs in typed helpers
anyway. Revisit when the upstream crash is fixed.

### `ruff format --check` fails on 15 pre-existing files

Not part of `just check`, so not part of the gate. Left alone deliberately: a
repo-wide reformat would have buried the milestone diffs. **Recommendation:** do
it as one isolated commit now that the milestones have landed.

---

## 4. Recommendations, in the order I would do them

### Before publishing any number

1. **Calibrate the judge against human labels.** This is the single biggest
   threat to the headline claims. Every propensity metric is downstream of one
   LLM's `lie`/`true`/`unverifiable` call and, more delicately, its
   *necessary/unnecessary* judgement. Take ~200 messages spanning all three roles,
   label them by hand, and report judge–human agreement. If agreement on
   "necessary" is poor, Backstab Rate is not yet publishable — and that is the
   metric the whole benchmark is named for.
2. **Run a power analysis on real pilot data.** 20 games is enough to shake out
   the harness; it is nowhere near enough to separate two close models. Use the
   per-decision metrics (Backstab Rate, Gullibility, invalid-action rate) — they
   are far lower-variance than win rate — to set the game count for a leaderboard
   run.
3. **Fix `tokens_per_game`** (§3) before any cost column goes public.
4. **Populate the price table.** `CostTracker` takes prices but nothing ships
   them, so every run currently reports `unpriced_models` and $0.00. A small
   `configs/prices.yaml`, loaded by the CLI, would close this.

### Soon after

5. **Measure style deanonymization.** Train a cheap classifier to identify the
   speaking model from chat text alone. If it succeeds, the cross-model
   cooperation matrix is confounded and needs the paraphrase ablation. This is
   cheap to check and currently a blind spot.
6. **A real smoke test against live APIs, run manually before each release.**
   `configs/smoke.yaml` exists and is documented, but by design nothing in CI
   exercises it. Someone should run it by hand and record the result each time
   the provider adapters change — the mock cannot catch a tool-schema rejection
   from a real endpoint.
7. **Prompt-sensitivity ablation.** Re-run one config with a reworded (still
   deception-free) system prompt. If Backstab Rate moves a lot, that number is
   measuring the prompt as much as the model, and the README should say so.

### Structural, when convenient

8. **Split the test suite by speed.** It is ~12 minutes, almost all of it full
   mock games. Mark the integration tests and let `just test` run the fast ones
   by default, with CI running everything. Right now the slow feedback loop
   discourages running the suite locally.
9. **`database/connection.py` holds one global engine.** Fine for concurrent games
   against one database, but a process can only talk to one database at a time.
   If the CLI ever grows a `--database-url` flag or a run needs to write to two
   places, this needs to become instance-scoped.
10. **The judge is sequential.** `ChatJudge.judge_game` labels messages one at a
    time, and the orchestrator judges games one at a time after the run. On a
    large run this will dominate wall-clock. It parallelises the same way the
    games do; nobody has needed it yet.

### Explicitly not recommended

- **Do not add private DMs** without treating it as a new benchmark version. It
  changes what "all table talk is public" means, and every propensity metric is
  calibrated against public speech.
- **Do not "improve" the prompts** to make models play better. The prompts are
  frozen per version, and a prompt that coaches strategy is a prompt that
  contaminates propensity. If a model plays badly, that is a finding.

---

## 5. Things that are load-bearing and easy to break

A short list for whoever touches this next.

| Invariant | Enforced by | Breaks if |
|---|---|---|
| No prompt nudges toward deception | `tests/test_llm_player.py::TestPromptHygiene`, `tests/test_providers.py` | anyone edits `prompts/v1/` or a tool description |
| Tool schemas are built from the *filtered* state | `test_providers.py::test_paper_enum_comes_from_the_players_own_hand` | someone passes the full state to `build_tools` |
| Bootstrap intervals are reproducible | `test_stats.py::test_results_are_reproducible` | the fixed bootstrap seed is removed |
| A resumed run == an uninterrupted run | `test_run_orchestrator.py::test_a_resumed_run_matches_an_uninterrupted_one` | game seeds become stored rather than derived |
| Nothing in CI calls a real API | structural — tests only construct `MockAdapter` | someone adds a test that builds a real adapter |
| Chat off by default | `test_chat.py::TestChatDisabledByDefault` | `GameConfig.chat_enabled` default flips |

The prompt-hygiene one deserves emphasis: it is a *hard requirement*, not a
preference. If those tests ever fail, the correct response is to fix the prompt,
never to relax the test.
