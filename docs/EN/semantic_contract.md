# Pulse Semantic Contract

This document defines the semantic contract of Pulse memory.

It explicitly separates:
- the **current contract**: what the code actually does today
- the **known limits**: where the system is weak, incomplete, or risky
- the **target evolutions**: what Pulse should do later

It does not describe an ideal system.
It does not describe Episode System either.

2026 note: historical sections that mention `EpisodeFSM` describe the previous architecture path. They are kept only as design archive and must no longer guide runtime changes. The current runtime removed `EpisodeFSM` and uses `current_context`, `recent_sessions`, `work_blocks`, and `work_block_*`. The short up-to-date reference is [architecture.md](./architecture.md).

Current Pulse memory is still primarily:
- session-centric
- heuristic
- retrospective

---

# Part 0 — Runtime present contract

The runtime present now has a clear contract.

## 0.1 Source of truth

`PresentState`, stored in `RuntimeState`, is the single canonical source of truth for the present.

The canonical present currently groups:
- session state (`session_status`, `awake`, `locked`)
- current work context (`active_file`, `active_project`, `probable_task`, `activity_level`, `focus_level`)
- a few directly useful surface fields (`friction_score`, `clipboard_context`, `session_duration_min`, `updated_at`)

## 0.2 Allowed producers

The present has only two business producers:
- `SessionFSM` for session state
- `SignalScorer` for current work context

`RuntimeState.update_present()` stores that result.
It does not recompute it.

## 0.3 What is not canonical

- `signals`: a detail and enrichment layer, useful but not canonical
- `CurrentContext`: a rendering of the present for assistant/UI reads
- `StateStore`: a legacy shim
- `SessionMemory`: historical persistence
- `work_blocks` / `recent_sessions`: derived history, not canonical for the present

Explicit prohibitions:
- `signals` are not a source of truth for the present
- `signals` must not be used for business decisions
- `signals` must not be used to derive the main business context
- work history does not currently participate in the truth of the present or the live decision path

## 0.4 Atomic snapshot

The runtime exposes an atomic read snapshot.

It exists to avoid reading:
- `present`
- `signals`
- `decision`

at different instants and creating a hybrid runtime state.

Implementation rule:
- any read path combining `present`, `signals`, and `decision` must go through `get_runtime_snapshot()`
- reading those fields separately is incorrect

## 0.5 Lock / session rule

The current product rule is:

> short lock ≠ new session

This rule is implemented in `SessionFSM`.
It must not be reinterpreted elsewhere.

## 0.6 `/state`

`/state` remains a composite projection for compatibility.

Read rule:
- `present` is the only canonical core
- top-level fields exist for UI compatibility and are deprecated
- `debug` is non-contractual
- no new feature should be built from the top-level `/state` fields

## 0.7 Legacy lock marker

The legacy lock marker is not canonical.

It must only be used for:
- ingress filtering
- debug
- compatibility

It must never be used as a business source.

---

## 1. The problem to avoid

Pulse can create the impression that it understands work when it is actually approximating from sessions and heuristics.

The core risk is simple:

- a modest observation
- repeated often enough
- promoted into a fact
- injected into the LLM with language that sounds too strong

The illusion of understanding appears when:
- tone is stronger than evidence
- the status of the information is unclear
- the documentation describes as robust what is still heuristic

---

## 2. Current contract

### 2.1 Real nature of the memory system

Today, Pulse does not understand work in the strong sense.

What it does is:
- observe sessions
- project those sessions into a usable format
- extract a small set of heuristic observations
- count their repetitions
- promote some observations into facts
- inject part of the consolidated facts into the LLM context

The current memory system is therefore:
- **session-centric**
- **heuristic**
- **deterministic up to LLM compression**
- **capable of being wrong**

It does not yet rely on:
- episodes
- fine-grained work segmentation
- causal understanding of user behavior

### 2.2 Real information levels

The current pipeline can be read in five levels.

#### Level 1 — Local observation

