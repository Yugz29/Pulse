import type { FunctionMetrics } from '../../cortex/analyzer/parser.js';
import type { TerminalErrorContext } from '../../app/main/terminal/clipboardWatcher.js';
import type { ChatMessage } from './config.js';

export interface LLMContext {
    filePath:    string;
    globalScore: number;
    details: {
        complexityScore:    number;
        functionSizeScore:  number;
        churnScore:         number;
        depthScore:         number;
        paramScore:         number;
    };
    rawValues?: {
        complexity:          number;
        cognitiveComplexity: number;
        functionSize:        number;
        depth:               number;
        params:              number;
        churn:               number;
    };
    functions:       FunctionMetrics[];
    importedBy:      string[];
    scoreHistory:    { score: number; scanned_at: string }[];
    feedbackHistory: { action: string; created_at: string }[];
}

export interface IntelScan {
    filePath:          string;
    globalScore:       number;
    complexityScore:   number;
    functionSizeScore: number;
    churnScore:        number;
    depthScore:        number;
    paramScore:        number;
    fanIn:             number;
    fanOut:            number;
    trend:             string;
    language:          string;
}

export interface ProjectContext {
    projectPath:    string;
    allScansCount:  number;
    edgesCount:     number;
    distribution:   { stable: number; stressed: number; critical: number };
    topScans:       IntelScan[];
    topFanIn:       { filePath: string; fanIn: number }[];
    degrading:      { filePath: string; globalScore: number }[];
    projectHistory: { date: string; score: number }[];
    selectedFile?:  { filePath: string; globalScore: number } | null;
}

export interface IntelMessage {
    role:    'user' | 'assistant';
    content: string;
}

function getFileName(p: string): string {
    return p.split('/').pop() ?? p;
}

function buildScoreTrend(history: { score: number; scanned_at: string }[]): string {
    if (history.length < 2) return 'Pas assez de données historiques.';
    const first = history[0]!.score;
    const last  = history[history.length - 1]!.score;
    const delta = last - first;
    const trend = delta > 5 ? 'en dégradation' : delta < -5 ? 'en amélioration' : 'stable';
    return `${trend} (${first.toFixed(1)} → ${last.toFixed(1)} sur ${history.length} scans)`;
}

function signalComplexity(cx: number): string {
    if (cx >= 15) return `${cx} ⚠️ très élevé`;
    if (cx >= 10) return `${cx} ⚠️ élevé`;
    if (cx >= 6)  return `${cx} modéré`;
    return `${cx} ok`;
}
function signalLines(lines: number): string {
    if (lines >= 80) return `${lines}L ⚠️ très longue`;
    if (lines >= 40) return `${lines}L ⚠️ longue`;
    return `${lines}L`;
}
function signalDepth(depth: number): string {
    if (depth >= 5) return `${depth} ⚠️ profond`;
    if (depth >= 3) return `${depth} modéré`;
    return `${depth} ok`;
}
function signalChurn(commits: number): string {
    if (commits >= 20) return `${commits} commits/30j ⚠️ très instable`;
    if (commits >= 10) return `${commits} commits/30j — instable`;
    return `${commits} commits/30j`;
}

