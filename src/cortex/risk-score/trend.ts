// ── TREND ANALYSIS — régression linéaire sur l'historique de scores ──

export type TrendSignal = 'degrading' | 'improving' | 'stable' | 'insufficient_data';

/**
 * Régression linéaire simple (moindres carrés) sur les points (i, score[i]).
 * Retourne la pente : > 0.5 = dégradation notable, < -0.5 = amélioration.
 * Retourne 0 si moins de 3 points.
 */
export function computeDegradationSlope(scores: number[]): number {
    if (scores.length < 3) return 0;

    const n  = scores.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;

    for (let i = 0; i < n; i++) {
        sumX  += i;
        sumY  += scores[i];
        sumXY += i * scores[i];
        sumX2 += i * i;
    }

    const denom = n * sumX2 - sumX * sumX;
    if (denom === 0) return 0;

    return (n * sumXY - sumX * sumY) / denom;
}

export function getTrendSignal(slope: number): TrendSignal {
    if (slope === 0) return 'insufficient_data';
    if (slope >  0.5) return 'degrading';
    if (slope < -0.5) return 'improving';
    return 'stable';
}