What Pulse has seen without interpretation.

Examples:
- active app
- touched file
- raw duration
- computed friction

Origin:
- runtime events
- current session

Status:
- local
- not durable

#### Level 2 — Current context

What Pulse aggregates about ongoing work.

Examples:
- `PresentState`
- `probable_task`
- `focus_level`
- `session_duration_min`

Origin:
- live runtime
- `SignalScorer`
- `SessionFSM`
- `RuntimeState.update_present()`

Status:
- useful for the present
- not a durable truth

`CurrentContext` is only a read rendering of that level.

#### Level 3 — Heuristic observation

What Pulse derives from a retrospective session.

Origin:
- `_extract_observations()` in `facts.py`

Current examples:
- time slot + task type
- deep focus by time slot
- long session
- high friction on a project

Status:
- session-level hypothesis
- not a fact

#### Level 4 — Repeated observation

A heuristic observation repeated several times.

Current rule:
- `count >= SIGNAL_THRESHOLD (3)`

Status:
- more credible signal
- still not a stable fact

#### Level 5 — Consolidated fact

An observation promoted into the `facts` table.

Current rule:
- `count >= FACT_THRESHOLD (5)`
- no existing fact with the same `key`

Current creation state:
- `confidence = 0.50`
- `autonomy_level = 0`
- `archived = 0`

Status:
- consolidated fact by current system rules
- not high certainty

### 2.3 Real promotion rules

Today, promotion works like this:

```text
Observation -> count >= 3  -> repeated signal
Observation -> count >= 5  -> fact creation
Fact -> confidence < 0.30  -> archive
```

What the system actually applies:
- repetition counting
- an initial confidence score
- temporal decay
- archiving below threshold

What it does not apply today:
- additional semantic validation at promotion time
- filtering on `autonomy_level` before injection
- explicit key-quality checks inside `_promote_pending()`

### 2.4 Real role of `autonomy_level`

In the current code:
- `autonomy_level` exists
- it increases through `reinforce()`
- it decreases through `contradict()`
- it is stored in `facts.db`

But:
- it does **not** affect `render_for_context()`
- it does **not** filter facts injected into the LLM
- it has no operational role in agentic behavior, because that layer does not exist yet

Conclusion:
- `autonomy_level` is currently persisted data that may matter later
- not an active constraint in the current injection contract

### 2.5 Real rule for LLM context injection

Today, `render_for_context()` does exactly this:
- takes active facts
- filters on `confidence >= 0.60`
- limits output to 8 entries
- does not use `autonomy_level`

That filter is the current contract.

A fact injected today should therefore be read as:
- repeated enough to be promoted
- still confident enough to pass the 0.60 threshold
- not necessarily strongly validated by the user

### 2.6 What the memory system currently does well

The current system is useful for:
- keeping simple local memory
- avoiding re-learning everything from scratch every session
- injecting plausible work tendencies
- providing a deterministic base before later sophistication

It is coherent if it is understood as:
- a trend engine
- not a deep understanding engine

---

## 3. Known limits

### 3.1 The system remains largely heuristic

Facts are derived from sessions and simple rules.

That means:
- a badly designed key can create a misleading fact
- repeating a weak heuristic increases frequency, not truth
- the system can consolidate an approximate pattern

### 3.2 Tone can still be stronger than evidence

Even though `_extract_observations()` now separates:
- `obs_description`
- `fact_description`

the risk remains:
- some fact descriptions can still sound more solid than they really are

The problem is not only storage.
The problem is also the tone used at injection time.

### 3.3 `_promote_pending()` is mechanical

Current promotion:
- does not verify semantic quality at promotion time
- does not re-evaluate the robustness of the observation
- simply creates the fact once the counter reaches the threshold

In practice:
- fact quality depends almost entirely on the quality of `_extract_observations()`

### 3.4 `render_for_context()` is simple, not robust

The current `confidence >= 0.60` filter is simple and honest.

