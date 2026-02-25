import { startWatcher } from './watcher/watcher.js';
import { analyzeFile } from './analyzer/parser.js';
import { calculateRiskScore } from './risk-score/riskScore.js';
import { initDb, saveScan } from './database/db.js';
import { scanProject } from './cli/scanner.js';
import { printReport } from './cli/display.js';
import { promptFeedback } from './cli/prompt.js';
import { config } from './config.js';



console.log('Pulse is initializing the database...');
initDb();

console.log('Pulse is scanning the project...');
const results = scanProject(config.projectPath);
printReport(results);
await promptFeedback(results);

console.log('Pulse is watching...');
const emitter = startWatcher();

// Quand un fichier est modifié, on le passe au parser
const debounceTimers = new Map<string, NodeJS.Timeout>();

emitter.on('file:changed', (filePath: string) => {
    // Si un timer existe déjà pour ce fichier, on l'annule
    const existing = debounceTimers.get(filePath);
    if (existing) clearTimeout(existing);

    // On crée un nouveau timer
    const timer = setTimeout(() => {
        debounceTimers.delete(filePath);
        console.log(`\n[CHANGED] ${filePath}`);
        try {
            const metrics = analyzeFile(filePath);
            const result = calculateRiskScore(metrics);
            saveScan(result);

            console.log(`  → RiskScore: ${result.globalScore.toFixed(1)} | complexité: ${result.details.complexityScore.toFixed(1)} | taille: ${result.details.functionSizeScore.toFixed(1)}`);
            console.log(`  → ${metrics.totalFunctions} fonction(s), ${metrics.totalLines} lignes`);
        } catch (err) {
            console.error(`  → Impossible d'analyser ce fichier :`, err);
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
