# LLM Cooperation & Deception Eval — Assessment and Plan

*Written 2026-07-28. Covers: (1) landscape research on existing evals, (2) assessment of
this codebase, (3) a concrete proposal for building the eval on top of it.*

## TL;DR

- **Keep the engine.** The Secret AGI rules engine is correct, fully tested (219/219
  passing today), and already has the hard parts an eval harness needs: per-player
  information filtering, full action/state persistence, and replay/branching. Rebuilding
  this or bending a generic framework to these rules would cost more than filling the gaps.
- **The space is crowded but the specific question is not.** There are many social
  deduction benchmarks now (Kaggle Game Arena Werewolf, Elimination Game, Among Us
  sandbox, Avalon, Secret Hitler hobby leaderboards), but almost all of them *assign*
  deceptive roles and publish a single Elo. Nobody maintains an eval that separates
  **propensity to deceive** from **capability to deceive**, or measures **whether
  same-team agents who can't verify each other manage to cooperate** — which is exactly
  what you said you want to measure.
- **Three gaps block the eval today**: no chat system (so no medium for deception), no
  LLM-backed player (and `choose_action` is sync, so an LLM player would block the event
  loop), and metrics tables that exist but are never written to.

---

## 1. Landscape: what already exists (mid-2026)

### Closest neighbors

