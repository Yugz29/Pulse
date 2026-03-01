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

function getDb(): InstanceType<typeof Database> {
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

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN parameter_count INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added parameter_count to functions.');
    } catch { }

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN max_depth INTEGER NOT NULL DEFAULT 0`);
        console.log('[Pulse] DB migrated: added max_depth to functions.');
    } catch { }
}

// ── WRITE ──

export function saveScan(result: RiskScoreResult, projectPath: string): void {
    const db   = getDb();
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
        result.language ?? 'unknown',
        projectPath,
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
        INSERT INTO functions (file_path, name, start_line, line_count, cyclomatic_complexity, parameter_count, max_depth, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const now = new Date().toISOString();
    for (const fn of functions) {
        stmt.run(filePath, fn.name, fn.startLine, fn.lineCount, fn.cyclomaticComplexity, fn.parameterCount, fn.maxDepth, projectPath, now);
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
}

export function getLatestScans(projectPath: string): LatestScan[] {
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
    `).all(projectPath) as {
        file_path: string;
        global_score: number;
        complexity_score: number;
        function_size_score: number;
        churn_score: number;
        depth_score: number;
        param_score: number;
        fan_in: number;
        fan_out: number;
        language: string;
        scanned_at: string;
    }[];

    return rows.map(row => {
        // Trend
        const prev = db.prepare(`
            SELECT global_score FROM scans
            WHERE file_path = ? AND scanned_at < ?
            ORDER BY scanned_at DESC LIMIT 1
        `).get(row.file_path, row.scanned_at) as { global_score: number } | undefined;

        let trend: '↑' | '↓' | '↔' = '↔';
        if (prev) {
            const delta = row.global_score - prev.global_score;
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
        };
    });
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
            deleted++;
        }
    }
    return deleted;
}

export function getFunctions(filePath: string) {
    return getDb()
        .prepare(`
            SELECT name, start_line, line_count, cyclomatic_complexity, parameter_count, max_depth
            FROM functions
            WHERE file_path = ?
            ORDER BY cyclomatic_complexity DESC
        `)
        .all(filePath) as { name: string; start_line: number; line_count: number; cyclomatic_complexity: number; parameter_count: number; max_depth: number }[];
}
