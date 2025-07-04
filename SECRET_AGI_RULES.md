# SECRET AGI - COMPLETE GAME RULES & IMPLEMENTATION GUIDE

## OVERVIEW
A social deduction game where players are AI researchers divided into two secret factions. Safety Researchers aim to develop AI carefully with proper alignment. Accelerationists want rapid capability advancement regardless of risk. Hidden among them is the AGI itself, manipulating development toward uncontrolled superintelligence. Players vote on research teams that publish papers advancing both Capability and Safety metrics, trying to achieve their faction's goals while deducing who to trust.

## SETUP
- **Players**: 5-10
- **Roles**: 
  - 5p: 3 Safety, 1 Accelerationist, 1 AGI
  - 6p: 4 Safety, 1 Accelerationist, 1 AGI  
  - 7p: 4 Safety, 2 Accelerationist, 1 AGI
  - 8p: 5 Safety, 2 Accelerationist, 1 AGI
  - 9p: 5 Safety, 3 Accelerationist, 1 AGI
  - 10p: 6 Safety, 3 Accelerationist, 1 AGI
- **Board**: Capability = 0, Safety = 0
- **Papers**: 17 total (shuffle as deck)
- **Knowledge**: Accelerationists and AGI know each other's identities
- **Turn Order**: Random starting Director, then clockwise rotation

*Implementation Note: Role distribution ensures Safety players are always the majority initially, but Accelerationists + AGI combined can form blocking coalitions in larger games.*

## PAPER VALUES
```
3x [C:0, S:2]  // Pure safety research
2x [C:1, S:2]  // Capability with strong safety  
2x [C:1, S:3]  // Breakthrough safety research
2x [C:1, S:1]  // Balanced research
2x [C:2, S:2]  // Major balanced breakthrough
2x [C:3, S:0]  // Pure capability advancement
2x [C:2, S:1]  // Capability-focused research
2x [C:3, S:1]  // Major capability with minimal safety
```

*Implementation Note: Total deck composition: C=28, S=26. Deck is capability-leaning but close to balanced. Papers are shuffled once at game start and never reshuffled.*

## GAME FLOW

### Phase 1: Team Proposal
1. **Emergency Safety Check**: If Capability - Safety = 4 or 5, any player may call Emergency Safety vote
2. **Nomination**: Director nominates any eligible Engineer
   - **Eligibility**: Cannot nominate the immediately previous Engineer (resets each round)
3. **Voting**: All alive players vote YES/NO simultaneously
4. **Resolution**: 
   - Majority YES (ties fail) → proceed to Phase 2
   - Failed → Failed counter +1, Director passes clockwise
   - 3 failures → draw and auto-publish top paper from deck, reset counter to 0, all players become eligible

*Implementation Note: Track `wasLastEngineer` flag per player, reset to false for all players after auto-publish or successful team formation.*

### Phase 2: Research
1. **Draw**: Director draws 3 papers from deck
2. **Director Discard**: Director discards 1 paper to discard pile  
3. **Engineer Choice**: Engineer receives remaining 2 papers, publishes 1, discards 1
4. **Veto Check**: If veto unlocked (C≥12), Engineer may declare veto before publishing
   - Director agrees → discard all 3 papers, Failed counter +1, return to Phase 1
   - Director refuses → Engineer must publish normally
5. **Publication**: Add published paper values to both meters
6. **Powers**: Execute any powers triggered by new Capability level
7. **Win Check**: Check all win conditions
8. **Next Round**: If no win, Director passes clockwise, reset Engineer eligibility

*Implementation Note: Powers execute immediately when Capability thresholds are reached. Multiple powers can trigger from a single paper if it crosses multiple thresholds.*

## POWERS (execute immediately when Capability reaches level)
- **C=3**: Director views target's allegiance card (9-10p games only)
- **C=6**: Director views target's allegiance card (all game sizes)
- **C=9**: Director picks next Director (overrides clockwise rotation for one round)
- **C=10**: AGI must truthfully reveal identity when directly asked
- **C=11**: Director eliminates target player - they reveal identity and become unable to vote/play (9-10p games only)
- **C=12+**: Veto power unlocked for all future Engineers

*Implementation Note: Powers are mandatory when triggered. The C=10 AGI revelation is a permanent state change - the AGI cannot lie about being the AGI anymore. Store viewed allegiances privately per player. Eliminated players should be marked as `alive: false`.*

### VETO POWER (when unlocked at C≥12)
- Engineer may declare "VETO" before publishing their chosen paper
- Director must respond "AGREE" or "REFUSE"
- If AGREE: discard all 3 originally drawn papers, Failed counter +1, return to Phase 1
- If REFUSE: Engineer must publish normally from their 2 papers
- Veto decision happens before Engineer selects which paper to publish

