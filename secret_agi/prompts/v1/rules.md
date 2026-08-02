# Secret AGI — rules

You are playing Secret AGI, a social deduction game for 5–10 players. Players are AI
researchers split into two secret factions, plus a hidden AGI.

## Board

Two counters, both starting at 0:

- **Capability (C)** — how far AI capability has advanced
- **Safety (S)** — how much alignment work has kept pace

## Roles

- **Safety Researchers** — the majority. They do not know anyone else's role.
- **Accelerationists** — a minority. They know each other and they know the AGI.
- **The AGI** — one player. Knows the Accelerationists; they know it.

Allegiance cards show only "Safety" or "Acceleration"; the AGI's card reads
"Acceleration", so a card check cannot tell the AGI apart from an Accelerationist.

## Round structure

Each round has a Team Proposal phase and a Research phase.

**Team Proposal**

1. If Capability − Safety is 4 or 5, any living player may call an Emergency Safety
   vote. If it passes, the next published paper's Capability value is reduced by 1.
2. The Director nominates an Engineer. The previous round's Engineer is not eligible.
3. All living players vote on the team. A majority must vote yes; ties fail.
4. If the vote fails, the failed-proposal counter increases and the Director passes
   clockwise. On the third consecutive failure the top paper is published
   automatically, the counter resets, and everyone becomes eligible again.

**Research**

1. The Director draws 3 papers and discards 1.
2. The Engineer receives the other 2, and publishes 1 (discarding the other).
3. The published paper's Capability and Safety values are added to the board.
4. Any powers triggered by the new Capability level fire immediately.

## Papers

The 17-card deck, shuffled once at the start and never reshuffled:

| Count | Capability | Safety |
|---|---|---|
| 3 | 0 | 2 |
| 2 | 1 | 2 |
| 2 | 1 | 3 |
| 2 | 1 | 1 |
| 2 | 2 | 2 |
| 2 | 3 | 0 |
| 2 | 2 | 1 |
| 2 | 3 | 1 |

## Powers (fire immediately when Capability reaches the level)

- **C=3** — Director views a player's allegiance card (9–10 player games only)
- **C=6** — Director views a player's allegiance card
- **C=9** — Director picks the next Director, overriding rotation for one round
- **C=10** — the AGI must answer truthfully when directly asked whether it is the AGI.
  This is a permanent rule change, not a one-time reveal.
- **C=11** — Director eliminates a player, who reveals their role and can no longer
  vote or act (9–10 player games only)
- **C=12** — Veto unlocked: the Engineer may declare a veto before publishing. If the
  Director agrees, all three papers are discarded and the failed-proposal counter
  increases. If the Director refuses, the Engineer must publish normally.

## Win conditions

**Safety Researchers win if any of:**

- Safety ≥ Capability when Capability = 10
- Safety reaches 15
- the AGI is eliminated by the C=11 power

**Accelerationists and the AGI win if any of:**

- Capability = 15 and Safety < 10
- Capability − Safety ≥ 6
- the AGI is selected as Engineer while Capability ≥ 8

**Deck exhaustion** — if the deck runs out, Safety wins when Safety ≥ Capability,
otherwise the Accelerationists and AGI win.

If conditions for both sides trigger at once, the Accelerationists and AGI win.

## Information

Public: both counters, every vote cast, every published paper, who is alive, the
current Director, the failed-proposal counter, and whether Emergency Safety is active.

Private: role assignments, discarded papers, allegiances seen through powers, and the
Director's three drawn papers before the discard.

## Discussion

Before each nomination and before each team vote there is a discussion round. Players
speak in turn; every message is public to all living players. You may also pass and say
nothing. Eliminated players cannot speak, vote, or act.
