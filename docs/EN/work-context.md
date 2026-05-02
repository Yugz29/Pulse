

# Work Context — Work context model

## Goal

The Work Context clarifies what Pulse believes it understands about the current work.

It is not meant to observe more.
It is not meant to give Pulse autonomy.
It is not meant to automatically trigger context requests.

Its role is simpler:

```text
existing runtime state
→ product interpretation
→ readable explanation
→ missing context
→ possible safe probes
```

The goal is to prevent Pulse from accumulating signals without being able to clearly explain:

```text
what it thinks the user is doing
why it thinks that
what is missing to be more confident
what it could ask without being intrusive
```

---

## The four layers that must not be confused

### 1. `PresentState`

`PresentState` is the immediate runtime truth.

It represents the **now**.

It answers questions such as:

```text
Which application is active?
Which project is active?
Which activity is detected?
Is the session active, idle, or locked?
What is the current focus level?
```

`PresentState` must not become a long explanation layer.
It should remain a compact and usable source of truth.

---

### 2. `CurrentContext`

`CurrentContext` is the current product context.

It turns runtime state and signals into a more useful reading for the UI and other modules.

It answers:

```text
What is the current work context?
Which task does Pulse believe it detects?
Which activity level is visible?
What confidence is attached to that reading?
```

In the Dashboard, the **Current Context** card is the main representation of this layer.

`CurrentContext` must not be duplicated by a second competing product card.

---

### 3. `WorkContextCard`

`WorkContextCard` is not a new truth.

It is a passive explanation layer built on top of the existing context.

It is meant to enrich **Current Context**, not replace it.

It exposes:

```text
project
activity_level
probable_task
confidence
evidence
missing_context
safe_next_probes
```

Its main value is not `project`, `activity_level`, or `probable_task`, because these already exist elsewhere.

Its real value is:

```text
evidence
missing_context
safe_next_probes
```

In other words:

```text
Why does Pulse think this?
What is missing?
What could Pulse safely ask for?
```

`WorkContextCard` should not be displayed as a large separate card if that creates a duplicate of **Current Context**.

---

### 4. `Context Probes`

Context Probes are controlled requests for additional context.

They are not automatic.

They go through:

```text
policy
request
approval/refusal
execution gate
runner
redaction when needed
safe audit
```

Today, the executable probes are:

```text
app_context
window_title redacted
```

Sensitive probes remain non-executable:

```text
selected_text
clipboard_sample
screen_snapshot
```

The Work Context may indicate that a probe would be safe or useful, but it must not trigger it by itself.

---

## Current pipeline

```text
SystemObserver / events
→ EventBus
→ SignalScorer
→ PresentState
→ CurrentContextBuilder
→ CurrentContext
→ WorkContextCard
→ Dashboard / enriched Current Context
```

Context Probes remain a separate flow:

```text
WorkContextCard may signal missing context
→ the user stays in control
→ Pulse may create an explicit request
→ the notch or Dashboard asks for validation
→ execution only happens after approval
```

---

## What `/work-context` exposes

The route:

```http
GET /work-context
```

returns a passive card:

```json
{
  "card": {
    "project": "Pulse",
    "activity_level": "editing",
    "probable_task": "debug",
    "confidence": 0.78,
    "evidence": [
      "Active project detected: Pulse",
      "Activity level: editing",
      "Window title available"
    ],
    "missing_context": [
      "User objective not explicit"
    ],
    "safe_next_probes": [
      "app_context"
    ]
  }
}
```

This route must not:

```text
observe new data
trigger a probe
modify memory
make an autonomous decision
approve a request
execute an action
```

---

## Product rules

### Do not duplicate the UI truth

The main Dashboard card remains:

```text
Current Context
```

`WorkContextCard` should enrich this card with:

```text
evidence
missing context
possible safe probes
```

It must not become a second card that re-displays project/task/activity/confidence in competition with the current context.

---

### Do not confuse missing context with authorization

If `WorkContextCard` says:

```text
Window title unavailable
safe_next_probes: ["window_title"]
```

it only means:

```text
Pulse could ask for this context cleanly.
```

It does not mean:

```text
Pulse can read it automatically.
```

---

### No implicit autonomy

Even if the user often accepts a probe, the Work Context must not turn that into automatic permission.

Autonomy may come later, if added, with explicit rules such as:

```text
allow app_context for this session
allow window_title for this project only
never auto-allow clipboard_sample
```

But that logic is not part of the current Work Context.

---

## Explicitly out of scope

The Work Context does not do:

```text
- user decision memory
- auto-approve
- preference learning
- long-term scoring
- automatic probe selection
- clipboard reading
- selected text reading
- screen capture
- OCR
```

---

## Guiding principle

The Work Context should help Pulse become clearer, not more intrusive.

The right model is:

```text
observe with existing signals
interpret carefully
explain what is understood
show what is missing
only suggest safe probes
let the user decide
```

Reference sentence:

```text
Pulse should not only know more things.
Pulse should better explain what it believes it knows.
```