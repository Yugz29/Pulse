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
- `CurrentContext` as the runtime synthesis view
- `SessionSnapshot` as the structured session projection
- `ProposalCandidate` as the business contract before legacy transport
- `SessionFSM` as the source of truth for session lifecycle
- Locked legacy compatibility on:
  - `build_context_snapshot()`
  - `/state`
  - `export_session_data()`

### Implemented but still transitional

- `StateStore` still exists for compatibility
- The Markdown context snapshot is still exposed for the assistant / LLM layer
- A compatibility shim still exists between `RuntimeState` and `SessionFSM` around the lock marker

### Not started

- Episode System V1
- a usable `current_episode` in the runtime
- sessions structured around persisted episodes
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
| Episode | segment work into units of meaning | not started |
| Session | contain work between temporal boundaries | implemented, without episodes |
| Memory | consolidate facts and retrospective summaries | implemented, still mostly session-centric |
| Proposal | suggest explainable actions | implemented, still local and limited |

The key point is simple: **Pulse does not yet have a usable Episode layer**.

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
- but the session does not yet contain structured episodes

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

**Status**: not started

This layer does not yet exist as a usable runtime system.

Concretely, Pulse does not currently have:
- a stabilized `Episode` model in the runtime
- a `current_episode` field in `CurrentContext`
- episode persistence
- `Session -> Episodes` aggregation
- an episode-driven proposal flow

Any document that suggests otherwise is describing the target, not the present state.

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

### Episode

Target:
- a unit of meaning inside a session
- detected continuously, then consolidated
- usable by memory and proposals

Reality today:
- no episode system has started

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
- the session exists without that structure

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
- an unimplemented episode must not be described as present
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

The next phase is not Episode System.

The next logical phase is `Field observation`.

Goal:
- measure the behavior of the stabilized runtime in practice
- qualify the gaps before opening an Episode effort

Implications:
- no immediate Episode feature work
- no premature generalization
- no heuristic changes without observation

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
