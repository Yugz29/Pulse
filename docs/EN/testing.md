# Pulse Testing

This document defines the current test battery for Pulse.

## Testing Philosophy

Pulse tests are used for three different purposes:

- `Unit tests`: verify local logic in isolation
- `Integration tests`: verify that modules still work together through the real pipeline
- `Contract tests`: verify that specific public or legacy-compatible outputs do not change

Contract tests are not optional cleanup tests. They are structural guarantees.

Rule:

> If a test asserts exact output, any change is a breaking change.

## Automated Tests

Run the full non-interactive Python suite:

```bash
cd /path/to/Pulse
./scripts/test_all.sh
```

This is the canonical entrypoint for daemon tests:
- uses the project venv instead of the macOS system Python
- fails fast if the interpreter is older than Python 3.11
- avoids false negatives caused by running the suite with `/usr/bin/python3`

What it covers:
- command interpreter
- signal scorer
- decision engine
- state store
- `PresentState`, `CurrentContext` builders and legacy adapters
- `SessionSnapshot` builders and legacy adapters
- `work_blocks`, `work_block_*`, `recent_sessions`, and related legacy aliases
- `ProposalCandidate` adapters
- `SessionFSM`
- runtime state matrix (`/ping`, `/state`, `/event`, `/insights`)
- MCP handlers
- session memory
- commit / multi-cluster activity window correlation
- FactEngine (facts, reinforce, contradict, decay, archive)
- memory extractor (cooldown, journal, projects)
- git diff module
- `/facts` API routes
- runtime orchestrator
- LLM availability matrix
- deterministic and LLM Resume Cards
- Resume Card debug routes
- context probes and approval/refusal transitions

## Contract Locking Tests

Some outputs are now explicitly frozen through golden or exact-match tests.

These tests exist to prevent structural regressions during refactors. They are not
"nice to have" checks.

Current locked outputs include:
- `build_context_snapshot()` -> exact Markdown output
- `/state` -> exact JSON output (`present` canonical core + compat/debug)
- `export_session_data()` -> exact legacy dict output
- proposal generation output -> exact payload / structure / evidence output

Important:
- legacy `/state` fields may be tested for compatibility
- they must not be used as the basis of new features

The same rule applies to memory migration:
- `work_blocks`, `work_block_*`, and `recent_sessions` are the canonical fields;
- `work_window_*` and `closed_episodes` may remain tested only as temporary legacy aliases;
- a legacy test must be explicitly named as such.

These tests are used when Pulse must preserve behavior while changing internal
structure. If one of these assertions fails, the default assumption is that the
change is breaking until proven otherwise.

## Core Artifacts Under Test

The current runtime foundation introduces several structural artifacts that are now
tested directly:

- `PresentState`
- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`
- `ResumeCard`
- `work_blocks` / `work_block_*`
- `ContextProbeRequest`

They are not tested to justify behavior drift. They are tested to lock:
- compatibility
- invariants
- legacy output stability
- session lifecycle consistency

Typical expectations:
- a builder can replace inline assembly without changing output
- a legacy adapter reproduces the exact previous contract
- `RuntimeState.present` remains the canonical truth of the present
- the session lifecycle has a single source of truth
- Resume Cards remain context recovery projections and keep a deterministic fallback
- context probes remain gated by validation and redaction
- memory legacy aliases do not become canonical fields
- a candidate-to-transport conversion does not mutate the final external payload

## Resume Card Tests

The Resume Card is tested as a context recovery projection, not as a source of truth.

Locked points:
- deterministic generation usable without an LLM;
- deterministic fallback if the LLM is unavailable, invalid, or does not produce a final answer;
- debug diagnostics on `/debug/resume-card/llm`;
- modern sources (`PresentState`, `work_block_*`, `recent_sessions`, recent journal entries) preferred over legacy aliases;
- `generated_by` distinguishes `deterministic` from `llm`.

Useful debug routes:

```bash
curl -s -X POST http://127.0.0.1:8765/debug/resume-card \
  -H "Content-Type: application/json" \
  -d '{"sleep_minutes":35}' | python -m json.tool

