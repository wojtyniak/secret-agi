# Secret AGI Bench — Implementation, Release & Adoption Roadmap

*Companion to EVAL_PLAN.md (landscape research + eval design). This document is the
execution plan: how we build it, ship it, and make it an eval that labs and the
community expect every new model to run.*

Goal: **the** reference eval for two questions no maintained benchmark answers today —
1. Do models *choose* to deceive, separately from whether they *can*? (propensity vs capability)
2. Can agents cooperate with allies whose minds they can't read? (trust under mutual opacity)

---

## Part 1 — Implementation

### 1.1 What we keep, what we scrap

| Component | Decision | Why |
|---|---|---|
| `engine/` (rules, filtering, persistence, replay) | **Keep** | Correct, 219 tests, the expensive part |
| `orchestrator/simple_orchestrator.py` | **Scrap & rewrite** | Sync `choose_action`, mypy debt, no metrics, no chat phases |
| `api/simple_api.py` + embedded HTML viewer | **Scrap** | Replaced by static replay viewer + leaderboard site (see Release) |
| `players/` | **Rewrite interface as async**; keep RandomPlayer as baseline | LLM players must not block the event loop |
| Database schema | **Keep**, add probe/judge tables | Action/Event/ChatMessage/snapshot design is exactly right |
| Root scripts (`test_your_agents.py`, `launch_web_viewer.py`) | **Scrap** | Superseded by the CLI |

One engine change worth making: allow **concurrent games** (the "sequential only" design
principle was fine for debugging, but an eval run needs throughput — hundreds of games).
The engine is already instance-scoped; this is mostly about DB session handling and a
semaphore on provider concurrency.

### 1.2 Provider layer (the OpenAI requirement)

Two native code paths cover effectively every model in existence:

- **OpenAI SDK** — with configurable `base_url`. This one adapter covers OpenAI itself
  **plus every OpenAI-compatible endpoint**: OpenRouter (→ 200+ models incl. open-weight),
  Gemini's OpenAI-compat endpoint, xAI, DeepSeek, Mistral, vLLM/Ollama for local models.
- **Anthropic SDK** — native, so we get first-class tool use, thinking budgets, and
  prompt caching (matters a lot for cost: game context is highly cacheable).

No LiteLLM dependency — two thin adapters behind one protocol is less magic, easier to
debug, and we control retry/cost accounting:

```python
class ModelAdapter(Protocol):
    async def decide(self, ctx: DecisionContext) -> Decision:  # tool-call → game action
    async def probe(self, ctx: ProbeContext) -> BeliefReport   # out-of-band belief elicitation
    # both return TokenUsage + latency for metrics
```

Per-player config in YAML — provider, model, base_url, api-key env var, temperature,
reasoning effort, system-prompt variant. Game actions map 1:1 to native **tool calls**
(both SDKs), so invalid-action handling is structured, and "invalid action rate" stays a
measurable metric rather than a parsing headache.

### 1.3 New architecture

```
secret_agi/
├── engine/          # kept as-is (+ concurrency-safe sessions)
├── providers/       # ModelAdapter protocol, openai_adapter, anthropic_adapter, mock_adapter
├── players/         # async BasePlayer, LLMPlayer, RandomPlayer (baseline)
├── match/           # MatchRunner: chat phases, probes, seeding, seat/role balancing,
│                    #   resumability (from existing snapshots), cost caps, parallelism
├── analysis/        # scorecards: judge pipeline (lie labeling, commitment tracking),
│                    #   detection/calibration scoring, bootstrap CIs, cross-model matrix
├── export/          # replay JSON for the web viewer, HF dataset export, leaderboard data
└── cli.py           # `secretagi run|resume|score|export` driven by run configs
```

Chat design (the biggest net-new game feature): a **discussion sub-phase** before each
nomination and each vote — round-robin, K messages per alive player, message length cap
(cost + fairness). All table talk public (matches the tabletop game; private DMs are a
v2 experiment). Belief probes fire after every round, out-of-band and invisible to other
players.

### 1.4 Milestones

| # | Milestone | Contents | Exit criterion |
|---|---|---|---|
| M0 | Modernize base | async interface, scrap dead code, ruff+mypy clean (incl. removing the DB mypy exemption where cheap), fresh lockfile, CI on GitHub Actions, gitignore `__pycache__` | 219 engine tests green + CI badge |
| M1 | LLM plays | provider layer, LLMPlayer, chat phases, mock-adapter integration tests | Full 5p game, mixed Anthropic+OpenAI players, completes reliably |
| M2 | Instrumentation | metrics wiring, belief probes, judge pipeline (lie labels, commitments), scorecard math with bootstrap CIs | One self-play run produces a complete model scorecard |
| M3 | Scale & harden | concurrent games, resumability, cost caps/accounting, prompt caching, seat/role-balanced schedules, power analysis on pilot data | 100-game run completes unattended within budget; variance report |
| M4 | Launch assets | replay viewer, leaderboard site, transcripts dataset export, docs ("evaluate your model in 10 minutes") | v1.0 tag + first public leaderboard (8–10 models) |

