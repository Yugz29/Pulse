import fs from 'node:fs';
import type { FunctionMetrics } from '../analyzer/parser.js';
import type { TerminalErrorContext } from '../terminal/clipboardWatcher.js';
import { loadSettings } from '../settings.js';

// Modèle de fallback ultime si rien n'est configuré
const FALLBACK_MODEL = 'pulse-qwen3';

type ModelRole = 'analyzer' | 'coder' | 'brainstorm' | 'fast' | 'default';

/**
 * Résoud le modèle pour un rôle donné.
 * Stratégie : rôle spécifique → modèle général (modelGeneral) → legacy (model) → fallback dur
 */
function getOllamaConfig(role: ModelRole = 'default') {
    const s = loadSettings();
    // Modèle général configuré dans settings (nouveau champ)
    const general = s.modelGeneral || s.model || FALLBACK_MODEL;

    const modelForRole: Record<ModelRole, string> = {
        analyzer:   s.modelAnalyzer   || general,
        coder:      s.modelCoder      || general,
        brainstorm: s.modelBrainstorm || general,
        fast:       s.modelFast       || general,
        default:    general,
    };
    return {
        model:       modelForRole[role],
        chatUrl: `${s.baseUrl || 'http://localhost:11434'}/api/chat`,
    };
}

// Options de génération par profil
const OLLAMA_OPTIONS         = { num_ctx: 4096, repeat_penalty: 1.1, num_predict: 900 } as const;  // analyse fichier
const OLLAMA_OPTIONS_COMPACT = { num_ctx: 2048, repeat_penalty: 1.15, num_predict: 512 } as const;  // fast
const OLLAMA_OPTIONS_INTEL   = { num_ctx: 4096, repeat_penalty: 1.1,  num_predict: 1400, think: false } as const;  // intel

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
    // Valeurs brutes (non normalisées) pour un contexte LLM plus précis
    rawValues?: {
        complexity:          number;  // max cyclomatic complexity
        cognitiveComplexity: number;  // max cognitive complexity (P2)
        functionSize:        number;  // max function lines
        depth:               number;  // max nesting depth
        params:              number;  // max parameter count
        churn:               number;  // commits last 30 days
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
    const trend = delta > 5 ? 'en dégradation' : delta < -5 ? 'en amélioration' : 'stable';
    return `${trend} (${first.toFixed(1)} → ${last.toFixed(1)} sur ${history.length} scans)`;
}

/**
 * Construit un "plan d'architecte" du fichier — représentation structurelle complète
 * que le LLM peut comprendre sans lire le code brut.
 *
 * Stratégie inspirée des LLMs avec outils : au lieu d'envoyer des fragments de code,
 * on envoie une carte du fichier + le corps des fonctions les plus critiques.
 */
function buildFileBlueprint(
    source: string,
    functions: FunctionMetrics[],
): string {
    const lines = source.split('\n');
    const totalLines = lines.length;
    const named = functions.filter(fn => fn.name !== 'anonymous' && fn.lineCount > 0);

    // ── 1. CARTE STRUCTURELLE ── toutes les fonctions, groupées par signal de risque
    const critical  = named.filter(fn => fn.cyclomaticComplexity >= 10 || fn.lineCount >= 60);
    const stressed  = named.filter(fn => !critical.includes(fn) && (fn.cyclomaticComplexity >= 6 || fn.lineCount >= 30 || fn.maxDepth >= 3));
    const healthy   = named.filter(fn => !critical.includes(fn) && !stressed.includes(fn));

    const formatFn = (fn: FunctionMetrics) =>
        `  ${fn.name}() — ${fn.lineCount}L, cx=${fn.cyclomaticComplexity}, depth=${fn.maxDepth}, ${fn.parameterCount}p`;

    const structureLines: string[] = [];
    structureLines.push(`Fichier : ${totalLines} lignes, ${named.length} fonctions nommées`);
    if (critical.length)  structureLines.push(`⚠️  Critique (${critical.length}) :\n${critical.map(formatFn).join('\n')}`);
    if (stressed.length)  structureLines.push(`⚡  Surveiller (${stressed.length}) :\n${stressed.map(formatFn).join('\n')}`);
    if (healthy.length)   structureLines.push(`✅  Sain (${healthy.length}) : ${healthy.map(f => f.name).join(', ')}`);

    const blueprint = structureLines.join('\n\n');

    // ── 2. CODE DES FONCTIONS CRITIQUES ── corps complet (tronqué si nécessaire)
    // Pour petits fichiers : toutes les fonctions stressed + critical
    // Pour gros fichiers : uniquement les 2 plus complexes, 30 lignes max chacune
    const isLarge = totalLines > 400;
    const toShow  = isLarge
        ? critical.sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity).slice(0, 2)
        : [...critical, ...stressed].sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity).slice(0, 4);

    const maxBodyLines = isLarge ? 30 : 50;
    const codeSections: string[] = [];

    for (const fn of toShow) {
        const startIdx = fn.startLine - 1;
        const bodyLines = lines.slice(startIdx, startIdx + fn.lineCount);
        const truncated = bodyLines.length > maxBodyLines;
        const body = bodyLines.slice(0, maxBodyLines).join('\n') + (truncated ? `\n  // ... (+${fn.lineCount - maxBodyLines} lignes tronquées)` : '');
        codeSections.push(`### ${fn.name}()  [cx=${fn.cyclomaticComplexity}, ${fn.lineCount}L, depth=${fn.maxDepth}]\n\`\`\`\n${body}\n\`\`\``);
    }

    // ── 3. IMPORTS (petits fichiers uniquement) ──
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

    const result = [
        `### Structure du fichier\n${blueprint}`,
        importsSection,
        ...codeSections,
    ].filter(Boolean).join('\n\n');

    // Budget final : 3000 chars max (on a plus de contexte num_ctx maintenant)
    return result.length > 3000 ? result.slice(0, 3000) + '\n// ... (tronqué)' : result;
}

