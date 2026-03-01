import type { FileMetrics } from '../analyzer/parser.js';
import { getChurnScore } from '../analyzer/churn.js';

export interface RiskScoreResult {
    filePath: string;
    language: string;
    globalScore: number;
    details: {
        complexityScore: number;
        functionSizeScore: number;
        churnScore: number;
        depthScore: number;
        paramScore: number;
        fanIn: number;
        fanOut: number;
    };
}

export function clampedScore(value: number, safe: number, danger: number): number {
    if (value <= safe)    return 0;
    if (value >= danger)  return 100;
    return ((value - safe) / (danger - safe)) * 100;
}

export async function calculateRiskScore(metrics: FileMetrics): Promise<RiskScoreResult> {
    // Exclure toutes les fonctions anonymes — double comptage avec leur parente
    const fns = metrics.functions.filter(fn => fn.name !== 'anonymous');

    const maxComplexity = fns.length > 0
        ? Math.max(...fns.map(fn => fn.cyclomaticComplexity))
        : 0;

    const maxFunctionSize = fns.length > 0
        ? Math.max(...fns.map(fn => fn.lineCount))
        : 0;

    const maxDepth = fns.length > 0
        ? Math.max(...fns.map(fn => fn.maxDepth))
        : 0;

    const maxParams = fns.length > 0
        ? Math.max(...fns.map(fn => fn.parameterCount))
        : 0;

    const complexityScore   = clampedScore(maxComplexity,   3,  10);
    const functionSizeScore = clampedScore(maxFunctionSize, 20, 60);
    const depthScore        = clampedScore(maxDepth,        2,  5);
    const paramScore        = clampedScore(maxParams,       3,  7);

    const churn      = await getChurnScore(metrics.filePath);
    const churnScore = clampedScore(churn, 5, 20);

    const globalScore =
        (complexityScore   * 0.35) +
        (functionSizeScore * 0.20) +
        (churnScore        * 0.15) +
        (depthScore        * 0.20) +
        (paramScore        * 0.10);

    return {
        filePath:  metrics.filePath,
        language:  metrics.language,
        globalScore,
        details: { complexityScore, functionSizeScore, churnScore, depthScore, paramScore, fanIn: 0, fanOut: 0 },
    };
}
