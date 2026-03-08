import type { FileMetrics } from '../analyzer/parser.js';
import { getChurnScore } from '../analyzer/churn.js';
import { getReferenceBaselines } from './referenceBaselines.js';

// ── INTERFACES ──

export interface RawMetrics {
    complexity:          number;  // max cyclomatic complexity across functions
    complexityMean:      number;  // mean cyclomatic complexity (P3)
    cognitiveComplexity: number;  // max cognitive complexity (P2)
    functionSize:        number;  // max function line count
    functionSizeMean:    number;  // mean function line count (P3)
    depth:               number;  // max nesting depth
    params:              number;  // max parameter count
    churn:               number;  // git commit count over 30 days
}

export interface ProjectBaselines {
    complexity:          { p25: number; p90: number };
    complexityMean:      { p25: number; p90: number };
    cognitiveComplexity: { p25: number; p90: number };
    functionSize:        { p25: number; p90: number };
    functionSizeMean:    { p25: number; p90: number };
    depth:               { p25: number; p90: number };
    params:              { p25: number; p90: number };
    churn:               { p25: number; p90: number };
}

export interface RiskScoreResult {
    filePath:    string;
    language:    string;
    globalScore: number;
    raw:         RawMetrics;
    details: {
        complexityScore:          number;
        cognitiveComplexityScore: number;  // P2 — affiché séparément dans la sidebar
        functionSizeScore:        number;
        churnScore:               number;
        depthScore:               number;
        paramScore:               number;
        fanIn:                    number;
        fanOut:                   number;
    };
}

// ── SEUILS ABSOLUS ──

const ABS_SAFE: Record<keyof RawMetrics, number> = {
    complexity:          3,
    complexityMean:      2,
    cognitiveComplexity: 8,   // recalibré — fonctions simples atteignent 3-5 naturellement
    functionSize:        20,
    functionSizeMean:    15,
    depth:               2,
    params:              3,
    churn:               3,
};

const ABS_DANGER: Record<keyof RawMetrics, number> = {
    complexity:          15,
    complexityMean:      8,
    cognitiveComplexity: 60,  // recalibré — buildFileBlueprint à cog:52 = stressed, pas critical
    functionSize:        80,
    functionSizeMean:    40,
    depth:               6,
    params:              8,
    churn:               20,
};

// ── FONCTIONS DE SCORE ──

export function clampedScore(value: number, safe: number, danger: number): number {
    if (safe >= danger) return value > safe ? 100 : 0;
    if (value <= safe)   return 0;
    if (value >= danger) return 100;
    return ((value - safe) / (danger - safe)) * 100;
}

function adaptiveScore(
    value: number,
    metric: keyof RawMetrics,
    baselines?: ProjectBaselines,
    refBaselines?: ProjectBaselines,
): number {
    // 1. Plancher absolu
    let safe   = ABS_SAFE[metric];
    let danger = ABS_DANGER[metric];

    if (refBaselines) {
        // La référence par type de fichier REMPLACE les seuils absolus.
        // Elle élargit pour les entrypoints/parsers, resserre pour les configs/utils.
        // safe   : on prend le max — ne pas flaguer ce qui est normal pour ce type
        // danger : on prend le max aussi — laisser de la place aux fichiers légitimement denses
        safe   = Math.max(safe,   refBaselines[metric].p25);
        danger = Math.max(danger, refBaselines[metric].p90);
        if (safe >= danger) danger = safe + 1;
    }

    if (baselines) {
        // Les baselines projet ajustent uniquement le seuil SAFE (ce qui est banal ici).
        // Elles ne touchent JAMAIS au danger — évite que p90 d'un projet peu churné
        // écrase la référence et transforme 8 commits en 100.0.
        safe = Math.max(safe, baselines[metric].p25);
        // danger reste inchangé — ancré par ABS_DANGER + refBaselines uniquement
        if (safe >= danger) danger = safe + 1;
    }

    return clampedScore(value, safe, danger);
}

// ── SCORE PONDÉRÉ MAX+MEAN (P3) ──
//
// Problème du MAX seul : 1 fonction monstre + 50 fonctions saines = score élevé,
// même si le fichier est globalement bien structuré.
//
// Formule : 0.65 * score(max) + 0.35 * score(mean)
// → Le pire cas reste dominant (signal conservateur) mais la distribution compte.

function blendedScore(
    maxMetric: keyof RawMetrics,
    meanMetric: keyof RawMetrics,
    raw: RawMetrics,
    baselines?: ProjectBaselines,
    refBaselines?: ProjectBaselines,
): number {
    const maxScore  = adaptiveScore(raw[maxMetric],  maxMetric,  baselines, refBaselines);
    const meanScore = adaptiveScore(raw[meanMetric], meanMetric, baselines, refBaselines);
    return (maxScore * 0.65) + (meanScore * 0.35);
}

