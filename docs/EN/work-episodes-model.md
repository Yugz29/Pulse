# Pulse — Work Episodes Model

## Status

This document describes the target model for Phase 2a.

`Work blocks` already partially exist through `daemon/memory/work_heartbeat.py` and `today_summary`.

Work episodes are not implemented yet as a canonical unit.

## Objective

Pulse must clearly distinguish several related but different concepts:

- system session
- work block
- work episode
- commit delivery
- journal entry

This distinction prevents Pulse from treating a powered-on computer, a long runtime session, a late Git delivery, or simple user presence as real work time.

## Definitions

### System Session

A system session describes the broad runtime state: `awake`, `active`, `idle`, `locked`, and the live duration displayed by Pulse.

It can be broader than actual work. For example, a machine can stay active during passive reading, a break, a video, or non-work context.

The system session must never be used alone as worked duration.

### Work Heartbeat

A work heartbeat is a signal classified by `daemon/memory/work_heartbeat.py`.

There are three levels:

- `strong`
- `weak`
- `none`

A `strong` heartbeat can open or extend a work block.

A `weak` heartbeat can only support or extend a recent block already corroborated by a `strong` signal.

A `none` heartbeat must never create or extend work.

### Work Block

A work block is a short cluster of qualified heartbeats.

It represents observed work activity and is already used by `today_summary`.

Its duration comes from heartbeats and their clustering. It must not depend on raw wall-clock duration from the system session.

### Work Episode

A work episode is the future canonical unit for Phase 2a.

It groups one or more coherent work blocks around the same intent or task. It may survive short gaps when the signals remain compatible.

It must end on a real boundary: long idle, dominant non-work activity, screen lock, night, restart repair, or another boundary that makes continuity uncertain.

### Commit Delivery

Commit delivery is the moment when a commit is delivered.

It is not necessarily the moment when the work happened. A commit can be created or pushed later, sometimes the next day.

This moment must be represented by `delivered_at`.

### Journal Entry

A journal entry is a human-readable memory rendering.

It may merge several commits or several blocks when that improves readability.

It must not invent worked duration when evidence is weak.

## Invariants

- User presence alone can never open a work episode.
- A weak app alone can never open a work episode.
- AI/dev apps are `weak` signals unless corroborated.
- Read-only git commands such as `status`, `log`, `show`, and `diff` are not strong evidence.
- Non-work titles such as YouTube/Netflix must prevent or cut extension.
- A late commit delivery never extends worked duration.
- `delivered_at` is distinct from `worked_at`.
- A work episode's duration comes from heartbeats/work blocks, not from `session_duration_min`.
- A long `restart_repair` session must be treated as uncertain until corroborated.

## Commit Attachment Rules

The target rule is to attach a commit to a compatible episode without artificially inflating duration.

Pulse should look for a recent episode compatible with the commit.

Compatibility should use file coherence, diff scope, active project, and observed work signals.

If the commit is delivered much later, `worked_at` stays on the real episode and `delivered_at` carries the commit time.

If no compatible episode exists, Pulse should create a short or uncertain commit-only entry instead of inflating duration from the system session.

## Examples

### Normal Work

Code + terminal + immediate commit.

Pulse creates a short episode from the observed work blocks. The commit is delivered inside the episode, so `worked_at` and `delivered_at` stay close.

### Late Delivery

Work from 23:00 to 00:30, then YouTube/night, then commit at 10:00.

Pulse keeps `worked_at` on 23:00-00:30. The commit carries `delivered_at` at 10:00. Work duration is not extended until 10:00.

### Presence Without Work

YouTube + mouse + Chrome.

Pulse creates no episode. User presence and active app are not enough.

### AI App During Work

Code + ChatGPT + terminal.

ChatGPT supports the episode because it appears in a context already corroborated by code or terminal. ChatGPT alone must not open the episode.

## Phase 2a Implications

Phase 2a must build the following chain:

```text
events → heartbeats → work blocks → episodes → journal entries
```

Phase 2a must not:

- use `session_duration_min` as the source of truth
- treat `commit_time` as `start_time`
- treat active app as work
- reintroduce an arbitrary duration cap

## Non-Goals

- No fine-tuning.
- No adaptive learning for now.
- No global refactor.
- No intrusive screen/content surveillance.
- No LLM summary to decide worked duration.
