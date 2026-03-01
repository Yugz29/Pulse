# Pulse – Technical Report

---

## 1️⃣ Project Summary

**Concept:**
Pulse is an intelligent desktop-resident agent designed as a proactive entity capable of monitoring code, analyzing metrics, and learning from developer interactions. In the long term, Pulse will evolve into a cybersecurity guardian capable of detecting threats and vulnerabilities on the local machine.

**Objectives:**
- Reduce development errors and improve code quality.
- Provide proactive feedback and suggestions.
- Enable adaptive learning based on developer behavior.
- Build a scalable architecture toward cybersecurity and controlled autonomy.

**Target Users:**
- Individual developers seeking an intelligent, always-on assistant.
- Multi-language projects: TypeScript, JavaScript, Python.
- Secure local desktop usage, with potential expansion to multi-project management and cybersecurity features.

---

## 2️⃣ Core Features

| Feature | Status | Description |
|---------|--------|-------------|
| **File Watcher** | ✅ Done | Monitors project files in real time via chokidar. Exclusions driven by `pulse.config.json`. Debounced 1500ms. Filters on supported extensions (`.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.py`). |
| **Analyzer / Parser** | ✅ Done | TS/JS via ts-morph (AST). Python via regex fallback. Measures cyclomatic complexity, function size, nesting depth, and parameter count per function. Anonymous functions excluded from metrics (double-counting). |
| **Churn Metric** | ✅ Done | Single Git call per scan — builds a cache of commit counts per file (last 30 days). 1 call for all files instead of 1 per file. |
| **Coupling (Fan-in / Fan-out)** | ✅ Done | Static import graph built after each scan. Fan-in = number of files that import this file. Fan-out = number of files this file imports. Displayed in sidebar, not included in RiskScore. |
| **RiskScore Calculator** | ✅ Done | Weighted score per file (0–100) across 5 metrics: complexity 35%, depth 20%, function size 20%, churn 15%, parameters 10%. |
| **Database / Persistence** | ✅ Done | SQLite via better-sqlite3. Stores scan history, function-level metrics, and feedbacks. Scoped per project via `project_path`. Auto-cleans deleted files at startup. |
| **Score Trends** | ✅ Done | Displays score evolution (↑↓↔) compared to previous scan. |
| **Score History Graph** | ✅ Done | SVG inline chart showing score evolution over time (up to 30 points) per file. Displayed in sidebar. |
| **Feedback Loop V1** | ✅ Done | Stores `apply / ignore / explore` actions per file in SQLite. Buttons in sidebar. Feedback history passed to LLM context. |
| **LLM Module (V1.5)** | ✅ Done | Local AI analysis via Ollama (`qwen2.5-coder:7b`). Triggered by the `explore` action. Enriched context: source code, metrics, functions, import graph, score history, feedback history. Streamed response rendered as markdown in sidebar. |
| **Config File** | ✅ Done | `pulse.config.json` centralizes project path, alert thresholds, and ignore list. Sensible defaults if fields are missing. |
| **Electron UI** | ✅ Done | Desktop app with file list, risk scores, trends, feedbacks. Sidebar with two tabs (Métriques / Analyse), resizable by dragging (260px–700px). |
| **Multi-Project Support** | ✅ Done | Each scan scoped by `project_path`. Multiple projects coexist in the same DB without mixing. |
| **Function-Level Detail** | ✅ Done | Per-function metrics stored in DB and displayed in sidebar: name, start line, line count, cyclomatic complexity, parameter count, nesting depth. |
| **Auto-cleanup** | ✅ Done | At startup, Pulse removes from DB any file that no longer exists on disk. |
| **Git Sandbox** | 📋 Planned V2 | Creates an isolated branch to apply and test modifications before final validation. |
| **Feedback Loop V2** | 📋 Planned V2 | Dynamic adjustment of RiskScore weights based on feedback patterns. |

---

## 3️⃣ Secondary / Nice-to-Have Features