function buildFileBlueprint(source: string, functions: FunctionMetrics[]): string {
    const lines      = source.split('\n');
    const totalLines = lines.length;
    const named      = functions.filter(fn => fn.name !== 'anonymous' && fn.lineCount > 0);

    const critical = named.filter(fn => fn.cyclomaticComplexity >= 10 || fn.lineCount >= 60);
    const stressed = named.filter(fn => !critical.includes(fn) && (fn.cyclomaticComplexity >= 6 || fn.lineCount >= 30 || fn.maxDepth >= 3));
    const healthy  = named.filter(fn => !critical.includes(fn) && !stressed.includes(fn));

    const formatFn = (fn: FunctionMetrics) =>
        `  ${fn.name}() — ${fn.lineCount}L, cx=${fn.cyclomaticComplexity}, depth=${fn.maxDepth}, ${fn.parameterCount}p`;

    const structureLines: string[] = [];
    structureLines.push(`Fichier : ${totalLines} lignes, ${named.length} fonctions nommées`);
    if (critical.length) structureLines.push(`⚠️  Critique (${critical.length}) :\n${critical.map(formatFn).join('\n')}`);
    if (stressed.length) structureLines.push(`⚡  Surveiller (${stressed.length}) :\n${stressed.map(formatFn).join('\n')}`);
    if (healthy.length)  structureLines.push(`✅  Sain (${healthy.length}) : ${healthy.map(f => f.name).join(', ')}`);

    const blueprint = structureLines.join('\n\n');

    const isLarge  = totalLines > 400;
    const toShow   = isLarge
        ? critical.sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity).slice(0, 2)
        : [...critical, ...stressed].sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity).slice(0, 4);

    const maxBodyLines  = isLarge ? 30 : 50;
    const codeSections: string[] = [];
    for (const fn of toShow) {
        const startIdx  = fn.startLine - 1;
        const bodyLines = lines.slice(startIdx, startIdx + fn.lineCount);
        const truncated = bodyLines.length > maxBodyLines;
        const body = bodyLines.slice(0, maxBodyLines).join('\n')
            + (truncated ? `\n  // ... (+${fn.lineCount - maxBodyLines} lignes tronquées)` : '');
        codeSections.push(`### ${fn.name}()  [cx=${fn.cyclomaticComplexity}, ${fn.lineCount}L, depth=${fn.maxDepth}]\n\`\`\`\n${body}\n\`\`\``);
    }

    let importsSection = '';
    if (!isLarge) {
        const importLines: string[] = [];
        for (let i = 0; i < Math.min(25, lines.length); i++) {
            const t = (lines[i] ?? '').trim();
            if (t.startsWith('import') || t.startsWith('from ') || t.startsWith('require(') || t === '') {
                importLines.push(lines[i] ?? '');
            } else if (importLines.some(l => l.trim().startsWith('import') || l.trim().startsWith('from'))) {
                break;
            }
        }
        const filtered = importLines.filter(l => l.trim()).join('\n').trim();
        if (filtered) importsSection = `### Dépendances\n\`\`\`\n${filtered}\n\`\`\`\n\n`;
    }

    const result = [`### Structure du fichier\n${blueprint}`, importsSection, ...codeSections]
        .filter(Boolean).join('\n\n');

    return result.length > 3000 ? result.slice(0, 3000) + '\n// ... (tronqué)' : result;
}

