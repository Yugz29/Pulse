# Pulse

> A local layer for observation, context, memory, and control around AI tools on macOS

---

## Why Pulse exists

AI tools are becoming increasingly capable of reading, editing, executing, and proposing actions inside a real working environment.

The problem is not only answer quality.  
The problem is also loss of visibility:

- what does the AI actually see?
- what is it relying on?
- how much context does it really have?
- why is it proposing this now?
- when is it acting too early?

Pulse exists to keep that decision layer from becoming opaque.

The core idea is straightforward:

> instead of treating AI as a black box, build a local layer of context, memory, and control around it.

---

## What Pulse is today

Pulse is a local system that:
- observes useful activity on the machine
- builds a usable current context
- maintains a simple local memory
- intercepts selected agent actions
- produces explainable proposals
- exposes an independent technical dashboard window to make internal state visible in real time

In practice, Pulse is built from:
- a Swift macOS app around the notch
- an independent dashboard window in the app for session, memory, events, MCP, and system visibility
- a local Python daemon
- an optional LLM layer, used only when deterministic logic is not enough

Today, Pulse is mainly able to:
- observe
- structure
- remember
- control

It does not yet:
- understand work continuity in a deep way
- segment work into usable episodes
- make genuinely smart proposals based on where the user is in the work
- act autonomously

---

## What Pulse is not

Pulse is not:
- an autonomous agent
- a system that fully understands what the user is doing
- a general-purpose chatbot
- a thin LLM wrapper
- a magical productivity layer

Pulse is a serious local foundation for building:
- better visibility
- better context
- better user control

But it is not the finished system yet.

---

## The problem Pulse is solving

Using AI in a real working environment creates several recurring problems:

- context is fragile and must be repeated
- AI tools only see a partial slice of the work in progress
- proposals often arrive at the wrong time
- agent commands become harder to review
- memory across interactions is weak or nonexistent

Pulse tries to address this locally by rebuilding a coherent chain:

Observation -> structuring -> memory -> proposal

Not to replace AI, but to give it a more legible and controllable frame.

---

## How Pulse works

Pulse currently operates in three layers.

### 1. Local observation

The Swift app observes the system:
- active app
- touched files
- clipboard
- screen lock / unlock
- runtime-relevant interactions

It does not interpret.
It emits events.

### 2. Local structuring

The Python daemon turns those events into more useful layers:
- work signals
- current context
- session lifecycle
- session projection
- local proposals

This is currently the strongest part of the project.

It is built around:
- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`

### 3. Memory and enrichment

Pulse then produces a retrospective local memory:
- session summaries
- user facts
- reusable context for assistant interactions

That memory already exists, but it is still:
- mostly session-centric
- heuristic
- imperfect

The LLM is used only when needed:
- commit summaries
- limited enrichment
- explicit user questions

### Routes currently exposed

- `/state`
- `/insights`
- `/facts`
- `/facts/stats`
- `/facts/profile`
- `/memory`
- `/memory/sessions`
- `/mcp/pending`
- `/mcp/decision`

---

## What is solid today

The foundation is now in place.

That means Pulse already has:
- a structured runtime
- a unified session lifecycle
- a coherent current context
- a clean session projection
- locked legacy compatibility on critical outputs

This is not a finished intelligence layer.

But it is a credible base for observing the real system before moving further.

---

## What still needs to be built

The hardest part is not raw observation.

The hardest part is still ahead:
- distinguishing actual work phases correctly
- reducing weak inferences
- making better proposals
- enriching memory without overclaiming

In particular, Pulse does not yet have:
- a usable episode system
- episode-structured memory
- a genuinely contextual proposal engine
- controlled agentic behavior

Put differently:
- the foundation is done
- the intelligence layer is not

---

## How this differs from a purely agentic approach

Many systems start directly from action:
- the agent sees something
- the agent decides
- the agent acts

Pulse starts from a different order:
- observe first
- structure next
- remember what is worth keeping
- propose before acting

That distinction matters.

Pulse is trying to build an AI layer that can be reviewed, understood, and corrected.
Not one that acts faster than the user can follow.

---

## Where the project stands

Pulse is no longer just a vague prototype.

It has crossed an important threshold:
- the runtime foundation is complete
- the core contracts exist
- session lifecycle has a single source of truth
- the system is stable enough to be observed seriously

The next logical step is no longer field observation, which is now closed.

The next logical step is now:

**Episode System V1**

In practical terms, that means:
- introducing a real unit of meaning inside a session
- structuring work continuity more explicitly
- reducing the current flatness of memory and injected context

---

## What Pulse is trying to become

Over time, Pulse aims to become a local system that can:
- better recognize what work is actually happening
- better connect the present, the recent past, and memory
- make better proposals at the right time
- eventually open the door to controlled forms of action

But that target is not the present.

Today, Pulse is mainly:
- a local observation layer
- a context structure
- a simple but useful memory
- a user control layer around AI tools

That is exactly what makes it credible at this stage.
