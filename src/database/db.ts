import Database from 'better-sqlite3';
import type { RiskScoreResult } from '../risk-score/riskScore.js';


const db = new Database('pulse.db');

export function initDb() {
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
