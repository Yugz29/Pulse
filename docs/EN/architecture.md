# Pulse — Progressive Architecture

This document describes Pulse architecture in a way that is usable against the current codebase.

It explicitly separates:
- what is **implemented today**
- what is **stabilized**
- what is still part of the **target architecture**
- what has **not started yet**

The reference execution document remains [refactor-roadmap.md](./refactor-roadmap.md).

---

## 1. Positioning

Pulse is a local system for observing work that:
- captures system and work events
- qualifies them and turns them into usable signals
- structures the current context
- consolidates local memory
- emits explainable proposals

Pulse is not an autonomous agent.

Today, Pulse is still primarily a system of:
- observation
- limited interpretation
- local memory
- suggestions

The target architecture remains:

Observation -> Qualification -> Activity -> Interpretation -> Episode -> Session -> Memory -> Proposal

But those layers do not all exist at the same level of maturity.

---

## 2. Real system state

### Implemented and stabilized

- Local event observation through the Swift app and the Python daemon
- Runtime-side event qualification (`actor`, `noise_policy`, implicit domain from file or action type)
- Real-time work signal computation
- `activity_level` and `task_confidence` exposed through `/state`
- `session_fsm` exposed through `/state`
- `CurrentContext` as the runtime synthesis view
- `SessionSnapshot` as the structured session projection
- `ProposalCandidate` as the business contract before legacy transport
- `SessionFSM` as the source of truth for session lifecycle
- `EpisodeFSM` as the source of truth for temporal episode boundaries
- SQLite persistence for episodes in `session.db`
- `current_episode` and `recent_episodes` exposed through `/state` as a runtime projection
- Episode semantics frozen only at closure (`probable_task`, `activity_level`, `task_confidence`)
- Technical dashboard in the app (`DashboardWindow`) as an independent glassmorphism window
- Phase 1 observability: `CurrentContextBuilder` logs, explicit memory fallback in `freeze_memory()`, logged FSM transitions
- `/memory/sessions` route for session journal exposure
- Locked legacy compatibility on:
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`

### Implemented but still transitional

- `StateStore` still exists for compatibility
- The Markdown context snapshot is still exposed for the assistant / LLM layer
- A compatibility shim still exists between `RuntimeState` and `SessionFSM` around the lock marker

### Not started

- proposals genuinely contextualized by episode
- episode-driven enriched memory
- controlled agentic behavior

---

## 3. Target architecture vs current state

| Layer | Target role | Current state |
|---|---|---|
| Observation | capture raw events | implemented |
| Qualification | assign source and handling policy | implemented |
| Activity | describe what the user is doing now | partially implemented via `activity_level` |
| Interpretation | infer task, friction, patterns | implemented |
| Episode | segment work into temporal segments and later carry frozen semantics | implemented, still limited to temporal boundaries + frozen semantics on closed episodes |
| Session | contain work between temporal boundaries | implemented, with persisted episodes but without rich memory/proposal usage |
| Memory | consolidate facts and retrospective summaries | implemented, still mostly session-centric |
| Proposal | suggest explainable actions | implemented, still local and limited |

The key point is simple: **Pulse now has a usable Episode layer for temporal boundaries and recent history, but not yet a rich episode-driven memory/proposal layer**.

---

## 4. Current runtime layers

### 4.1 Observation

**Status**: implemented

Pulse receives raw events such as:
- `file_modified`
- `file_created`
- `app_activated`
- `clipboard_updated`
- `screen_locked`
- `screen_unlocked`
- commit-related events inferred from git file observation

An event remains a raw observation:
- `type`
- `payload`
- `timestamp`

At this level there is no business interpretation.

### 4.2 Qualification

**Status**: implemented

Before scoring, Pulse enriches some events with attribution metadata:
- `actor`
- `noise_policy`
- scores or markers related to probable event origin

Purpose:
- distinguish user activity, system activity, and assisted activity
- reduce pollution in scoring

This layer already exists in the code, even if it is not yet modeled as a first-class contract.

### 4.3 Activity

**Status**: partially implemented

Pulse currently exposes `activity_level` in signals and in `CurrentContext`.

This layer answers:
- what is the user concretely doing right now?

Examples:
- `editing`
- `reading`
- `executing`
- `navigating`
- `idle`

Important:
- `Activity` is not `Task`
- it is computed today
- it already exists in the runtime
- it is a reliable part of the current context
- but it is not yet treated as a fully independent architectural layer
- and it does not yet carry its own structural responsibility the way a future Episode layer would

### 4.4 Interpretation

**Status**: implemented

Pulse currently infers:
- `probable_task`
- `task_confidence`
- `focus_level`
- `friction_score`
- `work_pattern_candidate`

This layer remains probabilistic.

It does not say:
- "what is true"

It says:
- "what the runtime currently considers most likely from the active signals"

### 4.5 Session

**Status**: implemented

The current session is a temporal container bounded by:
- meaningful activity gaps
- screen lock / unlock
- reset rules that are now stabilized

Session lifecycle is now centralized in `SessionFSM`.

Important:
- a session exists today
- its lifecycle is unified
- and it now aggregates persisted episodes

### 4.6 Memory

**Status**: implemented, still intermediate

Pulse currently has:
- session memory
- a structured session export (`SessionSnapshot`)
- retrospective memory extraction
- a user fact engine
- Markdown and SQLite outputs

Current memory is still largely:
- session-centric
- summary- and fact-oriented

It is not yet:
- organized around episodes
- fine-grained enough to support more advanced proposals on its own

### 4.7 Proposal

**Status**: implemented, limited scope

Pulse currently knows how to:
- produce local decisions
- build `ProposalCandidate`
- convert candidates into the legacy `Proposal` transport
- preserve transparency and evidence

But the current proposal flow is still:
- local
- weakly contextualized by work continuity
- not driven by episodes

### 4.8 Episode

**Status**: implemented, still limited

This layer now exists as a usable runtime system for temporal boundaries.

Concretely, Pulse currently has:
- a persisted `Episode` model in `session.db`
- a top-level `current_episode` exposed through `/state`
- `Session -> Episodes` aggregation through persistence and runtime exposure
- frozen semantics only on closed episodes

Important:
- `EpisodeFSM` remains temporal only
- `SignalScorer` remains the single source of semantic computation
- the active episode remains mostly temporal; live reading comes from `signals`
- `current_episode` is not carried by `CurrentContext`
- memory and proposals are not episode-driven yet

---

## 5. Current structural contracts

### CurrentContext

**Status**: implemented

`CurrentContext` is the real-time synthesized runtime view.

It is used to:
- provide a unified entry point to current context
- feed `build_context_snapshot()`
- feed `/state` through a legacy adapter

Important:
- `CurrentContext` must not become an active object
- it does not contain `current_episode`
- it must not carry retrospective memory

### SessionSnapshot

**Status**: implemented

`SessionSnapshot` is the structured projection of the current or closed session.

It is used to:
- structure the handoff to the memory layer
- preserve strict compatibility with `export_session_data()`

Important:
- it does not contain episodes today
- it remains a session snapshot, not a complete future memory model

### ProposalCandidate

**Status**: implemented

`ProposalCandidate` decouples:
- the business construction of a proposal
- its final legacy transport

It does not carry:
- `id`
- `status`
- persistence lifecycle

### SessionFSM

**Status**: implemented

`SessionFSM` is the source of truth for session lifecycle.

It centralizes:
- `active`
- `idle`
- `locked`
- session boundary transitions

Important:
- `RuntimeState` may still carry compatibility markers
- but it must no longer decide lifecycle behavior

---

## 6. Target concepts not yet implemented

The following elements belong to the target architecture, not to the current system.

### `current_episode` in `CurrentContext`

Target:
- a real-time view of a provisional ongoing episode

Reality today:
- intentionally absent
- not introduced during `Foundation`

### Session containing episodes

Target:
- a session will aggregate multiple episodes

Reality today:
- the session already aggregates persisted episodes, but this structure is not yet used richly by `SessionSnapshot`, memory, or proposals

### Episode-enriched memory

Target:
- finer, more contextual, less flat memory

Reality today:
- memory is still mostly built from sessions and facts

### Smart Proposals

Target:
- proposals contextualized by actual work continuity

Reality today:
- proposals are still local and limited

### Controlled agentic behavior

Target:
- bounded, explainable, validated actions

Reality today:
- not started

---

## 7. Design principles

### Strict separation between real-time and retrospective layers

The runtime must not mix:
- current context computation
- memory consolidation
- retrospective projection

Real-time exists to observe and qualify.
Retrospective logic exists to summarize, consolidate, correct, and remember.

### Transparency is mandatory

Any important inference or proposal must remain tied to:
- its signals
- its confidence
- its evidence set

### No future washing in code or docs

A future concept must be documented as future.

In particular:
- an unimplemented episode capability must not be described as present
- memory not structured by episodes must not be described as already mature
- an unstarted agentic layer must not be described as active

### One source of truth per critical responsibility

Current examples:
- session lifecycle -> `SessionFSM`
- real-time context -> `CurrentContext`
- session projection -> `SessionSnapshot`
- proposal transport -> `Proposal`

---

## 8. Next logical phase

The next logical phase is no longer introducing episodes themselves.

Goal:
- use episodes more effectively for proposals
- articulate memory more clearly around episodes
- make the separation between live signals and retrospective reading easier to read

---

## 9. How to read this document

This document must be read as a progressive architecture document.

It does not say:
- "all of this already exists"

It says:
- "this is the target structure"
- "this is what really exists today"
- "these are the layers that are still future"

If ambiguity appears between:
- this document
- the actual code
- the roadmap

priority is:
1. the actual code
2. [refactor-roadmap.md](./refactor-roadmap.md)
3. this document
