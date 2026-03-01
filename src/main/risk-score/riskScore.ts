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
    };
}

export function clampedScore(value: number, safe: number, danger: number): number {
    if (value <= safe)    return 0;
    if (value >= danger)  return 100;
    return ((value - safe) / (danger - safe)) * 100;
}

export async function calculateRiskScore(metrics: FileMetrics): Promise<RiskScoreResult> {
    const maxComplexity = metrics.functions.length > 0
        ? Math.max(...metrics.functions.map(fn => fn.cyclomaticComplexity))
        : 0;

    const maxFunctionSize = metrics.functions.length > 0
        ? Math.max(...metrics.functions.map(fn => fn.lineCount))
        : 0;

    const complexityScore    = clampedScore(maxComplexity,    3,  10);
    const functionSizeScore  = clampedScore(maxFunctionSize, 20,  60);

    const churn      = await getChurnScore(metrics.filePath);
    const churnScore = clampedScore(churn, 5, 20);

    const globalScore = (complexityScore * 0.5) + (functionSizeScore * 0.3) + (churnScore * 0.2);

    return {
        filePath:  metrics.filePath,
        language:  metrics.language,
        globalScore,
        details: { complexityScore, functionSizeScore, churnScore },
    };
}