*Implementation Note: Veto is a powerful late-game mechanic that can prevent unfavorable papers from being published, but costs the team a proposal attempt.*

## EMERGENCY SAFETY
**Timing**: Check at start of each Team Proposal phase only
**Trigger Condition**: Capability - Safety = 4 or 5
**Process**:
1. Any alive player may call for Emergency Safety vote (optional)
2. If called, all alive players vote YES/NO simultaneously  
3. Majority YES → next published paper has Capability reduced by 1 (minimum 0)
4. Vote fails or no one calls → no effect
5. Only one Emergency Safety attempt per phase
6. Effect applies to the very next paper published, regardless of when

*Implementation Note: Track `emergencySafetyActive` flag. Apply -1 Capability modifier to next published paper, then reset flag. The effect persists across rounds until a paper is published.*

## WIN CONDITIONS (check after each paper published and after eliminations)
**Safety Researchers win if ANY of:**
- Safety ≥ Capability when Capability = 10
- Safety reaches 15
- AGI is eliminated via C=11 power

**Accelerationists/AGI win if ANY of:**
- Capability = 15 and Safety < 10
- Capability - Safety ≥ 6  
- AGI is elected Engineer when Capability ≥ 8

**Deck Exhaustion**: 
- If deck runs out: Safety wins if Safety ≥ Capability, otherwise Accelerationists/AGI win

**Simultaneous Conditions**: 
- If multiple win conditions trigger simultaneously, Accelerationists/AGI win

*Implementation Note: Check win conditions in this exact order after each paper publication. The AGI Engineer win condition requires the AGI to be selected as Engineer (not just nominated) when C≥8.*

## INFORMATION RULES
**Public Information:**
- Current Capability and Safety values
- All votes cast by all players  
- All published papers and their values
- Which players are alive/eliminated
- Current Director
- Failed proposal counter
- Whether Emergency Safety is active

**Private Information:**
- Player role assignments
- Discarded papers
- Allegiances viewed through powers
- Contents of Director's 3-card draw before discarding

**Special Rules:**
- Allegiance cards show "Safety" or "Acceleration" (AGI shows "Acceleration")
- AGI and Accelerationists know each other's identities from game start
- When C≥10, AGI must truthfully reveal "I am the AGI" if directly asked about identity
- Dead players cannot vote, nominate, be nominated, or use powers
- Voting majorities calculated from alive players only

*Implementation Note: Maintain separate information views per player. The AGI's forced truthfulness at C≥10 is a permanent rule change, not a one-time revelation.*

## GAME STATE STRUCTURE
```javascript
GameState {
  // Player data
  players: [{
    id: string,
    role: "Safety" | "Accelerationist" | "AGI", 
    allegiance: "Safety" | "Acceleration",
    alive: boolean,
    wasLastEngineer: boolean
  }],
  
  // Board state
  board: {
    capability: number,
    safety: number
  },
  
  // Card management
  deck: [Paper],
  discard: [Paper],
  
  // Turn management  
  currentDirector: playerId,
  failedProposals: number, // 0-2
  roundNumber: number,
  
  // Active effects
  vetoUnlocked: boolean,
  emergencySafetyActive: boolean,
  
  // Power tracking
  viewedAllegiances: Map<viewerId, Map<targetId, allegiance>>,
  agiMustReveal: boolean, // true when C≥10
  
  // Current phase data
  currentPhase: "TeamProposal" | "Research" | "GameOver",
  nominatedEngineer: playerId | null,
  directorCards: [Paper] | null, // null when not in research phase
  engineerCards: [Paper] | null,
  
  // Vote tracking
  teamVotes: Map<playerId, boolean> | null,
  emergencyVotes: Map<playerId, boolean> | null
}

Paper {
  capability: number,
  safety: number,
  id: string
}
```

## API ACTIONS
```javascript
// Phase 1: Team Proposal
nominate(targetId: string) -> GameState
callEmergencySafety() -> GameState  
voteTeam(vote: boolean) -> GameState
voteEmergency(vote: boolean) -> GameState

// Phase 2: Research  
discardAsDirector(paperId: string) -> GameState
declareVeto() -> GameState
respondToVeto(agree: boolean) -> GameState
publish(paperId: string) -> GameState

// Powers (triggered automatically, but may require target selection)
usePower(type: PowerType, targetId?: string) -> GameState

// Information queries
getGameState(playerId: string) -> FilteredGameState
getValidActions(playerId: string) -> [ActionType]
```

## AI AGENT DECISION POINTS

**As Director:**
- Which eligible player to nominate as Engineer?
- Which paper to discard from 3-card draw?
- Who to investigate with allegiance-viewing powers?
- Who to eliminate with C=11 power?
- Whether to agree to Engineer's veto?

**As Engineer:**
- Which paper to publish from 2 options?
- Whether to use veto power (if unlocked)?

