import Database from 'better-sqlite3';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { join } from 'node:path';
import { existsSync } from 'node:fs';
import { app } from 'electron';
import type { FunctionMetrics } from '../analyzer/parser.js';


// ── DB INSTANCE (lazy) ──
// On n'ouvre pas la DB à l'import du module, mais au premier appel à getDb().
// Cela garantit que app.getPath('userData') est disponible (app ready).

let _db: InstanceType<typeof Database> | null = null;

export function getDb(): InstanceType<typeof Database> {
    if (_db) return _db;

    const dbPath = app?.getPath
        ? join(app.getPath('userData'), 'pulse.db')
        : join(process.cwd(), 'pulse.db');

    console.log(`[Pulse] Opening DB at: ${dbPath}`);
    _db = new Database(dbPath);
    return _db;
}

// ── INIT ──

export function initDb(): void {
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
        console.log('[Pulse] DB migrated: added churn_score column.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN depth_score REAL NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added depth_score to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN param_score REAL NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added param_score to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN fan_in INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added fan_in to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN fan_out INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added fan_out to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
        console.log('[Pulse] DB migrated: added project_path to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
        console.log('[Pulse] DB migrated: added project_path to functions.');
    } catch { }

    // Raw metric values (for adaptive baseline computation)
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_complexity   INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_complexity to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_function_size INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_function_size to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_depth        INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_depth to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_params       INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_params to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_churn        REAL    NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_churn to scans.');
    } catch { }

    // P2 — cognitive complexity
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN cognitive_complexity_score REAL NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added cognitive_complexity_score to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE scans ADD COLUMN raw_cognitive_complexity INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added raw_cognitive_complexity to scans.');
    } catch { }
    try {
        db.exec(`ALTER TABLE functions ADD COLUMN cognitive_complexity INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added cognitive_complexity to functions.');
    } catch { }

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN parameter_count INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added parameter_count to functions.');
    } catch { }

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN max_depth INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added max_depth to functions.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN llm_report TEXT`);
        console.log('[Pulse] DB migrated: added llm_report to scans.');
    } catch { }

    // ── TABLE intel_messages ──
    db.exec(`
        CREATE TABLE IF NOT EXISTS intel_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT    NOT NULL,
            role         TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            created_at   TEXT    NOT NULL
        )
    `);

    // ── TABLE intel_messages ──
    db.exec(`
        CREATE TABLE IF NOT EXISTS intel_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT    NOT NULL,
            role         TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            created_at   TEXT    NOT NULL
        )
    `);

    // ── TABLE llm_reports (persistance analyses LLM par fichier) ──
    db.exec(`
        CREATE TABLE IF NOT EXISTS llm_reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path    TEXT NOT NULL UNIQUE,
            report       TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
    `);

    // ── TABLE terminal_errors ──
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

// ── WRITE ──

