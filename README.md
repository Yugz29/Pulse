# Pulse – Technical Report

---

## 1️⃣ Project Summary

**Concept:**  
Pulse is an intelligent desktop-resident agent designed as a proactive entity capable of monitoring code, analyzing metrics, suggesting improvements, testing modifications in a sandboxed environment, and learning from developer interactions. In the long term, Pulse will evolve into a cybersecurity guardian capable of detecting threats and vulnerabilities on the local machine.

**Objectives:**  
- Reduce development errors and improve code quality.  
- Provide proactive feedback and suggestions.  
- Maintain a secure environment through sandboxing.  
- Enable adaptive learning based on developer behavior.  
- Build a scalable architecture toward cybersecurity and controlled autonomy.  

**Target Users:**  
- Individual developers seeking an intelligent, always-on assistant.  
- Multi-language projects, primarily Python and JavaScript/TypeScript.  
- Secure local desktop usage, with potential expansion to multi-project management and cybersecurity features.  

---

## 2️⃣ Core Features

| Feature | Status | Description |
|---------|--------|-------------|
| **File Watcher** | ✅ Done | Monitors project files in real time via chokidar. Exclusions driven by `pulse.config.json`. Debounced to avoid duplicate triggers. |
| **Analyzer / Parser** | ✅ Done | Analyzes JS/TS code via AST (ts-morph). Measures cyclomatic complexity and function size per file. |
| **Churn Metric** | ✅ Done | Counts recent commits per file via simple-git (last 30 days). Integrated into RiskScore weighting. |
| **RiskScore Calculator** | ✅ Done | Weighted score per file (0–100): complexity 50%, function size 30%, churn 20%. |
| **Database / Persistence** | ✅ Done | Stores scan history and feedbacks in SQLite via better-sqlite3. |
| **Score Trends** | ✅ Done | Displays score evolution (↑↓↔) compared to previous scan using DB history. |
| **CLI / Initial Report** | ✅ Done | Scans project at startup. Ranked report with risk levels (🔴🟡🟢), trends, and feedback history. |
| **Feedback Loop V1** | ✅ Done | Interactive prompt after report and on proactive alerts. Stores `apply / ignore / explore` actions in SQLite. |
| **Proactive Alerts** | ✅ Done | Real-time alert during watch when a file exceeds `thresholds.alert`. Watcher paused during prompt to avoid stdin interference. |
| **Config File** | ✅ Done | `pulse.config.json` centralizes project path, alert thresholds, and ignore list. |
| **Git Sandbox** | 📋 Planned V2 | Creates an isolated branch to apply and test modifications before final validation. |
| **LLM Module** | 📋 Planned V1.5 | Provides intelligent explanations and suggestions for alerts. Runs locally via Ollama for privacy. |

---

## 3️⃣ Secondary / Nice-to-Have Features

| Feature | Description |
|---------|-------------|
| **System Notifications** | Proactive alerts and messages displayed on desktop. |
| **Multi-Project Support** | Manage multiple projects simultaneously with independent profiles. |
| **Full Electron Interface** | Advanced interactive dashboard with graphs, clickable alerts, and detailed diff views. |
| **Export / Import Configuration** | Rules and profiles in JSON/YAML for sharing or backup. |
| **Controlled Autonomy** | Semi-automatic proposals executable after validation or via configurable auto-actions. |
| **Cybersecurity (advanced phase)** | Log analysis, vulnerability detection, local network monitoring. |

---

## 4️⃣ Technical Architecture

### Frontend (Desktop UI)
- **Electron** for cross-platform desktop (V2+)
- **React + Chart.js** for interactive dashboard (V2+)
- Minimal CLI for V1 ✅

### Backend / Core
- Node.js + TypeScript daemon
- Modules: File Watcher ✅, Analyzer ✅, Churn ✅, RiskScore ✅, CLI ✅, Feedback Loop ✅, Config ✅, Git Sandbox 📋

### Database
- **SQLite / Better SQLite3** ✅
- Tables: `scans` ✅, `feedbacks` ✅

### LLM / AI
- Ollama or local LLaMA (optional V1.5+)

---

## 5️⃣ Tech Stack

