# Pulse – Provisional Technical Report

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
- Multi-language projects, primarily Python and JavaScript.  
- Secure local desktop usage, with potential expansion to multi-project management and cybersecurity features.  

---

## 2️⃣ Core Features

| Feature | Description |
|---------|-------------|
| **File Watcher** | Monitors project files and folders in real time (excluding `node_modules/.git/dist`) to detect changes. |
| **Analyzer / Rule Engine V1** | Analyzes code via AST, measures cyclomatic complexity, function size, modification frequency (churn), and other metrics. Generates alerts and proposals based on initial static rules. |
| **RiskScore Calculator** | Combines weighted metrics to generate a risk score per file. Triggers alerts when thresholds are exceeded. |
| **Git Sandbox** | Creates an isolated project branch to apply and test modifications before final validation. Manages lifecycle (creation, merge/rebase, proposal TTL). |
| **Feedback Loop** | Adjusts rule weights based on developer actions (`apply`, `ignore`, `explore`) using learning rate and bounds. Stores history for auditing. |
| **DeveloperProfile** | Per-project developer profile storing statistics (acceptance rate, average score delta). |
| **CLI / Minimal Dashboard** | Interface to display RiskScore, proposals, alerts, and feedback. JSON dashboard with visualizations via `Chart.js`. |
| **LLM Module (optional V1.5)** | Provides intelligent explanations and suggestions for alerts and proposals. Runs locally for privacy. |
| **Logger / Persistence** | Complete history of actions, alerts, proposals, and scores stored in SQLite / Better SQLite3. |

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

## 4️⃣ Suggested Technical Architecture

### Frontend (Desktop UI)
- **Electron** for cross-platform desktop  
- **React + Chart.js** for interactive dashboard  
- Minimal CLI for V1  

### Backend / Core
- Node.js daemon supervising filesystem, Git sandbox, and AI module  
- Modules: File Watcher, Analyzer, RiskScore, Feedback Loop, Proposal Generator  

### Database
- **SQLite / Better SQLite3** for local persistence  
- Storage: projects, files, alerts, proposals, developer profiles, logs  

### LLM / AI
- Ollama or local LLaMA (optional V1.5+) for intelligent explanations and suggestions  

---

## 5️⃣ Recommended Tech Stack

| Component | Tech | Justification |
|-----------|------|---------------|
| Desktop UI | Electron + React | Cross-platform, seamless Node.js integration, interactive dashboard |
| File Watching | chokidar | Efficient filesystem event handling with exclusion support |
| Git Sandbox | isomorphic-git or simple-git | Sandbox branches, diff, merge/rebase |
| Code Analysis | ts-morph + escomplex | JS/TS AST parsing, complexity and size metrics |
| Rules Engine | json-rules-engine | Dynamic rule definition via JSON |
| RiskScore / Feedback | Custom Node.js module + SQLite | Flexible weighting and historical storage |
| LLM | Local Ollama | Privacy-respecting local execution |
| Visualization | Chart.js | Simple and performant charts |

---

## 6️⃣ Data Model

### Main Entities

**Projects**  
- id, name, path, last_scan  

**Files**  
- id, project_id, path, size, complexity, last_modified  

**Alerts**  
- id, file_id, type (rule), score, status, created_at  

**Proposals**  
- id, alert_id, diff_content, score_before, score_after, status, created_at  

**DeveloperProfile**  
- id, project_id, rule_name, acceptance_rate, avg_score_delta  

**Events_Log**  
- id, type, file_id, details, timestamp  

### Relationships
- 1 Project → N Files  
- 1 File → N Alerts  
- 1 Alert → N Proposals  
- 1 Project → 1 DeveloperProfile  
- Logs reference Files and Alerts  

---

## 7️⃣ Main User Flows

### Flow 1: Analysis & Alert
1. File modified → File Watcher detects change  
2. Analyzer / Rule Engine computes metrics  
3. RiskScore Calculator generates score  
4. Alert / Proposal created if threshold exceeded  
5. Dashboard / CLI displays alert and diff  

### Flow 2: Feedback Loop
1. Developer selects action (`apply / ignore / explore`)  
2. Feedback Loop adjusts rule weighting  
3. History stored in SQLite  
4. RiskScore recalculated if necessary  

### Flow 3: Sandbox Execution
1. Proposal applied in Git sandbox  
2. Unit tests / build executed  
3. Human validation or automatic rollback  

### Flow 4: LLM Interactions (optional)
1. Developer requests explanation  
2. Local LLM returns contextualized explanation of alert / proposal  

---

## 8️⃣ Internal API / Endpoints (V1)

| Endpoint | Method | Input | Output | Description |
|----------|--------|-------|--------|-------------|
| `/projects/:id/scan` | GET | project_id | JSON: files, metrics, scores | Scans project and returns RiskScore metrics |
| `/alerts/:id/diff` | GET | alert_id | JSON patch / unified diff | Returns proposal diff for an alert |
| `/alerts/:id/feedback` | POST | alert_id + action | JSON status | Records action: apply/ignore/explore |
| `/dashboard/:id` | GET | project_id | JSON scores + alert list | Minimal dashboard for UI / CLI |

---

## 9️⃣ Technical Constraints & Security

- **100% local execution** for privacy  
- Mandatory Git sandbox for any proposed patch  
- LLM strictly local and optional  
- Filesystem exclusions for performance and security (`node_modules`, `.git`)  
- Limited permissions: no root access in V1  
- Encrypted history + logs possible for auditing  
- Feedback loop constrained to prevent rule weight drift  

---

## 🔟 Development Phases Breakdown

| Phase | Features |
|-------|----------|
| **V1** | Minimal CLI, file scanning, RiskScore, alerts, proposals, Git sandbox, basic feedback loop, JSON dashboard |
| **V2** | Electron UI + interactive dashboard, notifications, dynamic feedback, experimental local LLM, limited multi-project |
| **V3** | Global developer profile, semi-autonomous intelligent suggestions, full LLM integration, cybersecurity (logs, vulnerabilities, network monitoring), controlled autonomy |

---

## 11️⃣ Complexity Estimate per Module (V1)

| Module | Complexity | Justification |
|--------|-----------|---------------|
| File Watcher | Medium | chokidar simplifies implementation, but exclusions and debouncing add complexity |
| Analyzer / Rule Engine | Medium → High | AST parsing, metric computation, json-rules-engine integration |
| RiskScore Calculator | Medium | Simple weighting logic, increased complexity with feedback loop |
| Git Sandbox | High | Branch creation, diff, merge/rebase, TTL, rollback |
| CLI / Dashboard | Medium | Minimal dashboard + Chart.js, simple UI |
| Feedback Loop | Medium | Dynamic weighting, SQLite history |
| LLM Module | Medium → High | Optional V1.5, local integration, sandboxing |
