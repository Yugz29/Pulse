import path from 'node:path';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { getLastFeedback } from '../database/db.js';
import { config } from '../config.js';



function getRiskEmoji(score: number): string {
    if (score >= config.thresholds.alert) return '🔴';
    if (score >= config.thresholds.warning) return '🟡';
    return '🟢';
}

export function printReport(results: RiskScoreResult[]): void {
    // Header
    console.log('-'.repeat(45));
    console.log(' PULSE - Rapport initial');
    console.log('-'.repeat(45));

    // Boucle sur chaque résultat
    for (const result of results) {
        const emoji = getRiskEmoji(result.globalScore);
        const fileName = path.basename(result.filePath);
        const score = result.globalScore.toFixed(1);
        const feedback = getLastFeedback(result.filePath);
        const feedbackTag = feedback ? `[${feedback.action}]` : '';
        console.log(`   ${emoji} ${fileName.padEnd(30)} ${score} ${feedbackTag}`);
    }

    // Footer
    const alerts = results.filter(r => r.globalScore >= config.thresholds.warning).length;
    console.log('-'.repeat(45));
    console.log(`  ${results.length} fichiers analysés | ${alerts} alerte(s)`);
}