/**
 * Traduit une valeur brute en signal lisible pour le LLM.
 * On évite les scores normalisés (0-100) qui biaisent vers le commentaire de chiffres.
 */
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

/**
 * Construit les messages chat pour l'analyse initiale d'un fichier.
 * Stratégie : valeurs brutes + signaux > scores normalisés.
 * Le LLM doit raisonner sur le CODE, pas commenter des chiffres.
 */
function buildAnalysisMessages(ctx: LLMContext, source: string, memorySnapshot?: string): ChatMessage[] {
    const codeContext = buildFileBlueprint(source, ctx.functions);
    const fileName = getFileName(ctx.filePath);

    // Fonctions notables : celles qui dépassent au moins un seuil
    const notableFunctions = ctx.functions
        .filter(fn => fn.name !== 'anonymous')
        .filter(fn => fn.cyclomaticComplexity >= 6 || fn.lineCount >= 40 || fn.maxDepth >= 3)
        .sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity)
        .slice(0, 5);

    const fnSummary = notableFunctions.length > 0
        ? notableFunctions.map(fn =>
            `  - ${fn.name}() — ${signalLines(fn.lineCount)}, cx=${signalComplexity(fn.cyclomaticComplexity)}, depth=${signalDepth(fn.maxDepth)}, ${fn.parameterCount} param(s)`
          ).join('\n')
        : '  (aucune fonction ne dépasse les seuils)';

    // Impact couplage
    const couplingSection = ctx.importedBy.length > 0
        ? `Ce fichier est importé par ${ctx.importedBy.length} autre(s) module(s) : ${ctx.importedBy.map(getFileName).join(', ')}. Une régression ici se propage directement.`
        : 'Non importé par d\'autres fichiers (module isolé ou point d\'entrée).';

    // Signal churn — valeurs brutes si disponibles, sinon estimation
    const rawChurn = ctx.rawValues?.churn ?? Math.round((ctx.details.churnScore / 100) * 20);
    const churnSignal = signalChurn(rawChurn);

    // Signal cognitif
    const rawCog = ctx.rawValues?.cognitiveComplexity ?? 0;
    const cogSignal = rawCog >= 25 ? `${rawCog} ⚠️ très élevé` : rawCog >= 12 ? `${rawCog} ⚠️ élevé` : rawCog >= 6 ? `${rawCog} modéré` : rawCog > 0 ? `${rawCog} ok` : null;

    // Feedback history : si le dev a déjà ignoré ce fichier, le LLM doit le savoir
    const lastFeedback = ctx.feedbackHistory[ctx.feedbackHistory.length - 1];
    const feedbackNote = lastFeedback?.action === 'ignore'
        ? '\nNote : le développeur a précédemment ignoré une alerte sur ce fichier. Sois précis et factuel, évite l\'alarmisme.'
        : lastFeedback?.action === 'apply'
        ? '\nNote : le développeur a déjà appliqué des corrections sur ce fichier. Concentre-toi sur ce qui reste.'
        : '';

    // Tendance
    const trendLine = buildScoreTrend(ctx.scoreHistory);

    // Liste exhaustive des fonctions réelles — ancre anti-hallucination
    const allFunctionNames = ctx.functions
        .filter(fn => fn.name !== 'anonymous')
        .map(fn => fn.name)
        .join(', ');

    const system: ChatMessage = {
        role: 'system',
        content:
            'Tu es Pulse, un assistant expert en qualité de code intégré dans l\'éditeur du développeur. ' +
            'Tu donnes des diagnostics courts, précis et actionnables. ' +
            'RÈGLE ABSOLUE : tu ne cites QUE des noms visibles dans le contexte fourni (fonctions, composants, variables). ' +
            'Tu n\'inventes jamais de noms absents du contexte. Si le fichier est tronqué, tu travailles avec ce qui est visible. ' +
            'Tu traduis les métriques en problèmes concrets sans répéter les chiffres bruts. ' +
            'Tu réponds en français, de manière directe.'
            + feedbackNote,
    };

    const user: ChatMessage = {
        role: 'user',
        content: `Diagnostique ce fichier.

## ${fileName}

${codeContext}

## Toutes les fonctions détectées (${ctx.functions.filter(f => f.name !== 'anonymous').length} au total)
${allFunctionNames || '(aucune)'}

## Fonctions les plus à risque
${fnSummary}

## Signaux de santé
- Churn : ${churnSignal}
- Complexité cognitive : ${cogSignal ?? '(non disponible — relancer un scan)'}
- Couplage : ${couplingSection}
- Évolution : ${trendLine}

IMPORTANT : cite uniquement des fonctions de la liste ci-dessus.
Réponds en 2 blocs :
**Diagnostic** : ce qui pose vraiment problème dans CE code (2-3 phrases, noms réels uniquement).
**Priorité** : 1 ou 2 actions concrètes, ordonnées par impact.`
        + (memorySnapshot ? `

${memorySnapshot}` : ''),
    };

    return [system, user];
}