// ── CALCUL DES BASELINES ──

function percentile(values: number[], p: number): number {
    if (values.length === 0) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const idx    = Math.max(0, Math.ceil(sorted.length * p / 100) - 1);
    return sorted[idx] ?? 0;
}

export function computeProjectBaselines(allRaw: RawMetrics[]): ProjectBaselines {
    const metrics: (keyof RawMetrics)[] = [
        'complexity', 'complexityMean', 'cognitiveComplexity',
        'functionSize', 'functionSizeMean',
        'depth', 'params', 'churn',
    ];
    const result = {} as ProjectBaselines;

    for (const m of metrics) {
        const values = allRaw.map(r => r[m]);
        result[m] = { p25: percentile(values, 25), p90: percentile(values, 90) };
    }

    return result;
}

// ── SCORING GLOBAL ──
//
// Pondération :
//   Complexité (cyclomatique blended)  30%
//   Complexité cognitive               20%  ← nouveau (P2), remplace une partie du "complexity"
//   Taille des fonctions (blended)     15%
//   Profondeur d'imbrication           15%
//   Churn                              12%
//   Paramètres                          8%
//
// Total : 100%
// Changement vs avant : cognitive complexity prend 20%, cyclomatique descend à 30%,
// les autres métriques ajustées proportionnellement.

export function scoreFromRaw(
    raw: RawMetrics,
    filePath: string,
    language: string,
    baselines?: ProjectBaselines,
): RiskScoreResult {
    // Baselines de référence externe — ancrées par type de fichier
    const refBaselines = getReferenceBaselines(filePath);

    // Complexité cyclomatique — blended max+mean (P3)
    const complexityScore = blendedScore('complexity', 'complexityMean', raw, baselines, refBaselines);

    // Complexité cognitive — max seul suffit ici (déjà très différenciante)
    const cognitiveComplexityScore = adaptiveScore(raw.cognitiveComplexity, 'cognitiveComplexity', baselines, refBaselines);

    // Taille des fonctions — blended max+mean (P3)
    const functionSizeScore = blendedScore('functionSize', 'functionSizeMean', raw, baselines, refBaselines);

    const depthScore  = adaptiveScore(raw.depth,  'depth',  baselines, refBaselines);
    const paramScore  = adaptiveScore(raw.params, 'params', baselines, refBaselines);
    const churnScore  = adaptiveScore(raw.churn,  'churn',  baselines, refBaselines);

    const globalScore =
        (complexityScore          * 0.30) +
        (cognitiveComplexityScore * 0.20) +
        (functionSizeScore        * 0.15) +
        (depthScore               * 0.15) +
        (churnScore               * 0.12) +
        (paramScore               * 0.08);

    return {
        filePath,
        language,
        globalScore,
        raw,
        details: {
            complexityScore,
            cognitiveComplexityScore,
            functionSizeScore,
            churnScore,
            depthScore,
            paramScore,
            fanIn:  0,
            fanOut: 0,
        },
    };
}

// ── EXTRACTION DES MÉTRIQUES BRUTES ──

export async function extractRaw(metrics: FileMetrics): Promise<RawMetrics> {
    const fns = metrics.functions.filter(fn => fn.name !== 'anonymous');

    const complexity          = fns.length > 0 ? Math.max(...fns.map(fn => fn.cyclomaticComplexity)) : 0;
    const complexityMean      = fns.length > 0 ? fns.reduce((s, fn) => s + fn.cyclomaticComplexity, 0) / fns.length : 0;
    const cognitiveComplexity = fns.length > 0 ? Math.max(...fns.map(fn => fn.cognitiveComplexity ?? 0)) : 0;
    const functionSize        = fns.length > 0 ? Math.max(...fns.map(fn => fn.lineCount)) : 0;
    const functionSizeMean    = fns.length > 0 ? fns.reduce((s, fn) => s + fn.lineCount, 0) / fns.length : 0;
    const depth               = fns.length > 0 ? Math.max(...fns.map(fn => fn.maxDepth)) : 0;
    const params              = fns.length > 0 ? Math.max(...fns.map(fn => fn.parameterCount)) : 0;
    const churn               = await getChurnScore(metrics.filePath);

    return {
        complexity,
        complexityMean,
        cognitiveComplexity,
        functionSize,
        functionSizeMean,
        depth,
        params,
        churn,
    };
}

/**
 * Point d'entrée compatible avec l'ancienne API (sans baselines).
 * Conservé pour compatibilité — préférer le pipeline deux passes dans scanner.ts.
 */
export async function calculateRiskScore(metrics: FileMetrics): Promise<RiskScoreResult> {
    const raw = await extractRaw(metrics);
    return scoreFromRaw(raw, metrics.filePath, metrics.language);
}