curl -s -X POST http://127.0.0.1:8765/debug/resume-card/llm \
  -H "Content-Type: application/json" \
  -d '{"sleep_minutes":35}' | python -m json.tool
```

Check in the LLM response:
- `llm_available`
- `debug.llm_called`
- `debug.fallback_reason`
- `debug.raw_preview`
- `card.generated_by`

The prepared Resume Card (`prepared_resume_card`) does not yet have a dedicated debug route for `prepare` / `peek` / `consume` / `expire`.
It must still be validated mainly in the field through a real lock/unlock cycle.

## Interactive E2E

The MCP smoke test is intentionally separate because it requires a live daemon:

It simulates the `daemon.mcp.stdio_server` MCP bridge and verifies the real `stdio -> /mcp/intercept -> /mcp/pending -> /mcp/decision` flow.

```bash
cd /path/to/Pulse
.venv/bin/python3 tests/test_e2e.py
```

Optional custom command:

```bash
.venv/bin/python3 tests/test_e2e.py "find . -type f -name \"*.swift\" | head"
```

## Manual UI Checklist

### Dashboard

- Open and close the notch.
- Verify the dashboard appears first.
- Verify the dashboard shows the current context card:
  - active app or project
  - active file
  - task, focus, session
  - friction badge
- Verify the input bubble stays fully inside the expanded notch panel.
- Send a message and verify the UI switches to chat mode.

### Services

- Open `Services` from the health icon.
- Verify the daemon row supports:
  - start
  - pause
  - resume
  - stop
  - restart
- Verify the observation row can be paused/resumed independently.
- Verify the `LLM` row shows:
  - current availability
  - refresh button
  - model chooser menu
- Change the command and summary models and restart Pulse to confirm persistence.

### Settings

- Open settings from the gear icon.
- Verify `Réglages` appears in the top bar.
- Verify the view only contains secondary/runtime guidance and no longer duplicates the LLM controls.

### Chat

- Send a message from the dashboard.
- Verify the panel switches to chat mode and shows:
  - loading state
  - final response
- Verify the close button exits chat back to the dashboard.
- Verify no control is rendered inside the physical notch area.

### Context

- Press `Cmd+Option+Shift+C`.
- Verify the notch shows the copy feedback.
- Paste into a text field and confirm the snapshot starts with `# Pulse Context Snapshot`.

### Observation

- Open `Observation` from the eye icon.
- Verify the panel shows only recent activity rows.
- Verify each activity row displays:
  - icon
  - main value
  - secondary description
  - relative timestamp
- Modify a real `.swift` or `.py` file.
- Confirm `Project` and `Active file` update in the copied context.
- Toggle observation off and verify file/app activity stops updating.

### Session Memory

- Work for at least 20 minutes with Pulse active.
- Trigger an idle period or lock the screen (or make a git commit).
- Verify memory files exist:

```bash
ls ~/.pulse/memory
ls ~/.pulse/memory/sessions
```

- Verify:
  - `facts.md` (profil utilisateur export)
  - `projects.md`
  - a dated file under `sessions/` (e.g. `2026-04-13.md`)
  - `~/.pulse/facts.db` exists and contains active facts

- Check the facts API:

```bash
curl http://127.0.0.1:8765/facts
curl http://127.0.0.1:8765/facts/profile
```

### Prepared Resume Card

- Work long enough to create real context.
- Lock the screen.
- Check daemon logs for a prepared card:

```bash
tail -n 120 ~/.pulse/logs/daemon.stdout.log ~/.pulse/logs/daemon.error.log | grep prepared_resume_card
```

- Unlock after a sufficient pause.
- Verify the Resume Card appears quickly in the notch.
- Check logs for:
  - `prepared_resume_card stored`
  - `prepared_resume_card emitted`
- If no valid prepared card exists, verify the classic fallback path still works.

## LaunchAgent Checks

Verify the daemon autostart is loaded:

```bash
launchctl list | grep cafe.pulse.daemon
ps aux | grep '[d]aemon.main'
```

Check logs if needed:

```bash
tail -n 80 ~/.pulse/logs/daemon.error.log ~/.pulse/logs/daemon.stdout.log
```
