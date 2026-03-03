import { app, clipboard, ipcMain, BrowserWindow } from "electron";
import * as path from "node:path";
import path__default, { join } from "node:path";
import Database from "better-sqlite3";
import * as fs from "node:fs";
import fs__default, { existsSync } from "node:fs";
import { SyntaxKind, Project } from "ts-morph";
import { simpleGit } from "simple-git";
import chokidar from "chokidar";
import { EventEmitter } from "node:events";
import http from "node:http";
import __cjs_mod__ from "node:module";
const __filename = import.meta.filename;
const __dirname = import.meta.dirname;
const require2 = __cjs_mod__.createRequire(import.meta.url);
let _db = null;
function getDb() {
  if (_db) return _db;
  const dbPath = app?.getPath ? join(app.getPath("userData"), "pulse.db") : join(process.cwd(), "pulse.db");
  console.log(`[Pulse] Opening DB at: ${dbPath}`);
  _db = new Database(dbPath);
  return _db;
}
function initDb() {
  const db = getDb();
  db.exec(`
        CREATE TABLE IF NOT EXISTS scans (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path           TEXT    NOT NULL,
            global_score        REAL    NOT NULL,
            complexity_score    REAL    NOT NULL,
            function_size_score REAL    NOT NULL,
            churn_score         REAL    NOT NULL DEFAULT 0,
            depth_score         REAL    NOT NULL DEFAULT 0,
            param_score         REAL    NOT NULL DEFAULT 0,
            fan_in              INTEGER NOT NULL DEFAULT 0,
            fan_out             INTEGER NOT NULL DEFAULT 0,
            language            TEXT    NOT NULL DEFAULT 'unknown',
            scanned_at          TEXT    NOT NULL
        )
    `);
  db.exec(`
        CREATE TABLE IF NOT EXISTS feedbacks (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path           TEXT    NOT NULL,
            action              TEXT    NOT NULL,
            risk_score_at_time  REAL    NOT NULL,
            created_at          TEXT    NOT NULL
        )
    `);
  db.exec(`
        CREATE TABLE IF NOT EXISTS functions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            name TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            line_count INTEGER NOT NULL,
            cyclomatic_complexity INTEGER NOT NULL,
            parameter_count INTEGER NOT NULL DEFAULT 0,
            max_depth INTEGER NOT NULL DEFAULT 0,
            scanned_at TEXT NOT NULL
        )
    `);
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN churn_score REAL NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added churn_score column.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN depth_score REAL NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added depth_score to scans.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN param_score REAL NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added param_score to scans.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN fan_in INTEGER NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added fan_in to scans.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN fan_out INTEGER NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added fan_out to scans.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
    console.log("[Pulse] DB migrated: added project_path to scans.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE functions ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
    console.log("[Pulse] DB migrated: added project_path to functions.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE functions ADD COLUMN parameter_count INTEGER NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added parameter_count to functions.");
  } catch {
  }
  try {
    db.exec(`ALTER TABLE functions ADD COLUMN max_depth INTEGER NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added max_depth to functions.");
  } catch {
  }
  db.exec(`
        CREATE TABLE IF NOT EXISTS terminal_errors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            command       TEXT    NOT NULL,
            exit_code     INTEGER NOT NULL,
            error_hash    TEXT    NOT NULL,
            error_text    TEXT    NOT NULL DEFAULT '',
            cwd           TEXT    NOT NULL DEFAULT '',
            project_path  TEXT    NOT NULL DEFAULT '',
            llm_response  TEXT,
            resolved      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL
        )
    `);
}
function saveScan(result, projectPath) {
  const db = getDb();
  const stmt = db.prepare(`
        INSERT INTO scans (file_path, global_score, complexity_score, function_size_score, churn_score, depth_score, param_score, fan_in, fan_out, language, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
  stmt.run(
    result.filePath,
    result.globalScore,
    result.details.complexityScore,
    result.details.functionSizeScore,
    result.details.churnScore,
    result.details.depthScore,
    result.details.paramScore,
    result.details.fanIn,
    result.details.fanOut,
    result.language ?? "unknown",
    projectPath,
    (/* @__PURE__ */ new Date()).toISOString()
  );
}
function saveFeedback(filePath, action, riskScore) {
  const db = getDb();
  const stmt = db.prepare(`
        INSERT INTO feedbacks (file_path, action, risk_score_at_time, created_at)
        VALUES (?, ?, ?, ?)
    `);
  stmt.run(filePath, action, riskScore, (/* @__PURE__ */ new Date()).toISOString());
}
function saveFunctions(filePath, functions, projectPath) {
  const db = getDb();
  db.prepare(`DELETE FROM functions WHERE file_path = ?`).run(filePath);
  const stmt = db.prepare(`
        INSERT INTO functions (file_path, name, start_line, line_count, cyclomatic_complexity, parameter_count, max_depth, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
  const now = (/* @__PURE__ */ new Date()).toISOString();
  for (const fn of functions) {
    stmt.run(filePath, fn.name, fn.startLine, fn.lineCount, fn.cyclomaticComplexity, fn.parameterCount, fn.maxDepth, projectPath, now);
  }
}
function getLatestScans(projectPath) {
  const db = getDb();
  const rows = db.prepare(`
        SELECT s.file_path, s.global_score, s.complexity_score, s.function_size_score,
            s.churn_score, s.depth_score, s.param_score, s.fan_in, s.fan_out, s.language, s.scanned_at
        FROM scans s
        INNER JOIN (
            SELECT file_path, MAX(scanned_at) as max_at
            FROM scans
            WHERE project_path = ?
            GROUP BY file_path
        ) latest ON s.file_path = latest.file_path AND s.scanned_at = latest.max_at
        ORDER BY s.global_score DESC
    `).all(projectPath);
  return rows.map((row) => {
    const prev = db.prepare(`
            SELECT global_score FROM scans
            WHERE file_path = ? AND scanned_at < ?
            ORDER BY scanned_at DESC LIMIT 1
        `).get(row.file_path, row.scanned_at);
    let trend = "↔";
    if (prev) {
      const delta = row.global_score - prev.global_score;
      if (delta > 2) trend = "↑";
      if (delta < -2) trend = "↓";
    }
    const fb = db.prepare(`
            SELECT action FROM feedbacks WHERE file_path = ? ORDER BY created_at DESC LIMIT 1
        `).get(row.file_path);
    return {
      filePath: row.file_path,
      globalScore: row.global_score,
      complexityScore: row.complexity_score,
      functionSizeScore: row.function_size_score,
      churnScore: row.churn_score,
      depthScore: row.depth_score,
      paramScore: row.param_score,
      fanIn: row.fan_in,
      fanOut: row.fan_out,
      language: row.language,
      scannedAt: row.scanned_at,
      trend,
      feedback: fb?.action ?? null
    };
  });
}
function getFeedbackHistory(filePath) {
  return getDb().prepare(`SELECT action, created_at FROM feedbacks WHERE file_path = ? ORDER BY created_at ASC LIMIT 20`).all(filePath);
}
function getScoreHistory(filePath) {
  return getDb().prepare(`
            SELECT global_score as score, scanned_at
            FROM scans
            WHERE file_path = ?
            ORDER BY scanned_at ASC
            LIMIT 30
        `).all(filePath);
}
function cleanDeletedFiles() {
  const db = getDb();
  const files = db.prepare(`SELECT DISTINCT file_path FROM scans`).all();
  let deleted = 0;
  for (const { file_path } of files) {
    if (!existsSync(file_path)) {
      db.prepare(`DELETE FROM scans WHERE file_path = ?`).run(file_path);
      db.prepare(`DELETE FROM functions WHERE file_path = ?`).run(file_path);
      db.prepare(`DELETE FROM feedbacks WHERE file_path = ?`).run(file_path);
      deleted++;
    }
  }
  return deleted;
}
function getFunctions(filePath) {
  return getDb().prepare(`
            SELECT name, start_line, line_count, cyclomatic_complexity, parameter_count, max_depth
            FROM functions
            WHERE file_path = ?
            ORDER BY cyclomatic_complexity DESC
        `).all(filePath);
}
function saveTerminalError(params) {
  const db = getDb();
  const stmt = db.prepare(`
        INSERT INTO terminal_errors (command, exit_code, error_hash, error_text, cwd, project_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
  const result = stmt.run(
    params.command,
    params.exit_code,
    params.error_hash,
    params.error_text,
    params.cwd,
    params.project_path,
    (/* @__PURE__ */ new Date()).toISOString()
  );
  return result.lastInsertRowid;
}
function getTerminalErrorHistory(errorHash, projectPath) {
  return getDb().prepare(`
            SELECT id, command, created_at, resolved
            FROM terminal_errors
            WHERE error_hash = ? AND project_path = ?
            ORDER BY created_at DESC
            LIMIT 20
        `).all(errorHash, projectPath);
}
function updateTerminalErrorResolved(id, resolved) {
  getDb().prepare(`UPDATE terminal_errors SET resolved = ? WHERE id = ?`).run(resolved, id);
}
function updateTerminalErrorLLM(id, llmResponse) {
  getDb().prepare(`UPDATE terminal_errors SET llm_response = ? WHERE id = ?`).run(llmResponse, id);
}
const OLLAMA_URL = "http://localhost:11434/api/generate";
const MODEL = "qwen2.5-coder:3b";
function getFileName(p) {
  return p.split("/").pop() ?? p;
}
function buildScoreTrend(history) {
  if (history.length < 2) return "Pas assez de données historiques.";
  const first = history[0].score;
  const last = history[history.length - 1].score;
  const delta = last - first;
  const trend = delta > 5 ? "📈 en dégradation" : delta < -5 ? "📉 en amélioration" : "↔ stable";
  return `${trend} (${first.toFixed(1)} → ${last.toFixed(1)} sur ${history.length} scans)`;
}
function buildPrompt(ctx, source) {
  const topFns = ctx.functions.filter((fn) => fn.name !== "anonymous").sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity).slice(0, 5).map((fn) => `  - ${fn.name}(): cx=${fn.cyclomaticComplexity}, ${fn.lineCount} lignes, profondeur=${fn.maxDepth}, params=${fn.parameterCount}`).join("\n");
  const importedBySection = ctx.importedBy.length > 0 ? `Ce fichier est importé par ${ctx.importedBy.length} autre(s) fichier(s) : ${ctx.importedBy.map(getFileName).join(", ")}. Un bug ici aurait un impact direct sur ces fichiers.` : "Ce fichier n'est importé par aucun autre fichier du projet (point d'entrée ou module isolé).";
  const feedbackSection = ctx.feedbackHistory.length > 0 ? `Historique des feedbacks : ${ctx.feedbackHistory.map((f) => f.action).join(" → ")} (${ctx.feedbackHistory.length} action(s) enregistrée(s)).` : "Aucun feedback enregistré pour ce fichier.";
  return `Tu es un expert en qualité de code. Analyse le fichier suivant et fournis des suggestions de refactorisation concrètes.

## Fichier : ${getFileName(ctx.filePath)}
## Score de risque : ${ctx.globalScore.toFixed(1)}/100

## Détail des métriques :
- Complexité cyclomatique : ${ctx.details.complexityScore.toFixed(1)}/100
- Taille des fonctions : ${ctx.details.functionSizeScore.toFixed(1)}/100
- Profondeur d'imbrication : ${ctx.details.depthScore.toFixed(1)}/100
- Nombre de paramètres : ${ctx.details.paramScore.toFixed(1)}/100
- Churn (fréquence de modification) : ${ctx.details.churnScore.toFixed(1)}/100

## Fonctions les plus complexes :
${topFns || "  (aucune)"}

## Impact dans le projet :
${importedBySection}

## Évolution du score :
${buildScoreTrend(ctx.scoreHistory)}

## Historique des actions développeur :
${feedbackSection}

## Code source :
\`\`\`
${source.slice(0, 6e3)}${source.length > 6e3 ? "\n... (tronqué)" : ""}
\`\`\`

Réponds en français. Structure ta réponse ainsi :
1. **Analyse** (3-4 phrases) : explique POURQUOI ce fichier est risqué en t'appuyant sur les métriques ET le code source.
2. **Suggestions** : liste 2-3 refactorisations concrètes avec exemples de code si pertinent. Priorise selon l'impact (commence par ce qui améliore le plus le score).
Sois direct et pratique. Tiens compte de la criticité du fichier (nombre de dépendants) dans ta priorisation.`;
}
async function streamOllama(prompt, onChunk, onDone, onError) {
  try {
    const res = await fetch(OLLAMA_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODEL, prompt, stream: true })
    });
    if (!res.ok || !res.body) {
      onError(`Erreur Ollama : ${res.status} ${res.statusText}`);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const lines = decoder.decode(value).split("\n").filter(Boolean);
      for (const line of lines) {
        try {
          const json = JSON.parse(line);
          if (json.response) onChunk(json.response);
          if (json.done) {
            onDone();
            return;
          }
        } catch {
        }
      }
    }
    onDone();
  } catch (err) {
    onError(`Ollama inaccessible : ${err instanceof Error ? err.message : String(err)}`);
  }
}
function buildErrorPrompt(ctx, topFiles, pastOccurrences) {
  const filesSection = topFiles.length > 0 ? topFiles.map((f) => `  - ${f.filePath.split("/").pop()} (risque: ${f.globalScore.toFixed(1)}/100)`).join("\n") : "  (aucun fichier analysé)";
  const recidive = pastOccurrences > 1 ? `
⚠️ **Récidive** : cette erreur a déjà été vue ${pastOccurrences} fois dans ce projet.
` : "";
  return `Tu es un expert en développement logiciel. Une commande a échoué dans un terminal.
${recidive}
## Commande échouée
\`${ctx.command}\` (exit code: ${ctx.exit_code})
Répertoire: ${ctx.cwd || "(inconnu)"}

## Sortie d'erreur
\`\`\`
${ctx.errorText.slice(0, 4e3)}${ctx.errorText.length > 4e3 ? "\n... (tronqué)" : ""}
\`\`\`

## Fichiers à risque dans le projet (pour contexte)
${filesSection}

Réponds en français. Structure ta réponse ainsi :
1. **Cause** (2-3 phrases) : explique la cause racine de cette erreur de manière claire et directe.
2. **Solution** : donne la commande exacte ou les étapes précises pour résoudre le problème.
3. **Prévention** (optionnel) : si c'est une erreur récurrente ou évitable, suggère comment l'éviter.

Sois concis et pratique. Priorise la solution immédiate.`;
}
async function askLLMForError(ctx, topFiles, pastOccurrences, onChunk, onDone, onError) {
  const prompt = buildErrorPrompt(ctx, topFiles, pastOccurrences);
  await streamOllama(prompt, onChunk, onDone, onError);
}
async function askLLM(ctx, onChunk, onDone, onError) {
  let source;
  try {
    source = fs__default.readFileSync(ctx.filePath, "utf-8");
  } catch {
    onError(`Impossible de lire le fichier : ${ctx.filePath}`);
    return;
  }
  const prompt = buildPrompt(ctx, source);
  await streamOllama(prompt, onChunk, onDone, onError);
}
const EXTENSION_MAP = {
  ".ts": "typescript",
  ".tsx": "typescript",
  ".js": "javascript",
  ".jsx": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".py": "python"
};
function detectLanguage(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return EXTENSION_MAP[ext] ?? "unknown";
}
const NESTING_KINDS = /* @__PURE__ */ new Set([
  SyntaxKind.IfStatement,
  SyntaxKind.ForStatement,
  SyntaxKind.ForInStatement,
  SyntaxKind.ForOfStatement,
  SyntaxKind.WhileStatement,
  SyntaxKind.DoStatement,
  SyntaxKind.SwitchStatement,
  SyntaxKind.TryStatement
  // SyntaxKind.Block retiré — trop agressif, surcompte tous les {}
]);
function computeMaxDepth(node, current = 0) {
  let max = current;
  for (const child of node.getChildren()) {
    const next = NESTING_KINDS.has(child.getKind()) ? current + 1 : current;
    max = Math.max(max, computeMaxDepth(child, next));
  }
  return max;
}
const COMPLEXITY_KINDS = /* @__PURE__ */ new Set([
  SyntaxKind.IfStatement,
  SyntaxKind.ForStatement,
  SyntaxKind.ForInStatement,
  SyntaxKind.ForOfStatement,
  SyntaxKind.WhileStatement,
  SyntaxKind.DoStatement,
  SyntaxKind.CaseClause,
  SyntaxKind.CatchClause,
  SyntaxKind.ConditionalExpression,
  SyntaxKind.AmpersandAmpersandToken,
  SyntaxKind.BarBarToken,
  SyntaxKind.QuestionQuestionToken
]);
function analyzeWithTsMorph(filePath) {
  const project = new Project({
    useInMemoryFileSystem: false,
    skipAddingFilesFromTsConfig: true,
    compilerOptions: { allowJs: true }
  });
  const sourceFile = project.addSourceFileAtPath(filePath);
  const totalLines = sourceFile.getEndLineNumber();
  const allFunctions = [
    ...sourceFile.getFunctions(),
    ...sourceFile.getDescendantsOfKind(SyntaxKind.ArrowFunction),
    ...sourceFile.getClasses().flatMap((cls) => cls.getMethods())
  ];
  const functions = allFunctions.map((fn) => {
    let name = "anonymous";
    if ("getName" in fn && typeof fn.getName === "function") {
      const raw = fn.getName();
      if (raw) name = raw;
    }
    if (name === "anonymous") {
      const parent = fn.getParent();
      if (parent && "getName" in parent && typeof parent.getName === "function") {
        const parentName = parent.getName();
        if (parentName) name = parentName;
      }
    }
    const startLine = fn.getStartLineNumber();
    const lineCount = fn.getEndLineNumber() - startLine + 1;
    let cyclomaticComplexity = 1;
    fn.forEachDescendant((node) => {
      if (COMPLEXITY_KINDS.has(node.getKind())) cyclomaticComplexity++;
    });
    const parameterCount = "getParameters" in fn && typeof fn.getParameters === "function" ? fn.getParameters().length : 0;
    const maxDepth = computeMaxDepth(fn);
    return { name, startLine, lineCount, cyclomaticComplexity, parameterCount, maxDepth };
  });
  return { filePath, totalLines, totalFunctions: functions.length, functions, language: "typescript" };
}
function analyzeWithRegex(source, filePath, language) {
  const lines = source.split("\n");
  const patterns = [
    /^\s*def\s+(\w+)\s*\(/,
    /^\s*async\s+def\s+(\w+)\s*\(/
  ];
  const complexityPatterns = [
    /\bif\b/,
    /\belif\b/,
    /\bfor\b/,
    /\bwhile\b/,
    /\bexcept\b/,
    /\band\b/,
    /\bor\b/
  ];
  const functions = [];
  lines.forEach((line, i) => {
    for (const pat of patterns) {
      if (pat.test(line)) {
        const nameMatch = /(?:def\s+|async\s+def\s+)(\w+)/.exec(line);
        const name = nameMatch?.[1] ?? "anonymous";
        let endLine = lines.length;
        for (let j = i + 1; j < lines.length; j++) {
          if (patterns.some((p) => p.test(lines[j] ?? ""))) {
            endLine = j;
            break;
          }
        }
        const fnLines = lines.slice(i, endLine);
        const cyclomaticComplexity = 1 + fnLines.reduce((acc, l) => acc + complexityPatterns.filter((p) => p.test(l)).length, 0);
        const sigMatch = /\(([^)]*)\)/.exec(line);
        const parameterCount = sigMatch?.[1]?.trim() ? sigMatch[1].split(",").filter((p) => p.trim().length > 0).length : 0;
        const maxDepth = fnLines.reduce((max, l) => {
          const indent = l.match(/^(\s+)/)?.[1] ?? "";
          const depth = Math.floor(indent.replace(/\t/g, "    ").length / 4);
          return Math.max(max, depth);
        }, 0);
        functions.push({ name, startLine: i + 1, lineCount: fnLines.length, cyclomaticComplexity, parameterCount, maxDepth });
        break;
      }
    }
  });
  return { filePath, totalLines: lines.length, totalFunctions: functions.length, functions, language };
}
async function analyzeFile(filePath) {
  const language = detectLanguage(filePath);
  if (language === "typescript" || language === "javascript") {
    try {
      const result = analyzeWithTsMorph(filePath);
      return { ...result, language };
    } catch (err) {
      console.warn(`[Pulse] ts-morph failed for ${filePath}, using regex fallback:`, err);
    }
  }
  const source = fs.readFileSync(filePath, "utf-8");
  return analyzeWithRegex(source, filePath, language);
}
let _cached = null;
function loadConfig() {
  if (_cached) return _cached;
  const candidates = [
    path__default.join(process.cwd(), "pulse.config.json"),
    path__default.join(__dirname, "../../pulse.config.json"),
    path__default.join(__dirname, "../../../pulse.config.json"),
    path__default.join(path__default.dirname(process.execPath), "pulse.config.json")
  ];
  for (const p of candidates) {
    if (fs__default.existsSync(p)) {
      console.log(`[Pulse] Config loaded from: ${p}`);
      const raw = JSON.parse(fs__default.readFileSync(p, "utf-8"));
      _cached = {
        projectPath: raw.projectPath ?? process.cwd(),
        thresholds: {
          alert: raw.thresholds?.alert ?? 50,
          warning: raw.thresholds?.warning ?? 20
        },
        ignore: raw.ignore ?? ["node_modules", ".git", "dist", "build", ".vite", "vendor", "__pycache__"],
        socketPort: raw.socketPort
      };
      return _cached;
    }
  }
  throw new Error(
    `[Pulse] pulse.config.json introuvable.
Chemins essayés :
${candidates.join("\n")}`
  );
}
let _churnCache = null;
async function buildChurnCache() {
  try {
    const config = loadConfig();
    const git = simpleGit(config.projectPath);
    const log = await git.raw(["log", "--since=30 days ago", "--name-only", "--pretty=format:"]);
    _churnCache = /* @__PURE__ */ new Map();
    for (const line of log.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const abs = `${config.projectPath}/${trimmed}`;
      _churnCache.set(abs, (_churnCache.get(abs) ?? 0) + 1);
    }
    console.log(`[Pulse] Churn cache built — ${_churnCache.size} files tracked.`);
  } catch {
    _churnCache = /* @__PURE__ */ new Map();
  }
}
function clearChurnCache() {
  _churnCache = null;
}
async function getChurnScore(filePath) {
  if (!_churnCache) await buildChurnCache();
  return _churnCache.get(filePath) ?? 0;
}
function clampedScore(value, safe, danger) {
  if (value <= safe) return 0;
  if (value >= danger) return 100;
  return (value - safe) / (danger - safe) * 100;
}
async function calculateRiskScore(metrics) {
  const fns = metrics.functions.filter((fn) => fn.name !== "anonymous");
  const maxComplexity = fns.length > 0 ? Math.max(...fns.map((fn) => fn.cyclomaticComplexity)) : 0;
  const maxFunctionSize = fns.length > 0 ? Math.max(...fns.map((fn) => fn.lineCount)) : 0;
  const maxDepth = fns.length > 0 ? Math.max(...fns.map((fn) => fn.maxDepth)) : 0;
  const maxParams = fns.length > 0 ? Math.max(...fns.map((fn) => fn.parameterCount)) : 0;
  const complexityScore = clampedScore(maxComplexity, 3, 10);
  const functionSizeScore = clampedScore(maxFunctionSize, 20, 60);
  const depthScore = clampedScore(maxDepth, 2, 5);
  const paramScore = clampedScore(maxParams, 3, 7);
  const churn = await getChurnScore(metrics.filePath);
  const churnScore = clampedScore(churn, 5, 20);
  const globalScore = complexityScore * 0.35 + functionSizeScore * 0.2 + churnScore * 0.15 + depthScore * 0.2 + paramScore * 0.1;
  return {
    filePath: metrics.filePath,
    language: metrics.language,
    globalScore,
    details: { complexityScore, functionSizeScore, churnScore, depthScore, paramScore, fanIn: 0, fanOut: 0 }
  };
}
const SUPPORTED_EXTENSIONS = /* @__PURE__ */ new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".py"]);
const IGNORE_FILE_PATTERNS = [".min.js", ".min.ts", ".d.ts", ".map", ".spec.", ".test.", "__tests__"];
function shouldIgnoreFile(filename) {
  return IGNORE_FILE_PATTERNS.some((p) => filename.includes(p));
}
function getFiles(dir, ignore, fileList = [], visited = /* @__PURE__ */ new Set()) {
  let realDir;
  try {
    realDir = fs__default.realpathSync(dir);
  } catch {
    return fileList;
  }
  if (visited.has(realDir)) return fileList;
  visited.add(realDir);
  let entries;
  try {
    entries = fs__default.readdirSync(dir);
  } catch {
    return fileList;
  }
  for (const entry of entries) {
    if (ignore.includes(entry)) continue;
    const fullPath = path__default.join(dir, entry);
    let stat;
    try {
      stat = fs__default.statSync(fullPath);
    } catch {
      continue;
    }
    if (stat.isDirectory()) {
      getFiles(fullPath, ignore, fileList, visited);
      continue;
    }
    const ext = path__default.extname(entry).toLowerCase();
    if (SUPPORTED_EXTENSIONS.has(ext) && !shouldIgnoreFile(entry)) {
      fileList.push(fullPath);
    }
  }
  return fileList;
}
const IMPORT_PATTERNS = {
  js: [
    /import\s+.*\s+from\s+['"]([^'"]+)['"]/g,
    /require\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
    /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  ],
  py: [
    /^from\s+(\.{0,2}[\w.]+)\s+import/gm,
    /^import\s+([\w.]+)/gm
  ]
};
function extractImports(filePath, source) {
  const ext = path__default.extname(filePath).toLowerCase();
  const isPy = ext === ".py";
  const pats = isPy ? IMPORT_PATTERNS.py : IMPORT_PATTERNS.js;
  const imports = [];
  for (const pat of pats) {
    pat.lastIndex = 0;
    let match;
    while ((match = pat.exec(source)) !== null) {
      const raw = match[1];
      if (raw.startsWith(".")) imports.push(raw);
    }
  }
  return imports;
}
function resolveImport(fromFile, importPath, allFiles) {
  const dir = path__default.dirname(fromFile);
  const stripped = importPath.replace(/\.js$/, "");
  const base = path__default.resolve(dir, stripped);
  const candidates = [
    base,
    base + ".ts",
    base + ".tsx",
    base + ".js",
    base + ".jsx",
    path__default.join(base, "index.ts"),
    path__default.join(base, "index.js")
  ];
  for (const c of candidates) {
    if (allFiles.has(c)) return c;
  }
  return null;
}
function buildEdges(files, fileSources) {
  const fileSet = new Set(files);
  const edges = [];
  const seen = /* @__PURE__ */ new Set();
  for (const file of files) {
    const source = fileSources.get(file);
    if (!source) continue;
    const imports = extractImports(file, source);
    for (const imp of imports) {
      const resolved = resolveImport(file, imp, fileSet);
      if (!resolved) continue;
      const key = `${file}→${resolved}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ from: file, to: resolved });
    }
  }
  return edges;
}
async function scanProject(projectPath) {
  const config = loadConfig();
  const files = getFiles(projectPath, config.ignore);
  clearChurnCache();
  console.log(`[Pulse] Found ${files.length} files to scan`);
  const results = [];
  const fileSources = /* @__PURE__ */ new Map();
  for (const file of files) {
    try {
      const source = fs__default.readFileSync(file, "utf-8");
      fileSources.set(file, source);
      const analysis = await analyzeFile(file);
      const riskScore = await calculateRiskScore(analysis);
      saveFunctions(file, analysis.functions, projectPath);
      results.push(riskScore);
    } catch (error) {
      console.error(`[Pulse] Error analyzing ${path__default.basename(file)}:`, error);
    }
  }
  const edges = buildEdges(files, fileSources);
  const fanOutMap = /* @__PURE__ */ new Map();
  const fanInMap = /* @__PURE__ */ new Map();
  for (const file of files) {
    fanOutMap.set(file, 0);
    fanInMap.set(file, 0);
  }
  for (const edge of edges) {
    fanOutMap.set(edge.from, (fanOutMap.get(edge.from) ?? 0) + 1);
    fanInMap.set(edge.to, (fanInMap.get(edge.to) ?? 0) + 1);
  }
  for (const result of results) {
    result.details.fanIn = fanInMap.get(result.filePath) ?? 0;
    result.details.fanOut = fanOutMap.get(result.filePath) ?? 0;
    saveScan(result, projectPath);
  }
  console.log(`[Pulse] Scan complete — ${results.length} files, ${edges.length} connections`);
  return {
    files: results.sort((a, b) => b.globalScore - a.globalScore),
    edges
  };
}
function startWatcher() {
  const config = loadConfig();
  const emitter = new EventEmitter();
  const watcher = chokidar.watch(config.projectPath, {
    ignored: (filePath) => {
      const parts = filePath.split("/");
      return parts.some((part) => config.ignore.includes(part));
    },
    ignoreInitial: true
  }).on("error", (err) => emitter.emit("error", err));
  const SUPPORTED = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".py"];
  watcher.on("add", (path2) => {
    if (!SUPPORTED.some((ext) => path2.endsWith(ext))) return;
    emitter.emit("file:added", path2);
  });
  watcher.on("change", (path2) => {
    if (!SUPPORTED.some((ext) => path2.endsWith(ext))) return;
    emitter.emit("file:changed", path2);
  });
  watcher.on("unlink", (path2) => {
    emitter.emit("file:deleted", path2);
  });
  return {
    emitter,
    pause: () => watcher.unwatch(config.projectPath),
    resume: () => watcher.add(config.projectPath)
  };
}
let lastCommandError = null;
function startSocketServer(preferredPort = 7891) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (req.method === "POST" && req.url === "/command-error") {
        let body = "";
        req.on("data", (chunk) => {
          body += chunk;
        });
        req.on("end", () => {
          try {
            const parsed = JSON.parse(body);
            lastCommandError = {
              command: parsed.command ?? "",
              exit_code: parsed.exit_code ?? 1,
              cwd: parsed.cwd ?? "",
              timestamp: parsed.timestamp ?? Date.now(),
              receivedAt: Date.now()
            };
            console.log(`[Pulse] Command error received: "${lastCommandError.command}" (exit ${lastCommandError.exit_code})`);
          } catch (e) {
            console.warn("[Pulse] Failed to parse command-error payload:", e);
          }
          res.writeHead(200);
          res.end("OK");
        });
      } else {
        res.writeHead(404);
        res.end("Not found");
      }
    });
    const tryBind = (port, attemptsLeft) => {
      server.once("error", (err) => {
        if (err.code === "EADDRINUSE" && attemptsLeft > 0) {
          console.warn(`[Pulse] Port ${port} in use, trying ${port + 1}`);
          tryBind(port + 1, attemptsLeft - 1);
        } else {
          reject(err);
        }
      });
      server.listen(port, "127.0.0.1", () => {
        console.log(`[Pulse] Socket server listening on port ${port}`);
        resolve({
          port,
          getLastCommandError: () => lastCommandError,
          stop: () => server.close()
        });
      });
    };
    tryBind(preferredPort, 3);
  });
}
const ERROR_PATTERNS = [
  // Node / TS
  /Error:/,
  /error TS\d+/,
  /ENOENT/,
  /EACCES/,
  /ECONNREFUSED/,
  /EADDRINUSE/,
  /npm ERR!/,
  /TypeError/,
  /SyntaxError/,
  /ReferenceError/,
  /RangeError/,
  /Cannot find module/,
  /Module not found/,
  // Unix / shell
  /No such file or directory/,
  /Permission denied/,
  /command not found/,
  /not found:/,
  /cannot open/i,
  /Segmentation fault/,
  // Python
  /Traceback \(most recent call last\)/,
  /ModuleNotFoundError/,
  /ImportError/,
  /AssertionError/,
  /IndentationError/,
  // Build tools
  /Build failed/i,
  /failed to compile/i,
  /Compilation failed/i,
  /failed with exit code/i,
  /exited with code [^0]/,
  /FAILED/,
  // Rust / Go / other
  /error\[E\d+\]/,
  /fatal:/i,
  /panic:/i
];
const CORRELATION_WINDOW_MS = 3e4;
const POLL_INTERVAL_MS = 600;
function makeHash(text) {
  return text.trim().slice(0, 80);
}
function isErrorText(text) {
  if (text.trim().length < 30) return false;
  return ERROR_PATTERNS.some((p) => p.test(text));
}
function startClipboardWatcher(getLastCommandError, onError) {
  let lastClipboardText = clipboard.readText();
  let lastNotifiedHash = "";
  const timer = setInterval(() => {
    const text = clipboard.readText();
    if (text === lastClipboardText) return;
    lastClipboardText = text;
    if (!isErrorText(text)) return;
    const hash = makeHash(text);
    if (hash === lastNotifiedHash) return;
    const cmdError = getLastCommandError();
    const now = Date.now();
    const inWindow = cmdError !== null && now - cmdError.receivedAt < CORRELATION_WINDOW_MS;
    lastNotifiedHash = hash;
    onError({
      command: inWindow ? cmdError.command : "(commande inconnue)",
      exit_code: inWindow ? cmdError.exit_code : 1,
      cwd: inWindow ? cmdError.cwd : "",
      errorText: text,
      errorHash: hash,
      timestamp: now
    });
  }, POLL_INTERVAL_MS);
  return {
    stop: () => clearInterval(timer)
  };
}
let mainWindow = null;
let lastEdges = [];
let lastTopFiles = [];
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js")
    }
  });
  if (process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}
async function runScan() {
  try {
    const config = loadConfig();
    mainWindow?.webContents.send("pulse-event", { type: "scan-start", ts: Date.now() });
    const result = await scanProject(config.projectPath);
    lastEdges = result.edges;
    lastTopFiles = result.files.slice(0, 10).map((f) => ({ filePath: f.filePath, globalScore: f.globalScore }));
    mainWindow?.webContents.send("pulse-event", { type: "scan-done", count: result.files.length, edges: result.edges.length, ts: Date.now() });
    mainWindow?.webContents.send("scan-complete");
  } catch (err) {
    console.error("[Pulse] Scan error:", err);
    mainWindow?.webContents.send("pulse-event", { type: "scan-error", ts: Date.now() });
  }
}
app.whenReady().then(async () => {
  initDb();
  const cleaned = cleanDeletedFiles();
  if (cleaned > 0) console.log(`[Pulse] Cleaned ${cleaned} deleted file(s) from DB.`);
  const config = loadConfig();
  const socketServer = await startSocketServer(config.socketPort ?? 7891);
  const clipWatcher = startClipboardWatcher(
    () => socketServer.getLastCommandError(),
    (ctx) => {
      const projectPath = loadConfig().projectPath;
      const pastHistory = getTerminalErrorHistory(ctx.errorHash, projectPath);
      const savedId = saveTerminalError({
        command: ctx.command,
        exit_code: ctx.exit_code,
        error_hash: ctx.errorHash,
        error_text: ctx.errorText,
        cwd: ctx.cwd,
        project_path: projectPath
      });
      mainWindow?.webContents.send("terminal-error", {
        ...ctx,
        id: savedId,
        pastOccurrences: pastHistory.length + 1,
        lastSeen: pastHistory[0]?.created_at ?? null
      });
    }
  );
  ipcMain.handle("get-scans", () => {
    const cfg = loadConfig();
    return getLatestScans(cfg.projectPath);
  });
  ipcMain.handle("get-edges", () => lastEdges);
  ipcMain.handle("get-functions", (_e, filePath) => getFunctions(filePath));
  ipcMain.handle("save-feedback", (_e, filePath, action, score) => {
    saveFeedback(filePath, action, score);
  });
  ipcMain.handle("get-score-history", (_e, filePath) => getScoreHistory(filePath));
  ipcMain.handle("get-feedback-history", (_e, filePath) => getFeedbackHistory(filePath));
  ipcMain.handle("get-socket-port", () => socketServer.port);
  ipcMain.handle(
    "get-terminal-error-history",
    (_e, hash, projectPath) => getTerminalErrorHistory(hash, projectPath)
  );
  ipcMain.on("ask-llm", (_e, ctx) => {
    askLLM(
      ctx,
      (chunk) => mainWindow?.webContents.send("llm-chunk", chunk),
      () => mainWindow?.webContents.send("llm-done"),
      (err) => mainWindow?.webContents.send("llm-error", err)
    );
  });
  ipcMain.on("analyze-terminal-error", (_e, ctx) => {
    let llmAccumulated = "";
    askLLMForError(
      ctx,
      lastTopFiles.slice(0, 5),
      ctx.pastOccurrences,
      (chunk) => {
        llmAccumulated += chunk;
        mainWindow?.webContents.send("llm-chunk", chunk);
      },
      () => {
        mainWindow?.webContents.send("llm-done");
        if (ctx.id) updateTerminalErrorLLM(ctx.id, llmAccumulated);
      },
      (err) => mainWindow?.webContents.send("llm-error", err)
    );
  });
  ipcMain.on("resolve-terminal-error", (_e, id, resolved) => {
    updateTerminalErrorResolved(id, resolved);
  });
  createWindow();
  app.on("before-quit", () => {
    socketServer.stop();
    clipWatcher.stop();
  });
  runScan();
  const { emitter } = startWatcher();
  let scanTimeout = null;
  function sendEvent(type, file) {
    mainWindow?.webContents.send("pulse-event", { type, file: file ? file.split("/").pop() : void 0, ts: Date.now() });
  }
  const debouncedScan = (path2, eventType) => {
    sendEvent(eventType, path2);
    if (scanTimeout) clearTimeout(scanTimeout);
    scanTimeout = setTimeout(() => runScan(), 1500);
  };
  emitter.on("file:changed", (p) => debouncedScan(p, "changed"));
  emitter.on("file:added", (p) => debouncedScan(p, "added"));
  emitter.on("file:deleted", (p) => debouncedScan(p, "deleted"));
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