| Component | Tech | Status |
|-----------|------|--------|
| Runtime | Node.js + TypeScript | ✅ |
| File Watching | chokidar | ✅ |
| Code Analysis | ts-morph | ✅ |
| Churn / Git | simple-git | ✅ |
| Database | better-sqlite3 | ✅ |
| Config | pulse.config.json | ✅ |
| Desktop UI | Electron + React | V2 |
| LLM | Local Ollama | V1.5 |
| Visualization | Chart.js | V2 |

---

## 6️⃣ Data Model

### Current Tables (SQLite)

**scans**
- id, file_path, global_score, complexity_score, function_size_score, scanned_at

**feedbacks**
- id, file_path, action (`apply` / `ignore` / `explore`), risk_score_at_time, created_at

### Planned Tables (V2+)

**projects** — id, name, path, last_scan  
**alerts** — id, file_path, type, score, status, created_at  
**proposals** — id, alert_id, diff_content, score_before, score_after, status, created_at  

---

## 7️⃣ Main User Flows

### Flow 1: Startup Scan ✅
1. Pulse loads `pulse.config.json`
2. Database initialized
3. Scanner recursively reads all JS/TS files (respecting ignore list)
4. Each file is parsed, scored (complexity + size + churn), compared to previous scan
5. CLI displays ranked report with risk levels, trends, and last feedback

### Flow 2: Live Watching ✅
1. File modified → chokidar detects change (debounced 500ms)
2. Analyzer computes AST metrics + churn
3. RiskScore calculated
4. If score ≥ `thresholds.alert` → proactive alert + interactive prompt
5. Feedback saved to SQLite

### Flow 3: Feedback Loop V1 ✅
1. Developer selects action (`apply / ignore / explore / skip`) from CLI
2. Action stored in SQLite with score at time of feedback
3. CLI report shows last feedback per file
4. *(V2)* Dynamic weight adjustment based on feedback patterns

### Flow 4: Git Sandbox 📋 *(V2)*
1. Proposal applied in Git sandbox branch
2. Human validation or automatic rollback

### Flow 5: LLM Interactions 📋 *(V1.5)*
1. Developer requests explanation
2. Local LLM returns contextualized explanation of alert / proposal

---

## 8️⃣ pulse.config.json

```json
{
    "projectPath": "/path/to/your/project",
    "thresholds": {
        "alert": 50,
        "warning": 20
    },
    "ignore": ["node_modules", ".git", "dist", ".vite", "static", "vendor", "__pycache__"]
}
```

---

## 9️⃣ Technical Constraints & Security

- **100% local execution** for privacy
- LLM strictly local and optional
- Filesystem exclusions driven by config: `node_modules`, `.git`, `dist`, `.vite`, etc.
- Limited permissions: no root access
- Watcher paused during interactive prompts to avoid stdin conflicts

---

## 🔟 Development Phases

| Phase | Features |
|-------|----------|
| **V1** ✅ | CLI, file scanning, RiskScore (complexity + size + churn), SQLite persistence, live watcher, debouncing, proactive alerts, feedback loop, score trends, config file |
| **V2** | Electron UI, interactive dashboard with Chart.js, system notifications, dynamic feedback weights, DeveloperProfile, multi-project support, Git Sandbox |
| **V3** | Full LLM integration, semi-autonomous suggestions, cybersecurity (logs, vulnerabilities, network monitoring), controlled autonomy |

---

## 11️⃣ Complexity Estimate per Module

| Module | Complexity | Status |
|--------|-----------|--------|
| File Watcher | Low | ✅ Done |
| Analyzer / Parser | Medium | ✅ Done |
| Churn Metric | Low | ✅ Done |
| RiskScore Calculator | Low | ✅ Done |
| Database / Persistence | Low | ✅ Done |
| Score Trends | Low | ✅ Done |
| CLI / Report | Low | ✅ Done |
| Feedback Loop V1 | Low | ✅ Done |
| Proactive Alerts | Low | ✅ Done |
| Config File | Low | ✅ Done |
| Git Sandbox | High | 📋 V2 |
| Electron UI | High | V2 |
| Feedback Loop V2 (dynamic weights) | Medium | V2 |
| LLM Module | Medium → High | V1.5 |