| Feature | Description |
|---------|-------------|
| **System Notifications** | Proactive alerts displayed on desktop. |
| **Full Electron Dashboard** | Advanced interactive dashboard with graphs, clickable alerts, and detailed diff views. |
| **Export / Import Configuration** | Rules and profiles in JSON/YAML for sharing or backup. |
| **Controlled Autonomy** | Semi-automatic proposals executable after validation or via configurable auto-actions. |
| **Cybersecurity (advanced phase)** | Log analysis, vulnerability detection, local network monitoring. |

---

## 4️⃣ Technical Architecture

### Frontend (Desktop UI)
- **Electron + React** — cross-platform desktop ✅
- File list, risk scores, trends, function detail sidebar ✅
- Resizable sidebar (drag to resize, 260px–700px) ✅
- Tabbed sidebar: **Métriques** (metrics + graph + functions + feedback buttons) / **Analyse** (LLM response) ✅

### Backend / Core
- Node.js + TypeScript daemon
- Modules: File Watcher ✅, Analyzer ✅, Churn ✅, Coupling ✅, RiskScore ✅, Feedback Loop V1 ✅, LLM ✅, Config ✅, Auto-cleanup ✅
- Git Sandbox — 📋 V2

### Database
- **SQLite / better-sqlite3** ✅
- Tables: `scans` ✅, `feedbacks` ✅, `functions` ✅
- Per-project scoping via `project_path` ✅
- Auto-migration on startup ✅

### LLM / AI
- **Ollama local** (`qwen2.5-coder:7b-instruct-q4_K_M`) ✅
- Streamed via `http://localhost:11434/api/generate`
- Enriched prompt: source code + metrics + top functions + import graph + score history + feedback history
- Response rendered as markdown in sidebar (Analyse tab)

---

## 5️⃣ Tech Stack

| Component | Tech | Status |
|-----------|------|--------|
| Runtime | Node.js + TypeScript | ✅ |
| Desktop UI | Electron + React | ✅ |
| File Watching | chokidar | ✅ |
| TS/JS Analysis | ts-morph (AST) | ✅ |
| Python Analysis | Regex | ✅ |
| Churn / Git | simple-git | ✅ |
| Database | better-sqlite3 | ✅ |
| Config | pulse.config.json | ✅ |
| Markdown rendering | marked | ✅ |
| LLM | Ollama (qwen2.5-coder:7b) | ✅ |
| Visualization | Chart.js | V2 |

---

## 6️⃣ Data Model

### Tables (SQLite)

**scans**
- id, file_path, global_score, complexity_score, function_size_score, churn_score, depth_score, param_score, fan_in, fan_out, language, project_path, scanned_at

**feedbacks**
- id, file_path, action (`apply` / `ignore` / `explore`), risk_score_at_time, created_at

**functions**
- id, file_path, name, start_line, line_count, cyclomatic_complexity, parameter_count, max_depth, project_path, scanned_at

### Planned Tables (V2+)
**alerts** — id, file_path, type, score, status, created_at
**proposals** — id, alert_id, diff_content, score_before, score_after, status, created_at

---

## 7️⃣ pulse.config.json

```json
{
    "projectPath": "/path/to/your/project",
    "thresholds": {
        "alert": 50,
        "warning": 20
    },
    "ignore": [
        "node_modules", ".git", "dist", "build", ".vite",
        "vendor", "__pycache__", "venv", ".venv", "coverage"
    ]
}
```

All fields have sensible defaults if omitted.

---

## 8️⃣ Main User Flows

### Flow 1: Startup Scan ✅
1. Pulse loads `pulse.config.json`
2. Database initialized — migrations applied automatically, deleted files cleaned
3. Scanner recursively reads all supported files (respecting ignore list)
4. Each file parsed → metrics computed (complexity, size, depth, params, churn)
5. Import graph built → fan-in / fan-out injected into results
6. All results saved to DB
7. UI displays ranked report with risk levels, trends, and last feedback

