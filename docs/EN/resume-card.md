

# Resume Card

The Resume Card is a short context recovery surface.

Its goal is not to summarize the entire day.
Its goal is to help the user quickly understand:
- what they were working on before the pause;
- what the likely objective was;
- what the next concrete action should be.

The Resume Card is a projection for resuming work. It is not a source of truth for work state.

## Triggers

Main path:
- `screen_locked` prepares a Resume Card while the context is still fresh;
- the prepared card is stored temporarily in memory;
- `screen_unlocked` immediately consumes the prepared card if it is still valid.

Fallback:
- if no valid prepared card exists, `screen_unlocked` may generate a Resume Card on demand after a sufficient pause.

## Authorized sources

- `PresentState`
- `current_context` when available
- latest memory/session payload
- `work_blocks` / `work_block_*`
- `recent_sessions`
- recent local journal entries
- recent files or commit files
- commit window derived from `commit_activity_started_at` / `commit_activity_ended_at`
- `diff_summary` when available

Legacy fields such as `work_window_*` and `closed_episodes` may be read as compatibility fallbacks, but they must not guide new features.

The LLM may improve the wording, but it does not decide whether the card should exist.
It only summarizes local sources already collected by Pulse.
The Resume Card is a resume projection, not a source of truth for work.

## Product rules

- at most one card every 2 hours;
- no card if the project is unknown;
- no card for short pauses;
- deterministic fallback is mandatory when the LLM is unavailable or invalid;
- the LLM may reason, but only an exploitable final answer is accepted;
- on `reasoning_without_final`, the provider may retry once in final-only mode;
- the card must remain explainable through `source_refs`;
- a prepared card can be consumed only once and expires after a bounded delay.

## Output contract

The Resume Card contains:
- `title`
- `summary`
- `last_objective`
- `next_action`
- `confidence`
- `project`
- `source_refs`
- `generated_by`
- `display_size`

`generated_by` can be:
- `deterministic`
- `llm`

`display_size` can be:
- `compact`
- `standard`
- `expanded`

## Generation paths

### Deterministic

The deterministic path produces a card without an LLM.
It is the mandatory fallback and a quick testing baseline.

Debug route:

```text
/debug/resume-card
```

### LLM

The LLM path uses the same local context, but improves wording.
It must return a structured final answer.
If the LLM response is empty, invalid, or only reasoning, Pulse falls back to the deterministic card.

Debug route:

```text
/debug/resume-card/llm
```

This route exposes generation diagnostics:
- `llm_called`
- `fallback_reason`
- `raw_preview`
- `error`
- `generated_by`

### Prepared

The prepared Resume Card is generated on `screen_locked`, while the context is still warm.
It is stored temporarily in memory and published immediately on the next `screen_unlocked` if it is still valid.

V1 limits:
- memory-only storage;
- lost if the daemon restarts;
- no dedicated debug route yet for the `prepare` / `peek` / `consume` / `expire` lifecycle.

## UI surface

The card is briefly displayed in the notch.
It is structured around three blocks:
- summary;
- likely objective;
- next action.

The size is bounded by three formats:
- `compact`
- `standard`
- `expanded`

The `expanded` format may increase both the width and height of the notch.
Height remains semi-dynamic based on content, with a `ScrollView` safety fallback.

Pulse adapts the size to the content, but does not turn the notch into a dashboard.

## Non-goals

The Resume Card must not:
- decide what the user should do autonomously;
- replace the journal;
- become a long report;
- expose raw sensitive data;
- become a new source of truth;
- depend on cloud execution.

## Current status

Implemented:
- deterministic Resume Card;
- LLM Resume Card with diagnostics;
- final-only retry on `reasoning_without_final`;
- adaptive notch UI;
- prepared Resume Card V1 on `screen_locked`.

Still to validate in the field:
- whether prepared cards appear reliably on the next unlock;
- whether commit/work block correlation provides enough context for long sessions;
- whether the wording remains useful after real-world pauses.