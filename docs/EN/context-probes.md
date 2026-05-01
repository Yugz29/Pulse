

# Context Probes — Safety Policy and Approval Flow

## Goal

_Context probes_ allow Pulse to request additional context about the current situation without turning the application into a permanent capture system.

The principle is simple:

```text
Pulse wants to read context
→ Pulse creates an explicit request
→ Pulse explains why
→ the user approves or refuses
→ only an approved request can pass the execution gate
→ execution is audited without raw values
```

This phase prepares future context enrichment for Pulse, but it remains deliberately conservative.

Today, two probes are actually executable: `app_context` and `window_title`. `window_title` never returns the raw title: it must pass through the redaction layer before any output. More sensitive probes (`selected_text`, `clipboard_sample`, `screen_snapshot`) are modeled, but not executed.

---

## What this phase adds

Pulse now has a complete but limited pipeline:

```text
Policy
→ Request
→ Debug summary
→ In-memory store
→ Approval routes
→ Execution gate
→ Authorized runner
→ Redaction layer when needed
→ Audit event
```

This pipeline can represent an intent to read context, explain it, ask for approval, and then execute only what is allowed.

---

## Main files

```text
daemon/core/context_probe_policy.py
```

Defines probe kinds, consent levels, sensitivity, and default retention.

```text
daemon/core/context_probe_request.py
```

Defines a probe request and its lifecycle: `pending`, `approved`, `refused`, `expired`, `executed`, `cancelled`.

```text
daemon/core/context_probe_debug.py
```

Produces a readable view for a future validation UI without exposing raw metadata values.

```text
daemon/core/context_probe_store.py
```

Stores requests in memory only. No disk persistence.

```text
daemon/core/context_probe_executor.py
```

Centralizes the execution gate. A request can only execute if it is approved, not expired, and compatible with its policy.

```text
daemon/core/context_probe_runner.py
```

Contains the currently authorized runners: `app_context` and `window_title`.

---

## Probe types

| Probe | Current status | Consent | Sensitivity | Retention | Execution |
|---|---:|---|---|---|---|
| `app_context` | active | implicit session | `public` | `session` | yes |
| `window_title` | active redacted | implicit session | `path_sensitive` | `session` | yes |
| `selected_text` | modeled | explicit each time | `content_sensitive` | `ephemeral` | no |
| `clipboard_sample` | modeled | explicit each time | `content_sensitive` | `ephemeral` | no |
| `screen_snapshot` | modeled | explicit each time | `content_sensitive` | `ephemeral` | no |
| `unknown` | blocked | blocked | `unknown` | `debug_only` | no |

---

## Safety rules

### 1. No sensitive read without a request

Pulse must not read sensitive context directly.

Any future context read must pass through:

```text
ContextProbeRequest
→ approval/refusal
→ execution gate
→ authorized runner
```

---

### 2. No execution without approval

A request must have the status:

```text
approved
```

Otherwise, the gate blocks execution with a `blocked_reason`:

```text
request_not_approved:pending
request_not_approved:refused
request_not_approved:expired
request_expired
policy_blocked
unsupported_probe_kind
```

---

### 3. No persistent storage by default

By default:

```text
allow_persistent_storage = false
```

The current store is memory-only.

It does not survive daemon restart, and that is intentional at this stage.

---

### 4. No raw values in debug views

Debug views expose:

```text
metadata_keys
```

but never:

```text
metadata values
```

Allowed example:

```json
{
  "metadata_keys": ["raw_selection", "source"]
}
```

Forbidden example:

```json
{
  "raw_selection": "sensitive selected content"
}
```

---

### 5. No raw leakage in the audit event

When an `app_context` probe is executed, Pulse publishes this event:

```text
context_probe_executed
```

The payload only contains structural information:

```json
{
  "request_id": "...",
  "kind": "app_context",
  "captured": true,
  "privacy": "public",
  "retention": "session",
  "data_keys": [
    "active_app",
    "active_project",
    "activity_level",
    "probable_task"
  ]
}
```

