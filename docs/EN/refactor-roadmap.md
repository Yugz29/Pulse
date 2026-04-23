# Pulse Roadmap

## 1. Pulse vision

### Positioning

Pulse is a local work observation system that qualifies activity in real time,
structures work continuity, consolidates useful memory, and produces explainable actions.

The target chain remains:

Observation -> Qualification -> Activity -> Interpretation -> Episode -> Session -> Memory -> Proposal

### What Pulse is trying to become

- A reliable observer of real work, not just a "probable task" detector
- A system able to identify stable units of meaning inside a session
- A memory base that can support relevant, traceable suggestions
- An assistant that can propose, and later act, under strict control

### What Pulse is not yet

- A proposal engine truly contextualized by work continuity
- A rich memory layer driven by episodes
- An autonomous agent

## 1bis. Runtime state after the refocus

The runtime is no longer organized around multiple competing live views.

The real pipeline is:

```text
event
→ SessionFSM
→ SignalScorer
→ RuntimeState.update_present()
→ DecisionEngine
→ SessionMemory
```

What is now true in code:
- `PresentState` is the single canonical source of truth for the present
- `SignalScorer` is the single source of current work context
- `SessionFSM` is the single source of session state
- `CurrentContext` is a rendering, not a source of truth
- `StateStore` is a legacy shim
- `EpisodeFSM` remains secondary and telemetry-oriented
- `/state` exposes `present` as the canonical core, with compatibility and debug around it
- an atomic runtime snapshot exists to avoid hybrid reads
- short lock != new session

Runtime prohibitions:
- do not reintroduce `signals` as a source of truth for the present
- do not build new features from top-level `/state` fields
- do not read `present`, `signals`, and `decision` separately
- do not recentralize episodes without an explicit runtime-contract refactor

## 2. Current state

### Stabilized

- `PresentState` carries the canonical present
- `CurrentContext` exists as a rendering of the present
- `SessionSnapshot` structures session projection
- `ProposalCandidate` decouples business logic from legacy transport
- `SessionFSM` centralizes session lifecycle
- Legacy compatibility is locked on:
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`
- The `SessionFSM` compatibility shim is documented and bounded

### What has just been completed

- Phase 0 Foundation: structured contracts, locked legacy compatibility, unified session lifecycle
- Phase 1 Field observation: instrumentation, technical dashboard, field observations documented in `OBS.md`
- Phase 2a Episode Boundaries: temporal episodes, SQLite persistence, `/state` exposure, dashboard visibility
- Phase 2b Episode Semantics (current scope): frozen semantic snapshot on closed episodes

### Added in Phase 1

- `activity_level` and `task_confidence` exposed in `/state`
- `session_fsm` exposed in `/state`
- Instrumentation: `CurrentContextBuilder` logs, explicit memory fallback, logged FSM transitions
- Technical dashboard (`DashboardWindow`): independent glassmorphism window to observe internal state
- `/memory/sessions` route exposing session journals

### What is still missing

- Smarter proposals built on episodes and richer memory
- A stronger memory chain from session -> episode -> facts
- A controlled agentic framework

## 3. Global roadmap

### Phase 0 — Foundation

**Status**: complete

**Goal**

Make the runtime structurally sound without changing observable behavior.

**Deliverables**

- `PresentState`
- `CurrentContext` as a rendering
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`
- Locked legacy adapters
- Tested output compatibility

**Out of scope**

- Episode System
- New business heuristics
- Enriched memory
- Agentic behavior

**Exit condition**

- A single source of truth for the present and session lifecycle
- Structured runtime and session contracts
- Unchanged legacy outputs
- Documented compatibility shim

### Phase 1 — Field observation

**Status**: complete

**Goal**

Measure the real behavior of the stabilized system before opening Episode System.

**Deliverables**

- Targeted debug and audit instrumentation
- Real-world session scenarios
- Validation of session boundaries on field cases
- Validation of `CurrentContext` as a useful rendering of the present
- A prioritized list of observed gaps, without opportunistic fixes

**Field observations** (summary — details in `OBS.md`)

- Session timeout too short outside file-driven workflows: non-dev apps are invisible to the FSM
- LLM context injection too flat: everything is injected without relevance filtering
- Memory confirmed as largely session-centric in real usage
- No structured cross-session continuity beyond `last_session_context`

### Observation method

- Use the system in real development sessions
- Keep consistent field-observation notes outside the repo, in a lightweight free-form way
- Analyze drift between:
  - actual activity vs `activity_level`
  - actual task vs `probable_task`
  - perceived session boundaries vs FSM boundaries
- Capture short concrete cases for later audit

**Out of scope**

- Episode implementation
- Heuristic changes not justified by observation
- Memory redesign
- Agentic work

**Exit condition — validated**

- ✓ Session boundaries stable on real cases
- ✓ Weak zones identified and classified (see `OBS.md`)
- ✓ Episode System entry point defined from field observations

