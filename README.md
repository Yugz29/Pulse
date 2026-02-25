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
| **File Watcher** | ✅ Done | Monitors project files and folders in real time (excluding `node_modules`, `.git`, `dist`, `.vite`, `static`, etc.) to detect changes. |
| **Analyzer / Parser** | ✅ Done | Analyzes JS/TS code via AST (ts-morph), measures cyclomatic complexity and function size. |
| **RiskScore Calculator** | ✅ Done | Combines weighted metrics (complexity 60%, function size 40%) to generate a risk score per file (0–100). |
| **Database / Persistence** | ✅ Done | Stores scan history and feedbacks in SQLite via better-sqlite3. |
| **CLI / Initial Report** | ✅ Done | Scans a project at startup and displays a ranked report with risk levels (🔴🟡🟢) and feedback history. |
| **Feedback Loop V1** | ✅ Done | Stores developer actions (`apply`, `ignore`, `explore`) per file in SQLite. Displays last feedback in CLI report. |
| **Config File** | 🔄 In Progress | `pulse.config.json` to replace hardcoded paths and centralize thresholds. |
| **Score Trends** | 🔄 In Progress | Display score evolution (↑↓) compared to previous scan using existing DB history. |
| **Churn Metric** | 📋 Planned | Count recent commits per file via simple-git to enrich RiskScore. |
| **Proactive Alerts** | 📋 Planned | Real-time alerts during watch when a file exceeds critical thresholds, with immediate action prompt. |
| **Git Sandbox** | 📋 Planned V2 | Creates an isolated branch to apply and test modifications before final validation. |
| **LLM Module** | 📋 Planned V1.5 | Provides intelligent explanations and suggestions for alerts. Runs locally via Ollama for privacy. |

---

## 3️⃣ Secondary / Nice-to-Have Features

| Feature | Description |
|---------|-------------|
| **System Notifications** | Proactive alerts and messages displayed on desktop. |
| **Multi-Project Support** | Manage multiple projects simultaneously with independent profiles. |
| **Full Electron Interface** | Advanced interactive dashboard with clickable alerts and detailed diff views. |
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
- Node.js + TypeScript daemon supervising filesystem and AI module
- Modules: File Watcher ✅, Analyzer ✅, RiskScore ✅, CLI ✅, Feedback Loop ✅, Config 🔄, Trends 🔄, Churn 📋, Git Sandbox 📋

### Database
- **SQLite / Better SQLite3** for local persistence ✅
- Storage: scans history ✅, feedbacks ✅

### LLM / AI
- Ollama or local LLaMA (optional V1.5+) for intelligent explanations and suggestions

---

## 5️⃣ Tech Stack

| Component | Tech | Status |
|-----------|------|--------|
| Runtime | Node.js + TypeScript | ✅ |
| File Watching | chokidar | ✅ |
| Code Analysis | ts-morph | ✅ |
| Database | better-sqlite3 | ✅ |
| Config | pulse.config.json | 🔄 |
| Churn / Git | simple-git | 📋 |
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
1. Pulse loads `pulse.config.json` for project path and thresholds
2. Database initialized
3. Scanner recursively reads all JS/TS files (excluding generated/vendor files)
4. Each file is parsed, scored, and compared to previous scan (trend)
5. CLI displays ranked report with risk levels and feedback history

### Flow 2: Live Watching ✅
1. File modified → File Watcher detects change
2. Analyzer computes AST metrics
3. RiskScore Calculator generates score
4. If score exceeds alert threshold → proactive prompt shown
5. Terminal displays updated metrics

### Flow 3: Feedback Loop V1 ✅
1. Developer selects action (`apply / ignore / explore`) from CLI
2. Action stored in SQLite with score at time of feedback
3. CLI report shows feedback history per file
4. *(V2)* Dynamic weight adjustment based on feedback patterns

### Flow 4: Churn Analysis 📋
1. simple-git counts recent commits per file
2. Churn score added to RiskScore weighting
3. High churn + high complexity = elevated risk

### Flow 5: Git Sandbox 📋 *(V2)*
1. Proposal applied in Git sandbox branch
2. Human validation or automatic rollback

### Flow 6: LLM Interactions 📋 *(V1.5)*
1. Developer requests explanation
2. Local LLM returns contextualized explanation of alert / proposal

---

## 8️⃣ Technical Constraints & Security

- **100% local execution** for privacy
- LLM strictly local and optional
- Filesystem exclusions for performance: `node_modules`, `.git`, `dist`, `.vite`, `static`, `vendor`, `__pycache__`
- Limited permissions: no root access in V1
- Config file (`pulse.config.json`) for project-specific settings

---

## 9️⃣ Development Phases

| Phase | Features |
|-------|----------|
| **V1** *(current)* | ✅ CLI, file scanning, RiskScore, SQLite persistence, live watcher, feedback loop — 🔄 Config file, score trends — 📋 Churn metric, proactive alerts |
| **V2** | Electron UI, system notifications, dynamic feedback weights, DeveloperProfile, multi-project support, Git Sandbox |
| **V3** | Full LLM integration, semi-autonomous suggestions, cybersecurity (logs, vulnerabilities, network monitoring), controlled autonomy |

---

## 🔟 Complexity Estimate per Module

| Module | Complexity | Status |
|--------|-----------|--------|
| File Watcher | Low | ✅ Done |
| Analyzer / Parser | Medium | ✅ Done |
| RiskScore Calculator | Low | ✅ Done |
| Database / Persistence | Low | ✅ Done |
| CLI / Report | Low | ✅ Done |
| Feedback Loop V1 | Low | ✅ Done |
| Config File | Low | 🔄 In Progress |
| Score Trends | Low | 🔄 In Progress |
| Churn Metric | Medium | 📋 Planned |
| Proactive Alerts | Low | 📋 Planned |
| Git Sandbox | High | 📋 V2 |
| Electron UI | Medium | V2 |
| Feedback Loop V2 (dynamic weights) | Medium | V2 |
| LLM Module | Medium → High | V1.5 |