But it does not distinguish between:
- a freshly promoted fact
- a repeatedly confirmed fact
- a fact with higher `autonomy_level`

So:
- current injection is pragmatic
- it is not yet semantically very fine-grained

### 3.5 Lack of contradiction is not proof

The system does not actively contradict its own facts.

That means:
- a weak fact can survive for a long time
- silence is not validation
- temporal decay helps, but does not solve the whole issue

### 3.6 Memory is not yet structured by work continuity

Current memory mainly starts from:
- the session
- facts derived from sessions

It is not yet organized around:
- episodes
- fine transitions
- work sequences

This limit is structural and explicitly accepted at this stage.

---

## 4. Target evolutions

This section describes what Pulse should do later.

It is **not** the current contract.

### 4.1 Make injection more selective

Possible target:
- take `autonomy_level` into account
- distinguish more carefully between newly promoted and time-tested facts
- calibrate the injection threshold more precisely

Today:
- this is not implemented

### 4.2 Make promotion less mechanical

Target:
- avoid turning a broad heuristic key into a durable fact just by repetition
- add stronger discipline around the quality of promoted observations

Today:
- that additional validation does not exist

### 4.3 Calibrate fact language more carefully

Target:
- make fact wording proportional to real robustness
- avoid wording that suggests stronger understanding than the evidence supports

Today:
- that calibration remains partial

### 4.4 Separate useful memory from risky memory more clearly

Target:
- distinguish facts that are genuinely useful for context
- reduce vague or overly broad facts
- limit the injection of fragile patterns

Today:
- the system mostly relies on thresholds and observation quality

### 4.5 Prepare the future without pretending it already exists

In the longer term, Pulse will likely need to:
- connect memory, proposals, and user validation more tightly
- separate what helps Pulse speak from what may one day help it act

But this must not be described as already present.

In particular:
- no active agentic layer today
- no episode-driven memory today
- no action logic driven by `autonomy_level` today

---

## 5. Reading and implementation rules

### What should be treated as true today

- memory is mainly derived from sessions
- facts are promoted through repetition of heuristic observations
- `render_for_context()` filters on confidence, not `autonomy_level`
- the system can produce useful approximations without real understanding

### What must not be assumed

- that an injected fact has been strongly validated
- that `autonomy_level` already drives behavior
- that promotion implies strong semantic validation
- that memory already reflects fine-grained work structure

### What to avoid in code

- building memory features as if facts were more robust than they really are
- adding undocumented implicit rules
- talking about "understanding" when the system is still heuristic aggregation
- documenting a desired behavior as if it were current behavior

---

## 6. Operational summary

The current Pulse memory contract is:

- Pulse observes sessions
- Pulse extracts a small set of deterministic heuristic observations
- Pulse promotes those observations into facts through simple thresholds
- Pulse injects a subset of those facts into the LLM through a confidence filter

That contract is useful.

It is also limited.

It should be treated as:
- a usable memory base
- not an advanced understanding system

The right use of this document is therefore:
- understand what Pulse memory does today
- see clearly where it is weak
- prepare future evolutions without assuming they are already active

---

# 2026 decision — Episode System replaced

The `EpisodeFSM` path is abandoned for the current runtime.

The retained model is:
- `SessionFSM`: user lifecycle (`active`, `idle`, `locked`)
- `PresentState`: canonical truth of the present
- `CurrentContext`: product read model of the present
- `recent_sessions`: recent history of closed sessions
- `work_blocks` / `work_block_*`: temporal projections of meaningful work
- `JournalEntry`: human-readable consolidated rendering, derived from history, not a runtime source of truth

Migration rule:
- old terms such as `current_episode`, `recent_episodes`, `work_window_*`, and `closed_episodes` must no longer be used as the current product model;
- they may remain as read fallbacks or compatibility aliases while historical payloads exist;
- every new feature must read canonical fields: `current_context`, `recent_sessions`, `work_blocks`, and `work_block_*`.
