import Database from 'better-sqlite3';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { join } from 'node:path';
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
        console.log('[Pulse] DB migrated: added churn_score column.');
    } catch { }

    try {
        db.exec(`ALTER TABLE scans ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
        console.log('[Pulse] DB migrated: added project_path to scans.');
    } catch { }

    try {
        db.exec(`ALTER TABLE functions ADD COLUMN project_path TEXT NOT NULL DEFAULT ''`);
        console.log('[Pulse] DB migrated: added project_path to functions.');
    } catch { }
}

// ── WRITE ──

export function saveScan(result: RiskScoreResult, projectPath: string): void {
    const db   = getDb();
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
        INSERT INTO functions (file_path, name, start_line, line_count, cyclomatic_complexity, project_path, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    const now = new Date().toISOString();
    for (const fn of functions) {
        stmt.run(filePath, fn.name, fn.startLine, fn.lineCount, fn.cyclomaticComplexity, projectPath, now);
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
    language: string;
    scannedAt: string;
    trend: '↑' | '↓' | '↔';
    feedback: string | null;
}

export function getLatestScans(projectPath: string): LatestScan[] {
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
    `).all(projectPath) as {
        file_path: string;
        global_score: number;
        complexity_score: number;
        function_size_score: number;
        churn_score: number;
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
            language:          row.language,
            scannedAt:         row.scanned_at,
            trend,
            feedback:          fb?.action ?? null,
        };
    });
}

export function getFunctions(filePath: string) {
    return getDb()
        .prepare(`
            SELECT name, start_line, line_count, cyclomatic_complexity
            FROM functions
            WHERE file_path = ?
            ORDER BY cyclomatic_complexity DESC
        `)
        .all(filePath) as { name: string; start_line: number; line_count: number; cyclomatic_complexity: number }[];
}
