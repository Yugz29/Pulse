import fs from 'node:fs';
import path from 'node:path';
import { analyzeFile } from '../analyzer/parser.js';
import { calculateRiskScore } from '../risk-score/riskScore.js';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { config } from '../config.js';


export function getFiles(dir: string, ignore: string[], fileList: string[] = []): string[] {
    const entries = fs.readdirSync(dir);
    for (const entry of entries) {
        const fullPath = path.join(dir, entry);

        if (ignore.includes(entry)) continue;
        if (entry.endsWith('.min.js') || entry.startsWith('chunk-') || entry.includes('-')) continue;

        if (fs.statSync(fullPath).isDirectory()) {
            getFiles(fullPath, ignore, fileList);
        }

        if (fullPath.endsWith('.js') || fullPath.endsWith('.ts')) {
            fileList.push(fullPath);
        }
    }

    return fileList;
}

export async function scanProject(projectPath: string): Promise<RiskScoreResult[]> {
    const files = getFiles(projectPath, config.ignore);
    const results: RiskScoreResult[] = [];

    for (const file of files) {
        try {
            const analysis = analyzeFile(file);
            const riskScore = await calculateRiskScore(analysis);
            results.push(riskScore);
        } catch (error) {
            console.error(`Error analyzing file ${file}:`, error);
        }
    }

    return results.sort((a, b) => b.globalScore - a.globalScore);
}