export function saveScan(result: RiskScoreResult, projectPath: string): void {
    const db   = getDb();
    const stmt = db.prepare(`
        INSERT INTO scans (
            file_path, global_score,
            complexity_score, cognitive_complexity_score, function_size_score,
            churn_score, depth_score, param_score,
            fan_in, fan_out, language, project_path,
            raw_complexity, raw_cognitive_complexity, raw_function_size,
            raw_depth, raw_params, raw_churn,
            scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(
        result.filePath,
        result.globalScore,
        result.details.complexityScore,
        result.details.cognitiveComplexityScore,
        result.details.functionSizeScore,
        result.details.churnScore,
        result.details.depthScore,
        result.details.paramScore,
        result.details.fanIn,
        result.details.fanOut,
        result.language ?? 'unknown',
        projectPath,
        result.raw.complexity,
        result.raw.cognitiveComplexity,
        result.raw.functionSize,
        result.raw.depth,
        result.raw.params,
        result.raw.churn,
        new Date().toISOString()
    );
}

export function saveFeedback(filePath: string, action: string, riskScore: number): void {
    const db   = getDb();
    const stmt = db.prepare(`
        INSERT INTO feedbacks (file_path, action, risk_score_at_time, created_at)
        VALUES (?, ?, ?, ?)
    `);
    stmt.run(filePath, action, riskScore, new Date().toISOString());
}

export function saveFunctions(filePath: string, functions: FunctionMetrics[], projectPath: string): void {
    const db = getDb();
    db.prepare(`DELETE FROM functions WHERE file_path = ?`).run(filePath);
    const stmt = db.prepare(`
        INSERT INTO functions (file_path, name, start_line, line_count, cyclomatic_complexity, cognitive_complexity, parameter_count, max_depth, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const now = new Date().toISOString();
    for (const fn of functions) {
        stmt.run(filePath, fn.name, fn.startLine, fn.lineCount, fn.cyclomaticComplexity, fn.cognitiveComplexity ?? 0, fn.parameterCount, fn.maxDepth, projectPath, now);
    }
}

// ── READ ──

export function getHistory(filePath: string) {
    return getDb()
        .prepare(`SELECT * FROM scans WHERE file_path = ? ORDER BY scanned_at DESC`)
        .all(filePath);
}

export function getLastFeedback(filePath: string) {
    return getDb()
        .prepare(`SELECT * FROM feedbacks WHERE file_path = ? ORDER BY created_at DESC LIMIT 1`)
        .get(filePath) as { action: string; risk_score_at_time: number } | undefined;
}

export function getPreviousScore(filePath: string): number | undefined {
    const rows = getDb()
        .prepare(`SELECT global_score FROM scans WHERE file_path = ? ORDER BY scanned_at DESC LIMIT 2`)
        .all(filePath) as { global_score: number }[];
    return rows[1]?.global_score;
}

// ── LATEST SCANS (pour le renderer) ──

export interface LatestScan {
    filePath: string;
    globalScore: number;
    complexityScore: number;
    cognitiveComplexityScore: number;  // P2
    functionSizeScore: number;
    churnScore: number;
    depthScore: number;
    paramScore: number;
    fanIn: number;
    fanOut: number;
    language: string;
    scannedAt: string;
    trend: '↑' | '↓' | '↔';
    feedback: string | null;
    rawComplexity: number;
    rawCognitiveComplexity: number;    // P2
    rawFunctionSize: number;
    rawDepth: number;
    rawParams: number;
    rawChurn: number;
}

export function getLatestScans(projectPath: string): LatestScan[] {
    const db = getDb();

    const rows = db.prepare(`
        SELECT s.file_path, s.global_score,
            s.complexity_score, s.cognitive_complexity_score, s.function_size_score,
            s.churn_score, s.depth_score, s.param_score, s.fan_in, s.fan_out, s.language, s.scanned_at,
            s.raw_complexity, s.raw_cognitive_complexity, s.raw_function_size,
            s.raw_depth, s.raw_params, s.raw_churn
        FROM scans s
        INNER JOIN (
            SELECT MAX(id) as max_id
            FROM scans
            WHERE project_path = ?
            GROUP BY file_path
        ) latest ON s.id = latest.max_id
        ORDER BY s.global_score DESC
    `).all(projectPath) as {
        file_path: string;
        global_score: number;
        complexity_score: number;
        cognitive_complexity_score: number;
        function_size_score: number;
        churn_score: number;
        depth_score: number;
        param_score: number;
        fan_in: number;
        fan_out: number;
        language: string;
        scanned_at: string;
        raw_complexity: number;
        raw_cognitive_complexity: number;
        raw_function_size: number;
        raw_depth: number;
        raw_params: number;
        raw_churn: number;
    }[];

    // Baseline du jour : date locale sous forme YYYY-MM-DD
    const today = new Date().toISOString().slice(0, 10);
    const todayStart = `${today}T00:00:00.000Z`;

    return rows.map(row => {
        // Trend : compare le score actuel avec le 1er scan du jour
        // Si pas de scan ce jour → compare avec le dernier scan d'hier ou avant
        const baseline = db.prepare(`
            SELECT global_score FROM scans
            WHERE file_path = ?
              AND project_path = ?
              AND scanned_at >= ?
            ORDER BY scanned_at ASC LIMIT 1
        `).get(row.file_path, projectPath, todayStart) as { global_score: number } | undefined;

        // Fallback : dernier scan avant aujourd'hui
        const fallback = !baseline ? db.prepare(`
            SELECT global_score FROM scans
            WHERE file_path = ?
              AND project_path = ?
              AND scanned_at < ?
            ORDER BY scanned_at DESC LIMIT 1
        `).get(row.file_path, projectPath, todayStart) as { global_score: number } | undefined : undefined;

        const ref = baseline ?? fallback;

        let trend: '↑' | '↓' | '↔' = '↔';
        if (ref) {
            const delta = row.global_score - ref.global_score;
            if (delta > 2)  trend = '↑';
            if (delta < -2) trend = '↓';
        }

        // Feedback
        const fb = db.prepare(`
            SELECT action FROM feedbacks WHERE file_path = ? ORDER BY created_at DESC LIMIT 1
        `).get(row.file_path) as { action: string } | undefined;

        return {
            filePath:          row.file_path,
            globalScore:       row.global_score,
            complexityScore:   row.complexity_score,
            functionSizeScore: row.function_size_score,
            churnScore:        row.churn_score,
            depthScore:        row.depth_score,
            paramScore:        row.param_score,
            fanIn:             row.fan_in,
            fanOut:            row.fan_out,
            language:          row.language,
            scannedAt:         row.scanned_at,
            trend,
            feedback:          fb?.action ?? null,
            cognitiveComplexityScore: row.cognitive_complexity_score ?? 0,
            rawComplexity:            row.raw_complexity              ?? 0,
            rawCognitiveComplexity:   row.raw_cognitive_complexity    ?? 0,
            rawFunctionSize:          row.raw_function_size           ?? 0,
            rawDepth:                 row.raw_depth                   ?? 0,
            rawParams:                row.raw_params                  ?? 0,
            rawChurn:                 row.raw_churn                   ?? 0,
        };
    });
}

export function getFeedbackHistory(filePath: string): { action: string; created_at: string }[] {
    return getDb()
        .prepare(`SELECT action, created_at FROM feedbacks WHERE file_path = ? ORDER BY created_at ASC LIMIT 20`)
        .all(filePath) as { action: string; created_at: string }[];
}

export function getScoreHistory(filePath: string): { score: number; scanned_at: string }[] {
    return getDb()
        .prepare(`
            SELECT global_score as score, scanned_at
            FROM scans
            WHERE file_path = ?
            ORDER BY scanned_at ASC
            LIMIT 30
        `)
        .all(filePath) as { score: number; scanned_at: string }[];
}

// Average global score per scan session (grouped by date), for project-level trend
export function getProjectScoreHistory(projectPath: string): { date: string; score: number }[] {
    return getDb()
        .prepare(`
            SELECT substr(scanned_at, 1, 10) as date, AVG(global_score) as score
            FROM scans
            WHERE project_path = ?
            GROUP BY substr(scanned_at, 1, 10)
            ORDER BY date ASC
            LIMIT 30
        `)
        .all(projectPath) as { date: string; score: number }[];
}

export function cleanDeletedFiles(): number {
    const db = getDb();
    const files = db.prepare(`SELECT DISTINCT file_path FROM scans`).all() as { file_path: string }[];
    let deleted = 0;
    for (const { file_path } of files) {
        if (!existsSync(file_path)) {
            db.prepare(`DELETE FROM scans WHERE file_path = ?`).run(file_path);
            db.prepare(`DELETE FROM functions WHERE file_path = ?`).run(file_path);
            db.prepare(`DELETE FROM feedbacks WHERE file_path = ?`).run(file_path);
            db.prepare(`DELETE FROM llm_reports WHERE file_path = ?`).run(file_path);
            deleted++;
        }
    }
    return deleted;
}

export function saveLlmReport(filePath: string, report: string): void {
    getDb().prepare(`
        INSERT INTO llm_reports (file_path, report, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET report = excluded.report, updated_at = excluded.updated_at
    `).run(filePath, report, new Date().toISOString());
}

export function getLlmReport(filePath: string): string | null {
    const row = getDb()
        .prepare(`SELECT report FROM llm_reports WHERE file_path = ?`)
        .get(filePath) as { report: string } | undefined;
    return row?.report ?? null;
}

export function getFunctions(filePath: string) {
    return getDb()
        .prepare(`
            SELECT name, start_line, line_count, cyclomatic_complexity, cognitive_complexity, parameter_count, max_depth
            FROM functions
            WHERE file_path = ?
            ORDER BY cyclomatic_complexity DESC
        `)
        .all(filePath) as { name: string; start_line: number; line_count: number; cyclomatic_complexity: number; cognitive_complexity: number; parameter_count: number; max_depth: number }[];
}

// ── TERMINAL ERRORS ──

export interface TerminalErrorRow {
    id: number;
    command: string;
    exit_code: number;
    error_hash: string;
    error_text: string;
    cwd: string;
    project_path: string;
    llm_response: string | null;
    resolved: number;
    created_at: string;
}

export function saveTerminalError(params: {
    command: string;
    exit_code: number;
    error_hash: string;
    error_text: string;
    cwd: string;
    project_path: string;
}): number {
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
        new Date().toISOString(),
    );
    return result.lastInsertRowid as number;
}

export function getTerminalErrorHistory(errorHash: string, projectPath: string): Pick<TerminalErrorRow, 'id' | 'command' | 'created_at' | 'resolved'>[] {
    return getDb()
        .prepare(`
            SELECT id, command, created_at, resolved
            FROM terminal_errors
            WHERE error_hash = ? AND project_path = ?
            ORDER BY created_at DESC
            LIMIT 20
        `)
        .all(errorHash, projectPath) as Pick<TerminalErrorRow, 'id' | 'command' | 'created_at' | 'resolved'>[];
}

export function updateTerminalErrorResolved(id: number, resolved: 1 | -1): void {
    getDb()
        .prepare(`UPDATE terminal_errors SET resolved = ? WHERE id = ?`)
        .run(resolved, id);
}

export function updateTerminalErrorLLM(id: number, llmResponse: string): void {
    getDb()
        .prepare(`UPDATE terminal_errors SET llm_response = ? WHERE id = ?`)
        .run(llmResponse, id);
}

// ── INTEL MESSAGES ──

export interface IntelMessageRow {
    id: number;
    role: 'user' | 'assistant';
    content: string;
    created_at: string;
}

export function saveIntelMessage(projectPath: string, role: 'user' | 'assistant', content: string): void {
    getDb()
        .prepare(`INSERT INTO intel_messages (project_path, role, content, created_at) VALUES (?, ?, ?, ?)`)
        .run(projectPath, role, content, new Date().toISOString());
}

export function getIntelMessages(projectPath: string, limit = 60): IntelMessageRow[] {
    return getDb()
        .prepare(`
            SELECT id, role, content, created_at
            FROM intel_messages
            WHERE project_path = ?
            ORDER BY created_at ASC
            LIMIT ?
        `)
        .all(projectPath, limit) as IntelMessageRow[];
}

export function clearIntelMessages(projectPath: string): void {
    getDb()
        .prepare(`DELETE FROM intel_messages WHERE project_path = ?`)
        .run(projectPath);
}

// ── PROJECT HOTSPOTS ──

export interface HotspotRow {
    file_path:        string;
    global_score:     number;
    complexity_score: number;
    churn_score:      number;
    fan_in:           number;
    language:         string;
    hotspot_score:    number;
    scanned_at:       string;
}

export function getProjectHotspots(projectPath: string, limit = 15): HotspotRow[] {
    return getDb()
        .prepare(`
            SELECT
                file_path,
                global_score,
                complexity_score,
                churn_score,
                fan_in,
                language,
                scanned_at,
                ROUND(global_score * churn_score / 100.0, 1) AS hotspot_score
            FROM scans
            WHERE project_path = ?
              AND churn_score  > 0
            ORDER BY hotspot_score DESC
            LIMIT ?
        `)
        .all(projectPath, limit) as HotspotRow[];
}

// Fichiers complexes mais stables (complexité élevée, peu de churn)
export function getComplexStableFiles(projectPath: string, limit = 10): HotspotRow[] {
    return getDb()
        .prepare(`
            SELECT
                file_path,
                global_score,
                complexity_score,
                churn_score,
                fan_in,
                language,
                scanned_at,
                ROUND(global_score * churn_score / 100.0, 1) AS hotspot_score
            FROM scans
            WHERE project_path = ?
              AND complexity_score >= 40
              AND churn_score      < 20
            ORDER BY complexity_score DESC
            LIMIT ?
        `)
        .all(projectPath, limit) as HotspotRow[];
}