**As Any Player:**
- Vote YES/NO on team proposals?
- Call Emergency Safety when conditions are met?
- Vote YES/NO on Emergency Safety?

**As AGI (special considerations):**
- Balance advancing Capability vs. staying hidden
- When to claim Accelerationist identity (before C=10)
- How to handle forced truth-telling at C≥10

## IMPLEMENTATION NOTES

**Randomness**: Only in initial setup (role assignment, deck shuffle, starting Director). All subsequent gameplay is deterministic.

**Validation**: Ensure all actions are validated against current game state and player permissions before execution.

**State Immutability**: Consider using immutable state updates for easier debugging and potential game replay functionality.

**Error Handling**: Invalid actions should return current state with error information rather than throwing exceptions.

**Performance**: Game state is small enough that full state copying is acceptable. No need for complex state diffing.

**Testing**: The deterministic nature after setup makes unit testing straightforward. Focus on testing each phase transition and win condition checking.

**AI Training**: The perfect information (except hidden roles) and deterministic gameplay make this ideal for reinforcement learning and game tree search algorithms.

## IMPLEMENTATION CLARIFICATIONS & INTERPRETATIONS

*These clarifications emerged during implementation and testing to resolve ambiguities in the original rules.*

### Director Override Power (C=9) - Immediate vs Next Round
**Rule**: "Director picks next Director (overrides clockwise rotation for one round)"

**Implementation Interpretation**: The C=9 power **immediately changes** the current director rather than waiting for the next natural director advancement. This interpretation is based on:
- Powers execute "immediately when Capability reaches level"
- The phrase "for one round" refers to the duration of the override effect
- Immediate director change provides more tactical value and clearer timing

**Clarified Behavior**: When C=9 is reached, the current director immediately selects any alive player to become the new director, bypassing the normal clockwise rotation for this selection.

### Veto System Timing and Mechanics
**Rule**: "Veto decision happens before Engineer selects which paper to publish"

**Implementation Interpretation**: The veto workflow follows this exact sequence:
1. Director draws 3 papers from deck
2. Director discards 1 paper to discard pile
3. Engineer receives remaining 2 papers  
4. **IF veto unlocked (C≥12)**: Engineer may declare veto before choosing which paper to publish
5. **IF veto declared**: Director must respond "AGREE" or "REFUSE"
6. **IF director agrees**: All 3 originally drawn papers go to discard, failed_proposals++, return to Phase 1
7. **IF director refuses OR no veto declared**: Engineer selects 1 of their 2 papers to publish

**Strategic Implications**: 
- Veto can prevent unfavorable papers but costs a team proposal attempt
- Director knows all 3 papers when deciding whether to agree to veto
- Veto agreement wastes all research progress for that round

### Power Trigger Timing and Multiple Activations
**Rule**: "Powers execute immediately when Capability thresholds are reached"

**Implementation Clarification**: 
- A single paper can trigger multiple powers if it crosses multiple thresholds (e.g., C=8→11 triggers C=9, C=10, C=11)
- All triggered powers execute in numerical order (C=9, then C=10, then C=11)
- Powers that require director action (C=3,6,9,11) create immediate action opportunities
- Automatic powers (C=10 AGI reveal, C=12 veto unlock) take effect permanently and immediately

### Emergency Safety Persistence
**Rule**: "Effect applies to the very next paper published, regardless of when"

**Implementation Clarification**: Emergency Safety effects persist across:
- Round boundaries (if no papers published between rounds)
- Phase transitions  
- Director changes
- Team proposal failures
- The effect only resets when a paper is actually published

### Win Condition Checking Timing
**Rule**: "Check win conditions after each paper published and after eliminations"

**Implementation Clarification**: Win conditions are checked:
- Immediately after paper capability/safety values are added to board
- After power executions complete (in case powers affect win conditions)
- After player eliminations via C=11 power
- After auto-publish events
- The check order determines priority when multiple conditions trigger simultaneously

### AGI Engineer Win Condition Precision
**Rule**: "AGI is elected Engineer when Capability ≥ 8"

**Implementation Clarification**: This requires:
- AGI player is **selected** as Engineer (team proposal passes), not just nominated
- Capability ≥ 8 **when the team selection completes**
- Game ends immediately upon team approval, before research phase begins
- This prevents AGI from being "discovered" during the research phase

### Information Visibility and Allegiance Cards
**Rule**: "Allegiance cards show 'Safety' or 'Acceleration' (AGI shows 'Acceleration')"

**Implementation Clarification**:
- AGI players have `role: AGI` but `allegiance: ACCELERATION` 
- Power-based allegiance viewing reveals "Acceleration" for AGI players
- Players cannot distinguish AGI from Accelerationists through allegiance viewing alone
- This maintains AGI's cover until C=10 forced revelation

These clarifications ensure consistent implementation and help players understand the precise timing and interactions of complex game mechanics.