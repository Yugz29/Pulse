# Pulse — Current Runtime Architecture

This document describes the runtime as it exists in the current code.

It does not describe a theoretical target.
It does not describe product vision.
If the code and this document diverge, the code wins.

The reference roadmap remains [refactor-roadmap.md](./refactor-roadmap.md).

---

## 1. Real pipeline

The actual runtime pipeline is:

```text
event
→ SessionFSM
→ SignalScorer
→ RuntimeState.update_present()
→ DecisionEngine
→ SessionMemory
```

More concretely:

```text
macOS / Swift observation
→ POST /event
→ EventBus
→ RuntimeOrchestrator
→ SessionFSM.observe_recent_events()
→ SignalScorer.compute()
→ RuntimeState.update_present()
→ DecisionEngine.evaluate()
→ SessionMemory.update_present_snapshot()
```

`RuntimeOrchestrator` exists to chain that flow.
It must not become a parallel business source of truth again.

---

## 2. Source of truth for the present

`PresentState`, stored in `RuntimeState`, is the single canonical source of truth for the present.

It currently contains:
- `session_status`
- `awake`
- `locked`
- `active_file`
- `active_project`
- `probable_task`
- `activity_level`
- `focus_level`
- `friction_score`
- `clipboard_context`
- `session_duration_min`
- `updated_at`

Read rule:
- if a reader needs to know what is true now, it must read `RuntimeState.present`
- it must not rebuild the present from `signals`, `StateStore`, `SessionMemory`, or `CurrentContext`

---

## 3. Real responsibilities by layer

| Layer | Real role today | What it must not do |
|---|---|---|
| `EventBus` | transport recent events | carry business state |
| `SessionFSM` | produce session state and session boundaries | compute work context |
| `SignalScorer` | produce the current work context | store the present |
| `RuntimeState` | store `PresentState` and expose an atomic read snapshot | recompute semantics |
| `RuntimeOrchestrator` | coordinate the runtime pipeline, proactive triggers, and controlled side effects | become a god-source of truth |
| `DecisionEngine` | decide from `PresentState` | consume `signals` directly as the main source |
| `CurrentContextBuilder` | render `CurrentContext` from `present` | become a source of truth |
| `SessionMemory` | persist history, snapshots, and work projections | correct or write the present |
| `StateStore` | passive legacy shim | derive `active_file`, `active_project`, or session state |

---

## 4. Producers of the present

The present has only two business producers:

- `SessionFSM` produces session state:
  - `session_status`
  - `awake`
  - `locked`
- `SignalScorer` produces work context:
  - `active_file`
  - `active_project`
  - `probable_task`
  - `activity_level`
  - `focus_level`
  - `friction_score`
  - `clipboard_context`
  - `session_duration_min`

`RuntimeState.update_present()` assembles those outputs and stores them.
It does not recompute anything.

---

## 5. Atomic runtime snapshot

The runtime exposes an atomic read snapshot through `RuntimeState.get_runtime_snapshot()`.

It currently contains:
- `present`
- `signals`
- `decision`
- `paused`
- `memory_synced_at`
- `latest_active_app`
- `lock_marker_active`
- `last_screen_locked_at`

Why it exists:
- to prevent a route or helper from reading `present`, then `signals`, then `decision` at different instants
- to prevent hybrid responses where the present and the decision do not belong to the same logical instant

Rule:
- runtime read paths should read this atomic snapshot
- they should no longer assemble runtime state from multiple separate `RuntimeState` getters
- any read path combining `present`, `signals`, and `decision` must go through `get_runtime_snapshot()`
- reading `present`, `signals`, and `decision` separately is incorrect

---

## 6. Reading and exposure

### `CurrentContext`

`CurrentContext` is no longer a source of truth.

It is a rendering of the present for assistant/UI layers.

What it reads from `present`:
- `active_project`
- `active_file`
- `session_duration_min`
- `activity_level`
- `probable_task`
- `focus_level`
- `clipboard_context`