export function buildAnalysisMessages(ctx: LLMContext, source: string, memorySnapshot?: string): ChatMessage[] {
    const codeContext    = buildFileBlueprint(source, ctx.functions);
    const fileName       = getFileName(ctx.filePath);
    const notableFns     = ctx.functions
        .filter(fn => fn.name !== 'anonymous')
        .filter(fn => fn.cyclomaticComplexity >= 6 || fn.lineCount >= 40 || fn.maxDepth >= 3)
        .sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity)
        .slice(0, 5);

    const fnSummary = notableFns.length > 0
        ? notableFns.map(fn =>
            `  - ${fn.name}() — ${signalLines(fn.lineCount)}, cx=${signalComplexity(fn.cyclomaticComplexity)}, depth=${signalDepth(fn.maxDepth)}, ${fn.parameterCount} param(s)`
          ).join('\n')
        : '  (aucune fonction ne dépasse les seuils)';

    const couplingSection = ctx.importedBy.length > 0
        ? `Ce fichier est importé par ${ctx.importedBy.length} autre(s) module(s) : ${ctx.importedBy.map(getFileName).join(', ')}. Une régression ici se propage directement.`
        : 'Non importé par d\'autres fichiers (module isolé ou point d\'entrée).';

    const rawChurn   = ctx.rawValues?.churn ?? Math.round((ctx.details.churnScore / 100) * 20);
    const churnSignal = signalChurn(rawChurn);
    const rawCog     = ctx.rawValues?.cognitiveComplexity ?? 0;
    const cogSignal  = rawCog >= 25 ? `${rawCog} ⚠️ très élevé`
                     : rawCog >= 12 ? `${rawCog} ⚠️ élevé`
                     : rawCog >= 6  ? `${rawCog} modéré`
                     : rawCog > 0   ? `${rawCog} ok`
                     : null;

    const lastFeedback  = ctx.feedbackHistory[ctx.feedbackHistory.length - 1];
    const feedbackNote  = lastFeedback?.action === 'ignore'
        ? '\nNote : le développeur a précédemment ignoré une alerte sur ce fichier. Sois précis et factuel, évite l\'alarmisme.'
        : lastFeedback?.action === 'apply'
        ? '\nNote : le développeur a déjà appliqué des corrections sur ce fichier. Concentre-toi sur ce qui reste.'
        : '';

    const trendLine = buildScoreTrend(ctx.scoreHistory);
    const allFunctionNames = ctx.functions
        .filter(fn => fn.name !== 'anonymous').map(fn => fn.name).join(', ');

    const system: ChatMessage = {
        role:    'system',
        content: 'Tu es Pulse, un assistant expert en qualité de code intégré dans l\'éditeur du développeur. '
            + 'Tu donnes des diagnostics courts, précis et actionnables. '
            + 'RÈGLE ABSOLUE : tu ne cites QUE des noms visibles dans le contexte fourni (fonctions, composants, variables). '
            + 'Tu n\'inventes jamais de noms absents du contexte. Si le fichier est tronqué, tu travailles avec ce qui est visible. '
            + 'Tu traduits les métriques en problèmes concrets sans répéter les chiffres bruts. '
            + 'Tu réponds en français, de manière directe.'
            + feedbackNote,
    };

    const user: ChatMessage = {
        role:    'user',
        content: `Diagnostique ce fichier.\n\n## ${fileName}\n\n${codeContext}\n\n## Toutes les fonctions détectées (${ctx.functions.filter(f => f.name !== 'anonymous').length} au total)\n${allFunctionNames || '(aucune)'}\n\n## Fonctions les plus à risque\n${fnSummary}\n\n## Signaux de santé\n- Churn : ${churnSignal}\n- Complexité cognitive : ${cogSignal ?? '(non disponible — relancer un scan)'}\n- Couplage : ${couplingSection}\n- Évolution : ${trendLine}\n\nIMPORTANT : cite uniquement des fonctions de la liste ci-dessus.\nRéponds en 2 blocs :\n**Diagnostic** : ce qui pose vraiment problème dans CE code (2-3 phrases, noms réels uniquement).\n**Priorité** : 1 ou 2 actions concrètes, ordonnées par impact.`
            + (memorySnapshot ? `\n\n${memorySnapshot}` : ''),
    };

    return [system, user];
}

export function buildProjectSystemPrompt(ctx: ProjectContext): string {
    const name = ctx.projectPath.split('/').pop() ?? ctx.projectPath;

    const trendStr = ctx.projectHistory.length >= 2
        ? (() => {
            const scores = ctx.projectHistory.map(h => h.score);
            const delta  = scores[scores.length - 1]! - scores[0]!;
            const dir    = delta > 1 ? 'degrading' : delta < -1 ? 'improving' : 'stable';
            return `${scores[0]!.toFixed(0)}->${scores[scores.length - 1]!.toFixed(0)} (${dir})`;
        })()
        : 'insufficient data';

    const topFiles = ctx.topScans.slice(0, 5).map((s, i) =>
        `${i + 1}. ${s.filePath.split('/').pop()} score=${s.globalScore.toFixed(0)} cx=${s.complexityScore.toFixed(0)} fan-in=${s.fanIn} ${s.trend}`
    ).join('\n');

    const fanInHubs = ctx.topFanIn.slice(0, 3)
        .map(s => `${s.filePath.split('/').pop()} (${s.fanIn} deps)`).join(', ');

    const degradingLine = ctx.degrading.length > 0
        ? `\nDegrading recently: ${ctx.degrading.map(f => `${f.filePath.split('/').pop()} (score=${f.globalScore.toFixed(0)} ↑)`).join(', ')}`
        : '';

    const selectedLine = ctx.selectedFile
        ? `\nSelected: ${ctx.selectedFile.filePath.split('/').pop()} (score ${ctx.selectedFile.globalScore.toFixed(0)})`
        : '';

    return `You are PULSE INTEL, a code quality expert. Answer in French, concisely and actionably.\n\nProject: ${name} | ${ctx.allScansCount} files | ${ctx.edgesCount} edges\nHealth: ${ctx.distribution.stable} stable, ${ctx.distribution.stressed} stressed, ${ctx.distribution.critical} critical\nTrend: ${trendStr}${degradingLine}${selectedLine}\n\nRiskiest files:\n${topFiles || 'none'}\n\nDependency hubs: ${fanInHubs || 'none'}\n\nRules: Be direct. Name specific files. Prioritize degrading files when relevant. Give actionable advice. No generic comments.`;
}

