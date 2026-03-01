import fs from 'node:fs';
import type { FunctionMetrics } from '../analyzer/parser.js';

const OLLAMA_URL = 'http://localhost:11434/api/generate';
const MODEL      = 'qwen2.5-coder:7b-instruct-q4_K_M';

export interface LLMContext {
    filePath: string;
    globalScore: number;
    details: {
        complexityScore: number;
        functionSizeScore: number;
        churnScore: number;
        depthScore: number;
        paramScore: number;
    };
    functions: FunctionMetrics[];
    // Contexte enrichi
    importedBy: string[];       // fichiers qui importent ce fichier
    scoreHistory: { score: number; scanned_at: string }[]; // historique des scores
    feedbackHistory: { action: string; created_at: string }[]; // historique des feedbacks
}

function getFileName(p: string): string {
    return p.split('/').pop() ?? p;
}

function buildScoreTrend(history: { score: number; scanned_at: string }[]): string {
    if (history.length < 2) return 'Pas assez de données historiques.';
    const first = history[0]!.score;
    const last  = history[history.length - 1]!.score;
    const delta = last - first;
    const trend = delta > 5 ? '📈 en dégradation' : delta < -5 ? '📉 en amélioration' : '↔ stable';
    return `${trend} (${first.toFixed(1)} → ${last.toFixed(1)} sur ${history.length} scans)`;
}

function buildPrompt(ctx: LLMContext, source: string): string {
    const topFns = ctx.functions
        .filter(fn => fn.name !== 'anonymous')
        .sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity)
        .slice(0, 5)
        .map(fn => `  - ${fn.name}(): cx=${fn.cyclomaticComplexity}, ${fn.lineCount} lignes, profondeur=${fn.maxDepth}, params=${fn.parameterCount}`)
        .join('\n');

    const importedBySection = ctx.importedBy.length > 0
        ? `Ce fichier est importé par ${ctx.importedBy.length} autre(s) fichier(s) : ${ctx.importedBy.map(getFileName).join(', ')}. Un bug ici aurait un impact direct sur ces fichiers.`
        : 'Ce fichier n\'est importé par aucun autre fichier du projet (point d\'entrée ou module isolé).';

    const feedbackSection = ctx.feedbackHistory.length > 0
        ? `Historique des feedbacks : ${ctx.feedbackHistory.map(f => f.action).join(' → ')} (${ctx.feedbackHistory.length} action(s) enregistrée(s)).`
        : 'Aucun feedback enregistré pour ce fichier.';

    return `Tu es un expert en qualité de code. Analyse le fichier suivant et fournis des suggestions de refactorisation concrètes.

## Fichier : ${getFileName(ctx.filePath)}
## Score de risque : ${ctx.globalScore.toFixed(1)}/100

## Détail des métriques :
- Complexité cyclomatique : ${ctx.details.complexityScore.toFixed(1)}/100
- Taille des fonctions : ${ctx.details.functionSizeScore.toFixed(1)}/100
- Profondeur d'imbrication : ${ctx.details.depthScore.toFixed(1)}/100
- Nombre de paramètres : ${ctx.details.paramScore.toFixed(1)}/100
- Churn (fréquence de modification) : ${ctx.details.churnScore.toFixed(1)}/100

## Fonctions les plus complexes :
${topFns || '  (aucune)'}

## Impact dans le projet :
${importedBySection}

## Évolution du score :
${buildScoreTrend(ctx.scoreHistory)}

## Historique des actions développeur :
${feedbackSection}

## Code source :
\`\`\`
${source.slice(0, 6000)}${source.length > 6000 ? '\n... (tronqué)' : ''}
\`\`\`

Réponds en français. Structure ta réponse ainsi :
1. **Analyse** (3-4 phrases) : explique POURQUOI ce fichier est risqué en t'appuyant sur les métriques ET le code source.
2. **Suggestions** : liste 2-3 refactorisations concrètes avec exemples de code si pertinent. Priorise selon l'impact (commence par ce qui améliore le plus le score).
Sois direct et pratique. Tiens compte de la criticité du fichier (nombre de dépendants) dans ta priorisation.`;
}

export async function askLLM(
    ctx: LLMContext,
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
): Promise<void> {
    let source: string;
    try {
        source = fs.readFileSync(ctx.filePath, 'utf-8');
    } catch {
        onError(`Impossible de lire le fichier : ${ctx.filePath}`);
        return;
    }

    const prompt = buildPrompt(ctx, source);

    try {
        const res = await fetch(OLLAMA_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: MODEL, prompt, stream: true }),
        });

        if (!res.ok || !res.body) {
            onError(`Erreur Ollama : ${res.status} ${res.statusText}`);
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const lines = decoder.decode(value).split('\n').filter(Boolean);
            for (const line of lines) {
                try {
                    const json = JSON.parse(line) as { response?: string; done?: boolean };
                    if (json.response) onChunk(json.response);
                    if (json.done) { onDone(); return; }
                } catch { /* ligne incomplète */ }
            }
        }
        onDone();
    } catch (err) {
        onError(`Ollama inaccessible : ${err instanceof Error ? err.message : String(err)}`);
    }
}
