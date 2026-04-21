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

- A production-ready episode system
- A proposal engine truly contextualized by work continuity
- A rich memory layer driven by episodes
- An autonomous agent

## 2. Current state

### Stabilized

- `CurrentContext` exists and feeds the runtime
- `SessionSnapshot` structures session projection
- `ProposalCandidate` decouples business logic from legacy transport
- `SessionFSM` centralizes session lifecycle
- Legacy compatibility is locked on:
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`
- The `SessionFSM` compatibility shim is documented and bounded

### What has just been completed

- End of the `Foundation` phase
- Reduced structural coupling inside the runtime
- Introduction of minimal structured contracts
- Session lifecycle unified around a single source of truth

### What is still missing

- Field measurement of signal quality and session boundaries
- An explicit episode system
- Smarter proposals built on episodes and richer memory
- A stronger memory chain from session -> episode -> facts
- A controlled agentic framework

## 3. Global roadmap

### Phase 0 — Foundation

**Status**: complete

**Goal**

Make the runtime structurally sound without changing observable behavior.

**Deliverables**

- `CurrentContext`
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

- A single source of truth for session lifecycle
- Structured runtime and session contracts
- Unchanged legacy outputs
- Documented compatibility shim

### Phase 1 — Field observation

**Status**: next phase

**Goal**

Measure the real behavior of the stabilized system before opening Episode System.

**Deliverables**

- Targeted debug and audit instrumentation
- Real-world session scenarios
- Validation of session boundaries on field cases
- Validation of `CurrentContext` as a useful real-time view
- A prioritized list of observed gaps, without opportunistic fixes

### Observation method

- Use the system in real development sessions
- Log observations consistently in `docs/observation-log.md`
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

**Exit condition**

- Session boundaries are considered stable enough on real cases
- Weak zones are identified and classified
- The entry point for Episode System is defined from observation, not intuition

### Phase 2 — Episode System V1

**Status**: not started

**Goal**

Introduce the episode as a unit of meaning inside a session without breaking existing layers.

**Deliverables**

- An explicit episode model
- Episode detection from the stabilized runtime
- `episode -> session` integration
- Output usable by memory and proposals
- Minimum transparency on current and closed episodes

**Out of scope**

- Agentic work
- Full memory rewrite
- Automated actions

**Exit condition**

- Episodes have a stable semantic meaning
- Episode boundaries are understandable and auditable
- A session can aggregate multiple episodes without patchwork

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

- `Field observation -> Episode System V1`
  - Real cases have been observed and documented
  - Session boundaries are considered stable
  - Episode needs are formulated from field data

- `Episode System V1 -> Smart Proposals`
  - Current and closed episodes are usable
  - Session aggregation is stable
  - Transition transparency is sufficient

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

At this stage, Pulse should make it possible to:

- observe in real time:
  - activity
  - task
  - context
- understand session transitions
- visually validate that the system remains coherent

No advanced suggestion or automation is expected at this stage.

## Usage reference

This document exists to arbitrate work order.

It does not exist to justify:

- a refactor without direction
- a premature feature
- an unnecessary abstract generalization
- a direct jump to agentic behavior