// ── Re-export type pour usage dans index.ts sans import circulaire ──
export type { TerminalErrorContext };

// ── PROJECT INTEL ──

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
    topScans:       IntelScan[];          // top 10 par score
    topFanIn:       { filePath: string; fanIn: number }[];
    degrading:      { filePath: string; globalScore: number }[]; // fichiers en dégradation récente (↑)
    projectHistory: { date: string; score: number }[];
    selectedFile?:  { filePath: string; globalScore: number } | null;
}

export interface IntelMessage {
    role:    'user' | 'assistant';
    content: string;
}

function buildProjectSystemPrompt(ctx: ProjectContext): string {
    const name = ctx.projectPath.split('/').pop() ?? ctx.projectPath;

    // Tendance projet (compact)
    const trendStr = ctx.projectHistory.length >= 2
        ? (() => {
            const scores = ctx.projectHistory.map(h => h.score);
            const delta  = scores[scores.length - 1]! - scores[0]!;
            const dir    = delta > 1 ? 'degrading' : delta < -1 ? 'improving' : 'stable';
            return `${scores[0]!.toFixed(0)}->${scores[scores.length - 1]!.toFixed(0)} (${dir})`;
        })()
        : 'insufficient data';

    // Top 5 fichiers seulement (au lieu de 8) pour réduire les tokens
    const topFiles = ctx.topScans.slice(0, 5).map((s, i) =>
        `${i + 1}. ${s.filePath.split('/').pop()} score=${s.globalScore.toFixed(0)} cx=${s.complexityScore.toFixed(0)} fan-in=${s.fanIn} ${s.trend}`
    ).join('\n');

    // Top 3 hubs seulement
    const fanInHubs = ctx.topFanIn.slice(0, 3)
        .map(s => `${s.filePath.split('/').pop()} (${s.fanIn} deps)`)
        .join(', ');

    // Fichiers en dégradation récente
    const degradingLine = ctx.degrading.length > 0
        ? `\nDegrading recently: ${ctx.degrading.map(f => `${f.filePath.split('/').pop()} (score=${f.globalScore.toFixed(0)} ↑)`).join(', ')}`
        : '';

    const selectedLine = ctx.selectedFile
        ? `\nSelected: ${ctx.selectedFile.filePath.split('/').pop()} (score ${ctx.selectedFile.globalScore.toFixed(0)})`
        : '';

    return `You are PULSE INTEL, a code quality expert. Answer in French, concisely and actionably.

Project: ${name} | ${ctx.allScansCount} files | ${ctx.edgesCount} edges
Health: ${ctx.distribution.stable} stable, ${ctx.distribution.stressed} stressed, ${ctx.distribution.critical} critical
Trend: ${trendStr}${degradingLine}${selectedLine}

Riskiest files:
${topFiles || 'none'}

Dependency hubs: ${fanInHubs || 'none'}

Rules: Be direct. Name specific files. Prioritize degrading files when relevant. Give actionable advice. No generic comments.`;
}

