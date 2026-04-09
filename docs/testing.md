# Pulse Testing

This document defines the current test battery for Pulse.

## Automated Tests

Run the full non-interactive Python suite:

```bash
cd /path/to/Pulse
./scripts/test_all.sh
```

What it covers:
- command interpreter
- signal scorer
- decision engine
- state store
- MCP handlers
- session memory
- memory extraction
- runtime settings persistence

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
- Verify the top status indicator changes between:
  - `Pulse observe`
  - `Observation paused`
  - `Daemon inactif`

### Settings

- Open settings from the gear icon.
- Verify `Réglages` appears in the top bar.
- Verify both model pickers are visible:
  - `Command model`
  - `Summary model`
- Change each model and restart Pulse to confirm persistence.
- Use refresh and verify the models list updates.

### Context

- Press `Cmd+Option+Shift+C`.
- Verify the notch shows the copy feedback.
- Paste into a text field and confirm the snapshot starts with `# Pulse Context Snapshot`.

### Observation

- Modify a real `.swift` or `.py` file.
- Confirm `Project` and `Active file` update in the copied context.
- Toggle observation off and verify file/app activity stops updating.

### Session Memory

- Work for at least 20 minutes with Pulse active.
- Trigger an idle period or lock the screen.
- Verify memory files exist:

```bash
ls ~/.pulse/memory
ls ~/.pulse/memory/sessions
```

- Verify:
  - `habits.md`
  - `projects.md`
  - a dated file under `sessions/`

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
