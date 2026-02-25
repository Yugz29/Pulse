import { startWatcher } from './watcher/watcher.js';
import { analyzeFile } from './analyzer/parser.js';
import { calculateRiskScore } from './risk-score/riskScore.js';
import { initDb, saveScan } from './database/db.js';
import { scanProject } from './cli/scanner.js';
import { printReport } from './cli/display.js';


// Init de la DB
console.log('Pulse is initializing the database...');
initDb();

console.log('Pulse is scanning the project...');
const results = scanProject('/Users/yugz/Projets/DevNote/');
printReport(results);

console.log('Pulse is watching...');

const emitter = startWatcher();

// Quand un fichier est modifié, on le passe au parser
emitter.on('file:changed', (filePath: string) => {
    console.log(`\n[CHANGED] ${filePath}`);
    try {
        const metrics = analyzeFile(filePath);
        const result = calculateRiskScore(metrics);
        saveScan(result);

        console.log(`  → RiskScore: ${result.globalScore.toFixed(1)} | complexité: ${result.details.complexityScore.toFixed(1)} | taille: ${result.details.functionSizeScore.toFixed(1)}`);
        console.log(`  → ${metrics.totalFunctions} fonction(s), ${metrics.totalLines} lignes`);
        for (const fn of metrics.functions) {
            console.log(`     • ${fn.name}() — complexité: ${fn.cyclomaticComplexity}, lignes: ${fn.lineCount}`);
        }
    } catch (err) {
        console.error(`  → Impossible d'analyser ce fichier :`, err);
    }
});

emitter.on('file:added', (filePath: string) => {
    console.log(`[ADDED]   ${filePath}`);
});

emitter.on('file:deleted', (filePath: string) => {
    console.log(`[DELETED] ${filePath}`);
});