M0–M1 ≈ 1–1.5 weeks of focused work; M2 ≈ 1–2 weeks (judge pipeline needs iteration);
M3 ≈ 1 week; M4 ≈ 1–2 weeks. **~6 weeks to launch** at steady part-time pace.

### 1.5 Methodology hardening (our differentiator — most game evals skip all of this)

- **Seeded, balanced schedules**: every model plays every role the same number of times,
  seat positions permuted; configs + seeds published → anyone can reproduce a run.
- **Confidence intervals on everything** (bootstrap over games); leaderboard shows CIs,
  and models are binned into tiers, not fake-precision ranks.
- **Frozen benchmark versions**: ruleset + prompts + judge model frozen per major version
  (v1, v2…); scores are only comparable within a version. Judge outputs spot-checked
  against human labels before freezing.
- **Style-deanonymization control**: measured (can a classifier identify the model from
  chat?) and reported; optional paraphrase layer as an ablation, not a default.
- **No deception nudges**: system prompts say "play to win," never "deceive" — required
  for the propensity claims to mean anything.
- **Cost transparency**: $/game and tokens/game per model published on the leaderboard.

---

## Part 2 — Release

### 2.1 Identity

- **Name**: *Secret AGI Bench*. The game name is the brand — memorable, thematically
  perfect (an eval where models literally hunt a hidden AGI), and self-explaining to
  both the safety crowd and the gaming crowd.
- **License**: Apache-2.0 (lab-friendly; MIT fine too, Apache's patent grant helps
  corporate adoption).
- **Headline metrics get memorable names** (named metrics get quoted):
  - **Backstab Rate** — excess deception: lies beyond what the role requires
    (incl. Safety-player lies, which are *never* necessary)
  - **Poker Face** — deception capability rating (Elo-style)
  - **Gullibility** — inverse detection/calibration score
  - **Circle of Trust** — ally coordination among mutually-unverifiable teammates
  - **Under Oath** — honesty-under-compulsion compliance at C≥10 (unique to this game)

### 2.2 Launch package (all land together — a launch is one moment, not a dribble)

1. **Repo** (public, Apache-2.0): 10-minute quickstart, "add your model in 20 lines"
   adapter guide, published run configs + seeds.
2. **Leaderboard site** (static, GitHub Pages/Cloudflare — no backend to maintain):
   scorecard table with CIs, cross-model cooperation matrix, cost column, methodology page.
3. **Replay viewer** — the single biggest hype asset. Every leaderboard game watchable:
   step-through chat + votes with hidden roles revealed, lies flagged in red as they
   happen. Deception is *watchable* in a way MMLU never was; this is what gets shared.
4. **Technical report** (arXiv): design, metrics, v1 results across 8–10 frontier +
   open-weight models, variance analysis. Target NeurIPS Datasets & Benchmarks. This is
   what makes the eval citable — and citations are what make labs run it.
5. **Labeled transcripts dataset** (HuggingFace): every chat message with speaker's true
   role, private knowledge, and lie/true/unverifiable labels. Nothing like it exists for
   policy games — deception-detection and interpretability researchers become users and
   citers even if they never run a game.

### 2.3 Launch leaderboard lineup

8–10 models spanning labs and openness: latest Claude, GPT, Gemini, Grok, DeepSeek,
Kimi/Qwen, one small model as floor, RandomPlayer as sanity baseline. Both **self-play**
(all seats one model) and **mixed-lobby** conditions — the cross-model cooperation
matrix ("does Claude cooperate better with Claudes than with GPTs?") is an
instantly-shareable figure no one has published.

### 2.4 Operations after launch

- **Day-one coverage of new model releases** — this, more than anything, is how evals
  become "important" (ARC-AGI, Aider, lmarena all won this way). Prereq: automation —
  one GitHub Action / one command from "model announced" to "scorecard published."
  Budget for it (see risks).
- Versioned releases; CHANGELOG for any prompt/judge change; community model
  submissions via PR (config + adapter only — runs executed by us for integrity).
