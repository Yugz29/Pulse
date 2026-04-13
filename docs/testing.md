# Pulse Testing

This document defines the current test battery for Pulse.

## Automated Tests

Run the full non-interactive Python suite:

```bash
cd /path/to/Pulse
.venv/bin/python -m unittest discover -s tests -v
```

What it covers:
- command interpreter
- signal scorer
- decision engine
- state store
- runtime state matrix (`/ping`, `/state`, `/event`, `/insights`)
- MCP handlers
- session memory
- FactEngine (facts, reinforce, contradict, decay, archive)
- memory extractor (cooldown, journal, projects)
- git diff module
- `/facts` API routes
- runtime orchestrator
- LLM availability matrix

## Interactive E2E

The MCP smoke test is intentionally separate because it requires a live daemon:

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