export async function askLLMProject(
    ctx: ProjectContext,
    messages: IntelMessage[],
    onChunk: (text: string) => void,
    onDone:  () => void,
    onError: (err: string) => void,
): Promise<void> {
    const systemContent = buildProjectSystemPrompt(ctx);

    // Format chat : [system, ...conversation history]
    const chatMessages: ChatMessage[] = [
        { role: 'system', content: systemContent },
        ...messages.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })),
    ];

    await streamOllamaChat(chatMessages, onChunk, onDone, onError, 'analyzer', OLLAMA_OPTIONS_INTEL);
}

export interface ChatMessage {
    role: 'system' | 'user' | 'assistant';
    content: string;
}

// ── STREAMING HELPER (partagé entre askLLM et askLLMForError) ──

let _currentAbort: AbortController | null = null;

export function abortCurrentLLM(): void {
    _currentAbort?.abort();
}

// ── CHAT (multi-turn via /api/chat) ──

async function streamOllamaChat(
    messages: ChatMessage[],
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
    role: ModelRole = 'default',
    options: Record<string, unknown> = OLLAMA_OPTIONS,
): Promise<void> {
    _currentAbort?.abort();
    const abort = new AbortController();
    _currentAbort = abort;

    try {
        const cfg = getOllamaConfig(role);
        const res = await fetch(cfg.chatUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: cfg.model, messages, stream: true, options }),
            signal: abort.signal,
        });

        if (!res.ok || !res.body) {
            onError(`Erreur Ollama : ${res.status} ${res.statusText}`);
            return;
        }

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const lines = decoder.decode(value).split('\n').filter(Boolean);
            for (const line of lines) {
                try {
                    const json = JSON.parse(line) as { message?: { content?: string }; done?: boolean };
                    if (json.message?.content) onChunk(json.message.content);
                    if (json.done) { onDone(); return; }
                } catch { /* ligne incomplète */ }
            }
        }
        onDone();
    } catch (err) {
        if (abort.signal.aborted) return;
        onError(`Ollama inaccessible : ${err instanceof Error ? err.message : String(err)}`);
    }
}

export async function continueLLM(
    messages: ChatMessage[],
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
): Promise<void> {
    const system: ChatMessage = {
        role: 'system',
        content:
            'Tu es un expert senior en qualité de code. ' +
            'Réponds en français, de manière directe et pratique. ' +
            'Appuie-toi sur le code et l\'analyse déjà fournie pour répondre aux questions.',
    };

    // Le format chat exige que la conversation commence par un tour "user" après "system".
    // Quand chatMessages débute par l'analyse initiale (role: assistant), on insère un
    // message user synthétique pour que le modèle ne se retrouve pas avec [system, assistant, user],
    // ce qui le désorienterait et produirait une réponse vide ou tronquée.
    let chat = [...messages];
    if (chat[0]?.role === 'assistant') {
        chat = [
            { role: 'user', content: 'Analyse ce fichier et donne tes observations.' },
            ...chat,
        ];
    }

    await streamOllamaChat([system, ...chat], onChunk, onDone, onError, 'analyzer');
}

// ── TERMINAL / CLIPBOARD ANALYSIS ──

/**
 * Mode 'hint' — pas d'erreur, juste une explication.
 * Pas de structure Cause/Solution, ton conversationnel.
 */
function buildExplainPrompt(ctx: TerminalErrorContext): string {
    const commandLine = ctx.command && ctx.command !== '(commande inconnue)'
        ? `\nCommande associée : \`${ctx.command}\`` : '';

    return `Tu es un assistant expert en développement logiciel. Le développeur a copié une sortie de terminal et veut comprendre ce qu'elle signifie.
${commandLine}

## Sortie copiée
\`\`\`
${ctx.errorText.slice(0, 3000)}${ctx.errorText.length > 3000 ? '\n... (tronqué)' : ''}
\`\`\`

Explique en français, de manière claire et directe :
- Ce que cette sortie signifie (commande, outil, contexte)
- Ce que chaque partie importante veut dire
- Si des actions sont attendues ou si c'est purement informatif

Sois concis. Pas de section forcée. Réponds comme si tu expliquais à un collègue développeur.`;
}

