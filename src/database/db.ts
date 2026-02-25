import Database from 'better-sqlite3';
import type { RiskScoreResult } from '../risk-score/riskScore.js';


const db = new Database('pulse.db');

export function initDb() {
    // Table scans
    db.exec(`
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            global_score REAL NOT NULL,
            complexity_score REAL NOT NULL,
            function_size_score REAL NOT NULL,
            scanned_at TEXT NOT NULL
        )
    `);

    // Table feedbacks
    db.exec(`
        CREATE TABLE IF NOT EXISTS feedbacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            action TEXT NOT NULL,
            risk_score_at_time REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    `);
}

export function saveScan(result: RiskScoreResult) {
    const stmt = db.prepare(`
        INSERT INTO scans (file_path, global_score, complexity_score, function_size_score, scanned_at)
        VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(
        result.filePath,
        result.globalScore,
        result.details.complexityScore,
        result.details.functionSizeScore,
        new Date().toISOString()
    );
}

export function getHistory(filePath: string) {
    const stmt = db.prepare(`SELECT * FROM scans WHERE file_path = ? ORDER BY scanned_at DESC`);
    return stmt.all(filePath);
}

export function saveFeedback(filePath: string, action: string, riskScore: number) {
    const stmt = db.prepare(`
        INSERT INTO feedbacks (file_path, action, risk_score_at_time, created_at)
        VALUES (?, ?, ?, ?)
    `);
    stmt.run(filePath, action, riskScore, new Date().toISOString());
}

export function getLastFeedback(filePath: string) {
    const stmt = db.prepare(`
        SELECT * FROM feedbacks WHERE file_path = ? ORDER BY created_at DESC LIMIT 1
    `);
    return stmt.get(filePath) as { action: string, risk_score_at_time: number } | undefined;
}