### Phase 2a — Episode Boundaries

**Status**: complete

**Goal**

Introduce reliable and observable episode boundaries without imposing semantics yet.

**Deliverables**

- A minimal `Episode` model
- Boundary detection from hard signals
- `episode -> session` integration
- SQLite persistence
- Transparency on the current episode in `/state` and the dashboard

**Out of scope**

- Episode semantics beyond the temporal model
- Agentic work
- Full memory rewrite
- Automated actions

**Exit condition**

- Episode boundaries are understandable and auditable
- A session can aggregate multiple episodes without patchwork

### Phase 2b — Episode Semantics

**Status**: complete (current scope)

**Goal**

Attach deterministic semantics to closed episodes without moving scoring out of live runtime signals.

**Deliverables**

- `probable_task`, `activity_level`, and `task_confidence` carried by closed episodes
- Semantics frozen only at episode closure
- Technical dashboard transparency between live signals and closed-episode history

**Out of scope**

- `origin`
- Episode summary / LLM enrichment
- Memory/proposal exports based on episodes
- Agentic work

**Exit condition**

- Closed episodes carry readable semantics
- Live semantics still come from `PresentState`, not from the active episode
- Session aggregation is stable

### Phase 3 — Smart Proposals

**Goal**

Evolve proposals from local suggestions toward proposals contextualized by session, episode, and memory.

**Deliverables**

- Proposal flow enriched by `CurrentContext + Episode + Session + Memory`
- Proposal prioritization
- Stronger explainability
- Suggestion deduplication and arbitration

**Out of scope**

- Autonomous execution
- Multi-step agentic behavior

**Exit condition**

- Proposals are more relevant than simple local triggers
- False positives go down
- Suggestions remain transparent and controllable

### Phase 4 — Enriched memory

**Goal**

Move memory from flat session summaries toward a structure based on work continuity.

**Deliverables**

- Memory consolidation built from episodes
- Better separation between real-time and retrospective layers
- Facts and summaries better aligned with actual work produced
- Memory contracts ready for proposal and future agentic use

**Out of scope**

- Autonomous agent behavior
- Global storage rewrite without demonstrated need

**Exit condition**

- Memory becomes genuinely useful for explaining and guiding proposals
- Work summaries stop being too flat or too session-centric

### Phase 5 — Controlled agentic behavior

**Goal**

Open bounded action capabilities on top of a system that is already reliable in observation, episodes, proposals, and memory.

**Deliverables**

- Explicit authorization framework
- Full traceability of proposed and executed actions
- Scope and safety guardrails
- User validation mechanisms before significant action

**Out of scope**

- Unsupervised autonomy
- Opaque decisions
- Silent execution

**Exit condition**

- Actions remain auditable, explainable, and bounded
- Pulse remains controlled, not autonomous by default

## 4. Transition rules

### Gates before moving to the next phase

- `Foundation -> Field observation`
  - Structured contracts are in place
  - Legacy compatibility is locked
  - Session lifecycle is unified

- `Field observation -> Episode Boundaries (2a)`
  - Real cases have been observed and documented
  - Session boundaries are considered stable
  - Episode needs are formulated from field data

- `Episode Boundaries (2a) -> Episode Semantics (2b)`
  - Current episodes are visible and boundaries are auditable
  - Session aggregation is stable
  - Runtime behavior matches real field cases

- `Episode Semantics (2b) -> Smart Proposals`
  - Closed episodes carry readable semantics
  - Live semantics still come from `PresentState`
  - Session aggregation is stable

- `Smart Proposals -> Enriched memory`
  - Proposals are contextualized but still limited by current memory
  - The need for richer structured memory is demonstrated

- `Enriched memory -> Controlled agentic behavior`
  - Memory is reliable
  - Proposals are explainable
  - Action and validation framework is defined

### What we refuse to do too early

- Introduce Episode System without field observation
- Change heuristics without measurement
- Rewrite storage before the model is stable
- Open agentic behavior before proposals are robust
- Add abstractions "for later" without a real responsibility today

## 5. Working rules

- No opportunistic patch without explicit phase attachment
- No refactor without a clear business or structural goal
- No feature without entry and exit criteria
- No invisible debt: every shim, compat layer, or compromise must be documented
- No big bang rewrite
- One source of truth per critical responsibility
- Any behavioral change must be treated as such, not hidden inside structural work

## 6. Expected user-facing output at this stage

At the end of the current Phase 2 scope, Pulse should make it possible to:

- observe activity, task and context in real time through `PresentState`
- visualize internal state through the technical dashboard
- detect episode boundaries inside a session
- inspect recent closed episodes with a frozen semantic snapshot

Cross-session continuity and smart proposals remain out of scope for the current Phase 2 scope.

## Usage reference

This document exists to arbitrate work order.

It does not exist to justify:

- a refactor without direction
- a premature feature
- an unnecessary abstract generalization
- a direct jump to agentic behavior