function buildErrorPrompt(
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

    return `Tu es un expert en développement logiciel. Une commande a échoué dans un terminal.
${recidive}
## Commande échouée
\`${ctx.command}\` (exit code: ${ctx.exit_code})
Répertoire: ${ctx.cwd || '(inconnu)'}

## Sortie d'erreur
\`\`\`
${ctx.errorText.slice(0, 4000)}${ctx.errorText.length > 4000 ? '\n... (tronqué)' : ''}
\`\`\`

## Fichiers à risque dans le projet (pour contexte)
${filesSection}

Réponds en français. Structure ta réponse ainsi :
1. **Cause** (2-3 phrases) : explique la cause racine de cette erreur de manière claire et directe.
2. **Solution** : donne la commande exacte ou les étapes précises pour résoudre le problème.
3. **Prévention** (optionnel) : si c'est une erreur récurrente ou évitable, suggère comment l'éviter.

Sois concis et pratique. Priorise la solution immédiate.`;
}

export async function askLLMForError(
    ctx: TerminalErrorContext,
    topFiles: { filePath: string; globalScore: number }[],
    pastOccurrences: number,
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
): Promise<void> {
    const prompt = ctx.mode === 'hint'
        ? buildExplainPrompt(ctx)
        : buildErrorPrompt(ctx, topFiles, pastOccurrences);
    const messages: ChatMessage[] = [{ role: 'user', content: prompt }];
    await streamOllamaChat(messages, onChunk, onDone, onError, 'fast', OLLAMA_OPTIONS_COMPACT);
}

// ── MEMORY EXTRACTION ──

export interface MemoryExtractionInput {
    context: string;   // analyse complète ou erreur résolue
    subject: string;   // filePath ou commande
}

const OLLAMA_OPTIONS_EXTRACT = { num_ctx: 2048, repeat_penalty: 1.1, num_predict: 400, temperature: 0.1, think: false } as const;

/**
 * Appel silencieux post-analyse : le LLM décide ce qui vaut la peine d'être mémorisé.
 * Répond en JSON strict — pas de streaming, réponse complète attendue.
 */
export async function extractMemoryFacts(input: MemoryExtractionInput): Promise<import('../memory/memoryEngine.js').MemoryExtraction> {
    const NOOP: import('../memory/memoryEngine.js').MemoryExtraction = { facts: [], noop: true };

    const prompt = `Tu es un système de mémoire pour un outil d'analyse de code.
Tu lis une analyse et tu extrais uniquement les faits DURABLES et NON-ÉVIDENTS.

RÈGLES STRICTES :
- 0 à 2 faits maximum. Si rien ne vaut la peine d'être retenu : noop=true.
- Un fait doit être spécifique, actionnable, non-déductible des métriques seules.
- Pas de reformulation de chiffres (ex: "cx=92" → inutile).
- Types autorisés : "insight" (fait structurel sur le code), "pattern" (comportement dev), "fix" (solution à un problème), "warning" (risque confirmé).
- Chaque fait : max 120 caractères.
- Tags : 2-4 mots-clés courts.

Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après :
{
  "noop": false,
  "facts": [
    { "type": "insight", "content": "...", "tags": ["...", "..."] }
  ]
}

Contexte à analyser :
${input.context.slice(0, 2000)}`;

    try {
        const cfg = getOllamaConfig('fast');
        const res = await fetch(cfg.chatUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model:    cfg.model,
                messages: [{ role: 'user', content: prompt }],
                stream:   false,
                options:  OLLAMA_OPTIONS_EXTRACT,
            }),
        });

        if (!res.ok) return NOOP;

        const data = await res.json() as { message?: { content?: string } };
        let raw = (data.message?.content ?? '').trim();

        // Strip les balises <think>...</think> de qwen3
        raw = raw.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();

        console.log('[Pulse Memory] Extract raw response:', raw.slice(0, 200));

        // Extrait le JSON même si le modèle a ajouté du texte autour
        const jsonMatch = raw.match(/\{[\s\S]*\}/);
        if (!jsonMatch) {
            console.warn('[Pulse Memory] No JSON found in extraction response');
            return NOOP;
        }

        const parsed = JSON.parse(jsonMatch[0]) as import('../memory/memoryEngine.js').MemoryExtraction;
        console.log('[Pulse Memory] Extracted facts:', parsed.noop ? 'noop' : parsed.facts?.length ?? 0);
        return parsed.noop ? NOOP : parsed;
    } catch {
        return NOOP;
    }
}

// ── CODE QUALITY ANALYSIS ──

export async function askLLM(
    ctx: LLMContext,
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
    memorySnapshot?: string,
): Promise<void> {
    let source: string;
    try {
        source = fs.readFileSync(ctx.filePath, 'utf-8');
    } catch {
        onError(`Impossible de lire le fichier : ${ctx.filePath}`);
        return;
    }

    const messages = buildAnalysisMessages(ctx, source, memorySnapshot);
    await streamOllamaChat(messages, onChunk, onDone, onError, 'analyzer');
}