Values are not published to the EventBus.

---

### 6. Mandatory redaction for sensitive text values

Before a sensitive text value can leave a runner, it must pass through:

```text
redact_context_probe_value()
```

Redaction masks, among other things:

```text
emails
URLs
/Users/<user> paths
obvious tokens
environment secrets
SSH / PKCS#8 private keys
```

The result exposes only:

```json
{
  "redacted_value": "...",
  "redaction_flags": ["email", "url", "home_path"],
  "original_length": 91,
  "redacted_length": 89,
  "was_redacted": true
}
```

The raw title, raw selected text, or raw clipboard content must not be published in debug views or in the EventBus.

---

## `app_context` probe

The least sensitive probe currently executable is:

```text
app_context
```

It returns only:

```json
{
  "active_app": "Code",
  "active_project": "Pulse",
  "activity_level": "editing",
  "probable_task": "coding"
}
```

It does not return:

```text
active_file
window content
clipboard content
selected text
screen content
```

Even if `active_file` is available elsewhere in the runtime, it is deliberately excluded from the probe result.

---

## `window_title` probe

The `window_title` probe is now executable, but only as redacted output.

It reuses data already observed by Pulse:

```text
SystemObserver.swift
→ app_activated.window_title / window_title_poll.title
→ EventBus
→ SignalScorer
→ Signals.window_title
→ run_window_title_probe()
→ redact_context_probe_value()
```

It does not create any new macOS capture path.

It returns a structure like this:

```json
{
  "redacted_value": "Pulse notes for [REDACTED_EMAIL] — [REDACTED_URL] — /Users/[REDACTED_USER]/Projects/Pulse",
  "redaction_flags": ["email", "url", "home_path"],
  "original_length": 91,
  "redacted_length": 89,
  "was_redacted": true
}
```

It does not return:

```text
raw title
window content
selected text
clipboard
screen capture
active_file
```

If no `Signals.window_title` is available, execution is blocked with:

```text
missing_window_title
```

---

## Backend routes

### Probe schema

```http
GET /context-probes/schema
```

Returns:

```text
probe_kinds
consent_levels
default_policies
unknown_policy
```

This route is intended for the future Dashboard so it can clearly display what Pulse may request and what level of risk is involved.

---

### Non-persistent preview

```http
POST /context-probes/request-preview
```

Creates a temporary request that is not stored.

Intended use: preview what the user would see before creating a real request.

---

### Create a request

```http
POST /context-probes/requests
```

Creates a request stored in memory with the status:

```text
pending
```

---

### List requests

```http
GET /context-probes/requests
```

Available filters:

```text
status=pending|approved|refused|expired|executed|cancelled
include_terminal=true|false
```

---

### Approval

```http
POST /context-probes/requests/<request_id>/approve
```

Moves a `pending` request to:

```text
approved
```

---

### Refusal

```http
POST /context-probes/requests/<request_id>/refuse
```

Moves a `pending` request to:

```text
refused
```

---

### Execution

```http
POST /context-probes/requests/<request_id>/execute
```

Executes only approved requests compatible with an authorized runner.

Today:

```text
app_context
window_title redacted
```

If the probe is blocked, the route returns:

```json
{
  "error": "probe_blocked",
  "blocked_reason": "..."
}
```

---

## What is not done yet

Pulse does not yet do:

```text
- screen capture
- OCR
- selected text reading
- raw clipboard reading
- persistent request storage
- selected_text execution
- clipboard_sample execution
- screen_snapshot execution
```

These items must stay out of scope until their approval, redaction, audit, and user-facing display rules are explicitly defined.

---

## Principle to preserve

Pulse must not become a data vacuum.

The right model is:

```text
observe enough
explain clearly
ask before reading
execute only if approved
redact before output
audit without exposing
```