- API credits: apply to lab researcher-access / evals-support programs (Anthropic,
  OpenAI, Google all run them) — evals with safety relevance routinely get credits,
  which also creates a relationship with the eval teams.

---

## Part 3 — Adoption & hype

### 3.1 Positioning (one sentence, repeated everywhere)

> Every benchmark measures whether models *can* deceive. Secret AGI Bench measures
> whether they *choose* to — and whether they can trust each other when they can't
> read each other's minds.

The AI-Diplomacy lesson: what went viral wasn't the leaderboard, it was the *story*
("o3 won by systematically lying; Claude refused to betray even while losing"). Every
release should lead with a concrete, screenshot-able story from the replays, with the
leaderboard as supporting evidence.

### 3.2 Launch sequence (over ~1 week)

1. **Teaser** (a few days before): 2–3 replay clips on X/Bluesky — "watch [model] lie
   about its allegiance for six straight rounds" with the replay-viewer link. No
   leaderboard yet.
2. **Launch day**: blog-style writeup (can live on the leaderboard site) leading with
   the 3 juiciest findings → simultaneously: **Show HN**, **X thread** (findings as
   screenshots + clips), **r/MachineLearning**.
3. **Safety-community post** (day 2–3): LessWrong / Alignment Forum version emphasizing
   propensity-vs-capability decomposition, Under Oath compliance, and the labeled
   transcripts as a resource for monitor/probe research (The Secret Agenda showed
   honesty probes miss strategic in-game lying — our dataset is the testbed for fixing
   that). This community sustains attention on deception evals better than any other.
4. **arXiv preprint** same week; submit to NeurIPS D&B at next deadline.
5. **Direct outreach**: eval/alignment teams at the big labs (credits conversations
   double as awareness); eval aggregators (Epoch AI, vals.ai, HELM); awesome-list PRs
   (awesome-LLM-game-agent-papers etc.); the adjacent-project authors (Among Us
   sandbox, WOLF, Elimination Game, secret-hitler-bench) — they cite, compare, and
   amplify; a Kaggle Game Arena conversation is worth one email (they expand game
   coverage and Secret Hitler-family is conspicuously missing).

### 3.3 Sustaining attention (where most evals die)

- **New-model-day scorecards within ~72h** of every major release — becomes the thing
  people check, then the thing people expect, then the thing labs pre-run.
- **A recurring finding cadence**: monthly-ish short posts mined from accumulated games
  ("models trust agents that talk like them", "reasoning effort raises Backstab Rate" —
  the Avalon reputation paper found exactly this pattern, we can test it at scale).
- **Community lobbies**: let people submit open-weight models / system-prompt variants
  ("can you prompt a model into never betraying without losing?") — cheap engagement,
  generates data.
- **Livestreamed showcase match** for big releases (Kaggle proved watching frontier
  models play draws an audience).
- **v2 experiments** kept on a public roadmap so there's always a "coming next":
  private DMs, cross-game memory/reputation (nearly untouched in the literature),
  human-vs-model lobbies (human baseline = major credibility unlock).

### 3.4 What makes labs care (the actual bar for "important eval")

1. **Citable** — arXiv + venue acceptance.
2. **Reproducible** — frozen versions, seeds, published configs, CIs.
3. **Safety-relevant** — propensity metrics plug into the scheming/deception eval
   conversation labs are already having (Apollo, anti-scheming, sabotage reports);
   "Backstab Rate" is a propensity number a model card can quote.
4. **Cheap enough to run** — publish exact $/scorecard; keep a "lite" config
   (fewer games, wider CIs) under ~$100 so anyone can run it.
5. **Immediately covered** — day-one scorecards mean a new model's social behavior gets
   discussed publicly whether or not the lab engages; engaging becomes the better option.

### 3.5 Risks

| Risk | Mitigation |
|---|---|
| Token cost of full leaderboard runs | prompt caching, message caps, lite config, credits programs; publish costs so contributors know what they're signing up for |
| High variance → noisy rankings | per-decision metrics (lower variance than win rate), power analysis at M3, tiers + CIs instead of ranks |
| Judge-model bias (LLM labels lies) | human spot-check calibration set, judge frozen per version, judge disagreement reported |
| "Propensity" overclaim (it's still a game) | scope claims as *in-game* propensity; no-nudge prompts; report prompt-sensitivity ablation |
| Style deanonymization confound | measure + report; paraphrase ablation |
| Maintainer burnout / eval goes stale | automation-first (one command per scorecard), community adapter PRs, keep scope v1-small |
| Pay-to-play optics if lab-funded | publish methodology + raw transcripts for every leaderboard game; credits ≠ input on scores |
