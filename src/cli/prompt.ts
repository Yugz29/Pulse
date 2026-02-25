import readLine from 'node:readline';
import path from 'node:path';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { saveFeedback } from '../database/db.js';


function ask(rl: readLine.Interface, question: string): Promise<string> {
    return new Promise(resolve => {
        rl.question(question, resolve);
    });
}

export async function promptFeedback(results: RiskScoreResult []): Promise<void> {
    const rl = readLine.createInterface({
        input: process.stdin,
        output: process.stdout
    });

    // Afficher la liste numérotée
    results.forEach((result, index) => {
        console.log(` ${index + 1}. ${path.basename(result.filePath)} - ${result.globalScore.toFixed(1)}`);
    });

    // Demander quel fichier ?
    const fileAnswer = await ask(rl, '\nNuméro du fichier à traiter (ou "q" pour quitter) : ');
    if (fileAnswer === 'q') { rl.close(); return; }

    const fileIndex = parseInt(fileAnswer) - 1;
    const selected = results[fileIndex];
    if (!selected) { console.log('Numéro invalide.'); rl.close(); return; }

    // Demander l'action
    const action = await ask(rl, 'Action (apply / ignore / explore) : ');
    if (!['apply', 'ignore', 'explore'].includes(action)) {
        console.log('Action invalide.'); rl.close(); return;
    }

    // Sauvegarder
    saveFeedback(selected.filePath, action, selected.globalScore);
    console.log(`✓ Feedback "${action}" enregistré pour ${path.basename(selected.filePath)}`);

    rl.close();
}
