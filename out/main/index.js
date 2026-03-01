import { app, ipcMain, BrowserWindow } from "electron";
import * as path from "node:path";
import path__default, { join } from "node:path";
import Database from "better-sqlite3";
import * as fs from "node:fs";
import fs__default from "node:fs";
import { SyntaxKind, Project } from "ts-morph";
import { simpleGit } from "simple-git";
import chokidar from "chokidar";
import { EventEmitter } from "node:events";
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
            scanned_at TEXT NOT NULL
        )
    `);
  try {
    db.exec(`ALTER TABLE scans ADD COLUMN churn_score REAL NOT NULL DEFAULT 0`);
    console.log("[Pulse] DB migrated: added churn_score column.");
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
}
function saveScan(result, projectPath) {
  const db = getDb();
  const stmt = db.prepare(`
        INSERT INTO scans (file_path, global_score, complexity_score, function_size_score, churn_score, language, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
  stmt.run(
    result.filePath,
    result.globalScore,
    result.details.complexityScore,
    result.details.functionSizeScore,
    result.details.churnScore,
    result.language ?? "unknown",
    projectPath,
    (/* @__PURE__ */ new Date()).toISOString()
  );
}
function saveFunctions(filePath, functions, projectPath) {
  const db = getDb();
  db.prepare(`DELETE FROM functions WHERE file_path = ?`).run(filePath);
  const stmt = db.prepare(`
        INSERT INTO functions (file_path, name, start_line, line_count, cyclomatic_complexity, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
  const now = (/* @__PURE__ */ new Date()).toISOString();
  for (const fn of functions) {
    stmt.run(filePath, fn.name, fn.startLine, fn.lineCount, fn.cyclomaticComplexity, projectPath, now);
  }
}
function getLatestScans(projectPath) {
  const db = getDb();
  const rows = db.prepare(`
        SELECT s.file_path, s.global_score, s.complexity_score, s.function_size_score,
            s.churn_score, s.language, s.scanned_at
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
      language: row.language,
      scannedAt: row.scanned_at,
      trend,
      feedback: fb?.action ?? null
    };
  });
}
function getFunctions(filePath) {
  return getDb().prepare(`
            SELECT name, start_line, line_count, cyclomatic_complexity
            FROM functions
            WHERE file_path = ?
            ORDER BY cyclomatic_complexity DESC
        `).all(filePath);
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
    return { name, startLine, lineCount, cyclomaticComplexity };
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
        functions.push({ name, startLine: i + 1, lineCount: fnLines.length, cyclomaticComplexity });
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
        ignore: raw.ignore ?? ["node_modules", ".git", "dist", "build", ".vite", "vendor", "__pycache__"]
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
  const maxComplexity = metrics.functions.length > 0 ? Math.max(...metrics.functions.map((fn) => fn.cyclomaticComplexity)) : 0;
  const maxFunctionSize = metrics.functions.length > 0 ? Math.max(...metrics.functions.map((fn) => fn.lineCount)) : 0;
  const complexityScore = clampedScore(maxComplexity, 3, 10);
  const functionSizeScore = clampedScore(maxFunctionSize, 20, 60);
  const churn = await getChurnScore(metrics.filePath);
  const churnScore = clampedScore(churn, 5, 20);
  const globalScore = complexityScore * 0.5 + functionSizeScore * 0.3 + churnScore * 0.2;
  return {
    filePath: metrics.filePath,
    language: metrics.language,
    globalScore,
    details: { complexityScore, functionSizeScore, churnScore }
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
  const base = path__default.resolve(dir, importPath);
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
      saveScan(riskScore, projectPath);
      saveFunctions(file, analysis.functions, projectPath);
      results.push(riskScore);
    } catch (error) {
      console.error(`[Pulse] Error analyzing ${path__default.basename(file)}:`, error);
    }
  }
  const edges = buildEdges(files, fileSources);
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
let mainWindow = null;
let lastEdges = [];
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
    mainWindow?.webContents.send("pulse-event", { type: "scan-done", count: result.files.length, edges: result.edges.length, ts: Date.now() });
    mainWindow?.webContents.send("scan-complete");
  } catch (err) {
    console.error("[Pulse] Scan error:", err);
    mainWindow?.webContents.send("pulse-event", { type: "scan-error", ts: Date.now() });
  }
}
app.whenReady().then(() => {
  initDb();
  ipcMain.handle("get-scans", () => {
    const config = loadConfig();
    return getLatestScans(config.projectPath);
  });
  ipcMain.handle("get-edges", () => lastEdges);
  ipcMain.handle("get-functions", (_e, filePath) => getFunctions(filePath));
  createWindow();
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