### Flow 2: Live Watching ✅
1. File modified → chokidar detects change (debounced 1500ms)
2. Analyzer computes AST metrics + churn
3. RiskScore calculated
4. UI updated in real time

### Flow 3: Feedback Loop V1 ✅
1. Developer selects action (`apply / ignore / explore`) from sidebar
2. Action stored in SQLite with score at time of feedback
3. UI report shows last feedback per file

### Flow 4: LLM Analysis ✅
1. Developer clicks **explore** in sidebar
2. Pulse reads the source file + collects enriched context (metrics, functions, importedBy, score history, feedback history)
3. Prompt sent to local Ollama instance (streaming)
4. Response streamed to **Analyse** tab in sidebar, rendered as markdown

### Flow 5: Git Sandbox 📋 (V2)
1. Proposal applied in Git sandbox branch
2. Human validation or automatic rollback

---

## 9️⃣ RiskScore Weights

| Metric | Weight | Safe threshold | Danger threshold |
|--------|--------|----------------|-----------------|
| Cyclomatic complexity | 35% | ≤ 3 | ≥ 10 |
| Nesting depth | 20% | ≤ 2 | ≥ 5 |
| Function size (lines) | 20% | ≤ 20 | ≥ 60 |
| Churn (commits/30d) | 15% | ≤ 5 | ≥ 20 |
| Parameter count | 10% | ≤ 3 | ≥ 7 |

Score ranges: 🟢 < 20 · 🟡 20–49 · 🔴 ≥ 50

**Notes:**
- Anonymous functions are excluded from all metric calculations (already counted within their parent function).
- Fan-in / fan-out are informational only — not included in the RiskScore.

---

## 🔟 Technical Constraints & Security

- **100% local execution** for privacy — no data leaves the machine
- LLM strictly local via Ollama — no cloud API calls
- Filesystem exclusions driven by config
- Limited permissions: no root access
- Scan history preserved across sessions — no data loss on restart
- Deleted files automatically removed from DB at startup

---

## 11️⃣ Development Phases

| Phase | Features |
|-------|----------|
| **V1** ✅ | Electron UI, file scanning, RiskScore (5 metrics), SQLite persistence, function-level metrics, coupling graph, live watcher, debouncing, feedback loop, score trends, score history graph, config file, multi-project support, auto-cleanup |
| **V1.5** ✅ | LLM module (Ollama local), enriched context, streamed markdown response, resizable sidebar, tabbed sidebar (Métriques / Analyse) |
| **V2** | System notifications, dynamic feedback weights, DeveloperProfile, Git Sandbox, Chart.js advanced dashboard |
| **V3** | Semi-autonomous suggestions, cybersecurity (logs, vulnerabilities, network monitoring), controlled autonomy |

---

## 12️⃣ Complexity Estimate per Module

| Module | Complexity | Status |
|--------|-----------|--------|
| File Watcher | Low | ✅ Done |
| Analyzer / Parser (TS/JS) | Medium | ✅ Done |
| Analyzer / Parser (Python) | Low | ✅ Done |
| Churn Metric | Low | ✅ Done |
| Coupling (Fan-in / Fan-out) | Low | ✅ Done |
| RiskScore Calculator | Low | ✅ Done |
| Database / Persistence | Low | ✅ Done |
| Auto-cleanup | Low | ✅ Done |
| Score Trends | Low | ✅ Done |
| Score History Graph (SVG) | Low | ✅ Done |
| Electron UI | Medium | ✅ Done |
| Resizable Sidebar | Low | ✅ Done |
| Tabbed Sidebar | Low | ✅ Done |
| Function-Level Detail | Low | ✅ Done |
| Multi-Project Support | Low | ✅ Done |
| Feedback Loop V1 | Low | ✅ Done |
| LLM Module (Ollama) | Medium | ✅ Done |
| Git Sandbox | High | 📋 V2 |
| Feedback Loop V2 (dynamic weights) | Medium | 📋 V2 |
