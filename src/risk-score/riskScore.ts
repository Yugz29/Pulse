import type { FileMetrics } from '../analyzer/parser.js';


export interface RiskScoreResult {
    filePath: string;
    globalScore: number;
    details: {
        complexityScore: number;
        functionSizeScore: number;
    };
}

export function clampedScore(value: number, safe: number, danger: number): number {
    if (value <= safe) return 0;
    if (value >= danger) return 100;
    return ((value - safe) / (danger - safe)) * 100;
}

export function calculateRiskScore(metrics: FileMetrics): RiskScoreResult {
    const maxComplexity = metrics.functions.length > 0
        ? Math.max(...metrics.functions.map(fn => fn.cyclomaticComplexity))
        : 0;

    const maxFunctionSize = metrics.functions.length > 0
        ? Math.max(...metrics.functions.map(fn => fn.lineCount))
        : 0;

    // Convertit chaque métrique encore 0-100
    const complexityScore = clampedScore(maxComplexity, 3, 10);
    const functionSizeScore = clampedScore(maxFunctionSize, 20, 60);

    // Moyenne pondérée : complexité compte plus que la taille
    const globalScore = (complexityScore * 0.6) + (functionSizeScore * 0.4);

    return {
        filePath: metrics.filePath,
        globalScore,
        details: { complexityScore, functionSizeScore }
    };
}
