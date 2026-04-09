# Pulse

Pulse is a local-first ambient layer between you and AI tools on macOS.

It combines:
- a Swift macOS app that lives around the notch,
- a Python daemon that observes system activity and intercepts risky commands,
- a local memory/context layer that can later be injected into AI conversations.

## Current Scope

Pulse currently includes:
- a SwiftUI notch app,
- a Python daemon exposed over `http://localhost:8765`,
- MCP command interception for Claude Code,
- command interpretation and risk scoring,
- local session memory in SQLite,
- markdown memory extraction (`projects.md`, `habits.md`).

## Project Structure

```text
Pulse/
├── App/                 # Swift macOS app
├── daemon/              # Python daemon
├── tests/               # Python tests
└── test_e2e.py          # End-to-end MCP smoke test
```

## Running Locally

### Python daemon

Create and activate a virtual environment, then run the daemon:

```bash
cd Pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r daemon/requirements.txt
python3 daemon/main.py
```

The daemon serves:
- `GET /ping`
- `POST /event`
- `GET /state`
- `GET /context`
- MCP-related routes under `/mcp/*`

### Swift app

Open the Xcode project in `App/App.xcodeproj`, then run the macOS app.

The app:
- renders the notch UI,
- polls the daemon,
- observes apps/filesystem/clipboard,
- sends events to the daemon.

## Tests

Run the Python test suite:

```bash
cd Pulse
python3 -m pytest tests -q
```

There is also an end-to-end script:

```bash
python3 test_e2e.py
```

For the current test battery and manual validation checklist, see `docs/testing.md`.

## Memory Output

Pulse writes local runtime memory under:

```text
~/.pulse/
├── session.db
└── memory/
    ├── MEMORY.md
    ├── habits.md
    ├── projects.md
    └── sessions/
```

## Status

Implemented:
- command interpreter,
- MCP interception flow,
- notch UI shell,
- signal scorer,
- decision engine,
- SQLite session memory,
- markdown memory extraction.

Still in progress:
- richer context injection,
- LLM routing for unknown commands and summaries,
- startup automation and final polish.

## LaunchAgent

For a stable login-time startup during development, Pulse now includes:
- a daemon launcher script at `scripts/start_pulse_daemon.sh`,
- a launchd plist template at `launchd/cafe.pulse.daemon.plist`,
- an installer script at `scripts/install_launch_agent.sh`.

This autostart flow currently targets the Python daemon. The notch app is still run from Xcode during development, so its bundle path is not stable enough yet for a robust login-time launch.

The included scripts resolve the repository path dynamically, so they keep working even if Pulse is cloned into a different folder.