export function buildErrorPrompt(
    ctx: TerminalErrorContext,
    topFiles: { filePath: string; globalScore: number }[],
    pastOccurrences: number,
): string {
    const filesSection = topFiles.length > 0
        ? topFiles.map(f => `  - ${f.filePath.split('/').pop()} (risque: ${f.globalScore.toFixed(1)}/100)`).join('\n')
        : '  (aucun fichier analysé)';

    const recidive = pastOccurrences > 1
        ? `\n⚠️ **Récidive** : cette erreur a déjà été vue ${pastOccurrences} fois dans ce projet.\n`
        : '';

    return `Tu es un expert en développement logiciel. Une commande a échoué dans un terminal.\n${recidive}\n## Commande échouée\n\`${ctx.command}\` (exit code: ${ctx.exit_code})\nRépertoire: ${ctx.cwd || '(inconnu)'}\n\n## Sortie d'erreur\n\`\`\`\n${ctx.errorText.slice(0, 4000)}${ctx.errorText.length > 4000 ? '\n... (tronqué)' : ''}\n\`\`\`\n\n## Fichiers à risque dans le projet (pour contexte)\n${filesSection}\n\nRéponds en français. Structure ta réponse ainsi :\n1. **Cause** (2-3 phrases) : explique la cause racine de cette erreur de manière claire et directe.\n2. **Solution** : donne la commande exacte ou les étapes précises pour résoudre le problème.\n3. **Prévention** (optionnel) : si c'est une erreur récurrente ou évitable, suggère comment l'éviter.\n\nSois concis et pratique. Priorise la solution immédiate.`;
}

export function buildExplainPrompt(ctx: TerminalErrorContext): string {
    const commandLine = ctx.command && ctx.command !== '(commande inconnue)'
        ? `\nCommande associée : \`${ctx.command}\`` : '';

    return `Tu es un assistant expert en développement logiciel. Le développeur a copié une sortie de terminal et veut comprendre ce qu'elle signifie.\n${commandLine}\n\n## Sortie copiée\n\`\`\`\n${ctx.errorText.slice(0, 3000)}${ctx.errorText.length > 3000 ? '\n... (tronqué)' : ''}\n\`\`\`\n\nExplique en français, de manière claire et directe :\n- Ce que cette sortie signifie (commande, outil, contexte)\n- Ce que chaque partie importante veut dire\n- Si des actions sont attendues ou si c'est purement informatif\n\nSois concis. Pas de section forcée. Réponds comme si tu expliquais à un collègue développeur.`;
}

export function buildMemoryExtractionPrompt(context: string): string {
    return `Tu es le système de mémoire de Pulse, un outil d'analyse de code.\nTon rôle : extraire UNIQUEMENT ce que Pulse ne peut pas déduire lui-même des métriques.\n\nPulse connaît DÉJÀ : complexité cyclomatique, complexité cognitive, taille des fonctions, churn, profondeur, couplage fan-in/fan-out.\nTu NE DOIS PAS stocker ce que Pulse sait déjà.\n\nEXEMPLES REFUSÉS (trop évidents) :\n✗ "Complexité cognitive élevée dans App.tsx"\n✗ "Churn élevé dans scanner.ts"\n✗ "Fonction trop grande, à refactoriser"\n\nEXEMPLES ACCEPTÉS (causes cachées, architecture, couplage) :\n✓ "App.tsx orchestre 12 composants via prop drilling — pas de context"\n✓ "scanner.ts bloque sur Git si le repo n'est pas initialisé — pas de guard"\n✓ "llm.ts mélange streaming et extraction sync — deux responsabilités incompatibles"\n\nRÈGLES :\n- 0 à 2 faits. Si rien de caché ou structurel : noop=true.\n- INTERDIT : type "fix" dans ce contexte (réservé aux erreurs terminal).\n- Types autorisés : "insight", "pattern", "warning".\n- Chaque fait : max 120 caractères, concret, nommé.\n- Tags : 2-4 mots-clés courts.\n\nRéponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après :\n{\n  "noop": false,\n  "facts": [\n    { "type": "insight", "content": "...", "tags": ["...", "..."] }\n  ]\n}\n\nContexte à analyser :\n${context.slice(0, 2000)}`;
}
