import { startWatcher } from './watcher/watcher.js';
import { analyzeFile } from './analyzer/parser.js';
import { calculateRiskScore } from './risk-score/riskScore.js';
import { initDb, saveScan } from './database/db.js';
import { scanProject } from './cli/scanner.js';
import { printReport } from './cli/display.js';
import { promptFeedback, promptSingleFeedback } from './cli/prompt.js';
import { config } from './config.js';


console.log('Pulse is initializing the database...');
initDb();

console.log('Pulse is scanning the project...');
const results = await scanProject(config.projectPath);
printReport(results);
await promptFeedback(results);

console.log('\nPulse is watching...');
const { emitter, pause, resume } = startWatcher();

let isPrompting = false;
const debounceTimers = new Map<string, NodeJS.Timeout>();

emitter.on('file:changed', (filePath: string) => {
    if (isPrompting) return;

    const existing = debounceTimers.get(filePath);
    if (existing) clearTimeout(existing);

    const timer = setTimeout(async () => {
        debounceTimers.delete(filePath);
        console.log(`\n[CHANGED] ${filePath}`);
        try {
            const metrics = analyzeFile(filePath);
            const result = await calculateRiskScore(metrics);
            saveScan(result);

            console.log(`  → RiskScore: ${result.globalScore.toFixed(1)} | complexité: ${result.details.complexityScore.toFixed(1)} | taille: ${result.details.functionSizeScore.toFixed(1)} | churn: ${result.details.churnScore.toFixed(1)}`);
            console.log(`  → ${metrics.totalFunctions} fonction(s), ${metrics.totalLines} lignes`);

            if (result.globalScore >= config.thresholds.alert) {
                isPrompting = true;
                pause();
                await promptSingleFeedback(result);
                resume();
                isPrompting = false;
            }
        } catch (err) {
            console.error(`  → Impossible d'analyser ce fichier :`, err);
            isPrompting = false;
        }
    }, 500);

    debounceTimers.set(filePath, timer);
});

emitter.on('file:added', (filePath: string) => {
    console.log(`[ADDED]   ${filePath}`);
});

emitter.on('file:deleted', (filePath: string) => {
    console.log(`[DELETED] ${filePath}`);
});