What it still reads from `signals`:
- `task_confidence`
- terminal metadata
- MCP metadata
- `signal_summary`

So:
- `CurrentContext` is useful
- `CurrentContext` is not canonical
- `signals` remain a bounded secondary dependency
- `signals` are not a source of truth for the present
- `signals` must not be used for business decisions
- `signals` must not be used to derive the main business context

### `/state`

`/state` is a projection of the runtime snapshot.

Read rule:
- `present` = canonical
- top-level = temporary compatibility and deprecated
- `debug` = non-contractual

Do not use `signals` as the main source of truth.
Do not use top-level fields as the basis of new features.

The current `/state` payload still mixes:
- a canonical core:
  - `present`
- top-level compatibility fields:
  - `active_app`
  - `active_file`
  - `active_project`
  - `session_duration_min`
  - `runtime_paused`
- compatibility/debug blocks:
  - `signals`
  - `decision`
  - `session_fsm`
  - `current_context`
  - `recent_sessions`
  - `debug`

---

## 7. Lock / session rule

The current product rule is:

> short lock ≠ new session

This rule is implemented in `SessionFSM`.

Concretely:
- a long lock can close the current session and start another one on resume
- a short lock keeps the current session
- the first meaningful event after a short lock must not create a ghost session

The orchestrator does not patch that rule after the fact.
The boundary decision lives in `SessionFSM`.

---

## 8. Work context and history

`EpisodeFSM` has been removed from the runtime.

The current model is simpler:
- `current_context`: product-facing current context
- `recent_sessions`: recently closed sessions for history
- `work_blocks`: work blocks derived from meaningful events
- `work_block_*`: work window data used by memory, commits, and the ResumeCard

The remaining old names are exposed only for compatibility:
- `work_window_*`
- `closed_episodes`

Those aliases must not be used for new features.

### Prepared Resume Card

The ResumeCard has two paths:
- on-demand generation when the user returns, with deterministic fallback
- warm preparation on `screen_locked`, stored temporarily in memory, then consumed on the next `screen_unlocked`

The prepared path is a UX optimization.
It is not a source of truth.
It reads the runtime snapshot and memory payload, then publishes a `resume_card` event if the prepared card is still valid.

Existing debug routes:
- `/debug/resume-card`: forces a deterministic ResumeCard
- `/debug/resume-card/llm`: forces an LLM ResumeCard and returns generation diagnostics

V1 limit: there is not yet a dedicated debug route for the prepared card lifecycle itself (`prepare`, `peek`, `consume`, `expire`).

---

## 9. Remaining legacy layers

The following leftovers still exist:

- `StateStore`: passive compatibility shim
- legacy lock marker in `RuntimeState`: useful for ingress filtering / debug / compatibility, not canonical
- top-level `/state` payload: kept for UI compatibility and deprecated
- markdown / legacy adapters: still fed by `signals` for a few secondary details
- API aliases: `work_window_*`, `closed_episodes`

Those leftovers must not be treated as concurrent sources of truth.

---

## 10. Current limits

- `CurrentContext` still depends partly on `signals`
- `/state` still keeps legacy payload for UI compatibility and debug
- the legacy lock marker still exists alongside `present.locked`
- the memory extractor still contains historical episode vocabulary
- `SessionSnapshot` remains a compatibility projection, not the canonical shape of the present
- the prepared ResumeCard is stored in memory only and disappears if the daemon restarts
- there is not yet a dedicated debug route to inspect or force the `prepared_resume_card` lifecycle

---

## 11. Correct reading rule

To read the runtime correctly today:

1. read `RuntimeState.present` for the canonical present
2. read the atomic runtime snapshot for complete read paths
3. read `CurrentContext` as a rendering
4. read `signals` as a secondary-detail layer
5. read `StateStore` and top-level `/state` fields as compatibility, not truth
6. read `work_blocks` / `work_block_*` for work time and commit windows, not the `work_window_*` aliases
7. read the ResumeCard as a resume projection, never as a source of truth for work