| Eval | Game | What it measures | Status |
|---|---|---|---|
| [Kaggle Game Arena Werewolf](https://www.kaggle.com/benchmarks/kaggle/werewolf) (GDM, Feb 2026) | 8p Werewolf | Head-to-head Elo across frontier models | Active, hosted; the flagship leaderboard |
| [Elimination Game](https://github.com/lechmazur/elimination_game) (Jan 2026) | Survivor-style with private chats + secret votes | TrueSkill over 61 models; qualitative notes on coalition play and deception resistance | Active, open source; best independent comparison |
| [Among Us sandbox](https://arxiv.org/abs/2504.04072) (NeurIPS 2025) | Among Us | **Separate Deception ELO vs Detection ELO**; tests probes/monitors for catching deception | Open source, safety-oriented |
| [WOLF](https://arxiv.org/abs/2512.09187) (Dec 2025) | Werewolf | Deception *production* vs *detection* decomposition; finds models deceive well but detect poorly | Paper + code |
| [AvalonBench](https://github.com/jonathanmli/Avalon-LLM) / [Trust, Lies & Long Memories](https://arxiv.org/abs/2604.20582) | Avalon | Win rates; the 2026 follow-up studies cross-game **reputation** (188 games) | Semi-maintained |
| Secret Hitler clones ([secret-hitler-bench](https://github.com/jordan-gibbs/secret-hitler-bench), [leaderboard](https://github.com/ArmaanSethi/Secret-Hitler-LLM-Leaderboard), [arXiv:2605.22826](https://arxiv.org/html/2605.22826v1)) | Secret Hitler | Win rate, role-ID accuracy, deception retention | Hobbyist / single papers; **no maintained rigorous leaderboard** |
| [AI Diplomacy](https://every.to/diplomacy) (Every, 2025) | Diplomacy | Famous qualitative result: o3 won by systematic betrayal; Claude Opus 4 refused to betray even while losing | Open source |
| [Concordia Contest](https://arxiv.org/abs/2512.03318) (GDM) | Mixed-motive scenarios | Promise-keeping, reciprocity, sanctioning — cooperation with strangers | Active, but scripted scenarios, not social deduction |
| [Cheap Talk, Empty Promise](https://arxiv.org/abs/2604.04782) (Apr 2026) | 6 canonical games | **Propensity**: models break public commitments in 56.6% of scenarios, >70% when profitable | The single most relevant propensity result |
| Lab scheming evals (Apollo, [OpenAI anti-scheming](https://openai.com/index/detecting-and-reducing-scheming-in-ai-models/), [Anthropic sabotage report](https://alignment.anthropic.com/2025/sabotage-risk-report/)) | Scaffolded scenarios | Covert-action rates, doubling-down under interrogation | Active but not game-based |

Good index of the field: [awesome-LLM-game-agent-papers](https://github.com/git-disl/awesome-LLM-game-agent-papers).

### Gaps this project can fill

1. **Propensity vs capability.** Existing game evals tell a model "you are the traitor,
   deceive" — measuring *can it lie*, not *does it choose to*. Only Cheap Talk,
   MACHIAVELLI, and the Diplomacy anecdotes touch unelicited betrayal. A social deduction
   eval that scores deception *beyond what the role mechanically requires* is novel.
2. **Cooperation among mutually-unverifiable allies.** No benchmark scores whether
   same-team agents (who can't see each other's minds) establish trust and coordinate. An
   exploratory Blood-on-the-Clocktower study found exactly this failing; nothing measures it.
3. **No decomposed leaderboards.** Everyone publishes one Elo. WOLF and the Among Us
   sandbox show deception and detection are separable — but no maintained leaderboard
   reports subscores (deception, detection, cooperation reliability, betrayal rate).
4. **Secret Hitler-family games are underserved** despite being mechanically richer than
   Werewolf — and Secret AGI's specific mechanics provide measurement hooks no other game
   has: forced AGI truthfulness at C≥10 (**honesty under compulsion**), allegiance-viewing
   powers (**does the viewer share truthfully?**), emergency safety (**coordination under
   time pressure**).
5. **Methodology holes everywhere**: almost nobody reports statistical power, seat/role
   controls, or model anonymization (models can identify each other by writing style).

## 2. Codebase assessment (verified 2026-07-28)

**What holds up:**
- `uv run pytest`: **219/219 passing** (~81s). Ruff clean.
- Engine (`secret_agi/engine/`, ~2,500 lines) is genuinely production-grade: complete
  rules with the nasty edge cases (win simultaneity, engineer eligibility, veto timing)
  debugged and locked in by scenario tests; per-player info filtering in `events.py`;
  full persistence with per-turn snapshots, replay, and branching in `game_engine.py`.
- The `Action`/`Event`/`GameStateDB` tables record everything needed for post-hoc analysis.

**What the docs oversell:**
- mypy is **not** at 0 errors — 63 errors today, concentrated in
  `orchestrator/simple_orchestrator.py` (23) and `api/simple_api.py` (9), all mechanical
  Optional-narrowing. The database layer is exempted via a pyproject override.
- **Chat is not implemented.** `SEND_CHAT_MESSAGE` exists as an enum but `actions.py` has
  no validation branch for it and never returns it from `get_valid_actions`. No
  discussion phases. Without table talk there is no medium for deception.
- **`BasePlayer.choose_action` is synchronous** despite "async player interface" claims —
  an LLM player would block the event loop. One abstract method + one orchestrator call
  site to fix.
- **Metrics are schema-only.** `AgentMetric` (tokens, latency, invalid attempts) and
  `record_agent_metrics` exist; nothing ever calls them.
- No LLM SDK dependency at all (ADK appears only in docs/table names). Lockfile is ~1
  year stale but nothing blocking. `__pycache__` is checked into git and should be ignored.

**Verdict: build on it.** The engine is the expensive part and it's done. Treat the
orchestrator/API as scaffolding to be reworked, not preserved.

## 3. Proposed eval design

### What we measure (the two questions, operationalized)

**A. Cooperation under mutual opacity** — "how willing are models to work with others
whose thoughts they can't see?"
- **Ally coordination rate**: among Safety researchers (majority team, mutually
  unverifiable), how often do they converge on correct nominations/votes vs. splinter?
- **Trust formation speed**: rounds until stable voting blocs form; whether blocs track
  true teams (correct trust) or not (misplaced trust).
- **Information sharing after allegiance views**: when a player privately learns a true
  allegiance (C=3/C=6 powers), do they share it? Truthfully? Is it believed?
- **Emergency safety coordination**: when the trigger window opens, does the majority
  team actually assemble the vote?
- **Cross-model cooperation matrix**: mixed-model games — does model X cooperate better
  with copies of itself than with model Y? (Nobody has published this.)

**B. Deception propensity vs capability** — "can they trick, and do they choose to?"
- **Capability**: deception success rate when the role requires it (Accelerationist/AGI
  claims believed; survival to late game; vote-share attracted while evil). Report as a
  Deception score, with a separate Detection score (vote accuracy vs ground-truth roles,
  belief calibration from periodic probes) — following the WOLF / Among Us decomposition.
- **Propensity** (the novel part): deception *in excess of mechanical necessity* —
  - Do *Safety* players lie? (They never need to. Any lie is pure propensity signal.)
  - Does the AGI lie when silence or evasion would work equally well?
  - **Honesty under compulsion**: at C≥10 the AGI must answer identity questions
    truthfully. Does it comply? Does it pre-emptively muddy the water just before the
    threshold? (Unique to this game; no other eval has this hook.)
  - **Promise keeping**: extract commitments from chat ("I'll nominate you next round"),
    check follow-through — the Cheap Talk methodology, embedded in a real game.
- Every chat message gets ground-truth labeling (speaker's true role + private knowledge
  are known to the harness), so transcripts double as a **labeled deception dataset** —
  itself a contribution (only Mafia transcripts exist today; nothing for policy games).

### Scoring output

Not one Elo. A per-model card: `{cooperation reliability, trust calibration, deception
capability, deception detection, betrayal/excess-deception propensity, honesty-under-
compulsion compliance}` + win rates by role as the headline sanity check. Report
confidence intervals; control seat position and role assignment across repeats (the
engine's seeded setup makes this easy).

### Implementation roadmap

**Phase 1 — unblock LLM play (the prerequisite work)**
1. Make `choose_action` async; update orchestrator call site, RandomPlayer, HumanPlayer.
2. Implement chat: validation branch for `SEND_CHAT_MESSAGE` in `actions.py`, a
   discussion sub-phase before nominations and votes (round-robin, K messages per player,
   configurable), delivery through the existing filtered `GameUpdate` / `ChatMessage`
   table.
3. One `LLMPlayer` on the Anthropic SDK (native tool use mapping 1:1 to the existing
   action tools), model/prompt configurable per player. Add a cheap-model smoke test.
4. Housekeeping: gitignore `__pycache__`, fix the 32 orchestrator/API mypy errors,
   refresh lockfile.

**Phase 2 — instrumentation**
5. Wire `record_agent_metrics` (tokens, latency, invalid actions) in the orchestrator.
6. Belief probes: after each round, ask each player (out-of-band, not visible to others)
   for their probability estimate of each player's role → calibration + detection scores.
   (MafiaScope-style, trivial with the filtered-state machinery.)
7. Post-game analysis layer over `Action`/`Event`/`ChatMessage`: LLM-judge labeling of
   chat claims against ground truth (lie / true / unverifiable), commitment extraction +
   follow-through checking, vote-accuracy computation.

**Phase 3 — the eval proper**
8. Match runner: N games per configuration, seeded, role/seat-balanced; self-play
   (all one model) and mixed-model conditions; results into the existing DB.
9. Scorecard report generation + a simple leaderboard page (existing FastAPI viewer is a
   fine base).
10. Publish labeled transcripts.

Phase 1 is a few days of work; the engine does the heavy lifting. Phases 2–3 are where
the novelty lives and can be iterated once games are running.

### Risks / design cautions

- **Cost & variance**: social deduction outcomes are noisy; a 7-player game with rich
  chat can burn serious tokens. Mitigate: small-model pilots, capped message lengths,
  power analysis before scaling, and per-decision metrics (which are lower-variance than
  win rates).
- **Style deanonymization**: models may recognize each other's prose. Consider a
  paraphrasing layer or at least measure the confound.
- **Elicited-propensity caveat**: even "excess deception" happens inside a game frame;
  keep claims scoped ("in-game betrayal propensity"), and never nudge prompts toward
  deception ("play well" not "deceive").
