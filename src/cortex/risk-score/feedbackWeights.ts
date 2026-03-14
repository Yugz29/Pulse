import { getDb } from '../../core/database/db.js';

const LEARNING_RATE = 0.02;
const BOUND_MIN     = 0.5;
const BOUND_MAX     = 1.5;

export interface WeightAdjustment {
    complexity:          number;
    cognitiveComplexity: number;
    functionSize:        number;
    depth:               number;
    churn:               number;
    params:              number;
    fanIn:               number;
}

const DEFAULT_ADJUSTMENT: WeightAdjustment = {
    complexity: 1, cognitiveComplexity: 1, functionSize: 1,
    depth: 1, churn: 1, params: 1, fanIn: 1,
};

type MetricKey = keyof WeightAdjustment;

const SCORE_COLUMNS: Record<MetricKey, string> = {
    complexity:          'complexity_score',
    cognitiveComplexity: 'cognitive_complexity_score',
    functionSize:        'function_size_score',
    depth:               'depth_score',
    churn:               'churn_score',
    params:              'param_score',
    fanIn:               'fan_in',
};

export function computeWeightAdjustments(projectPath: string): WeightAdjustment {
    const db = getDb();
    const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString();
    const feedbacks = db.prepare(`
        SELECT f.file_path, f.action
        FROM feedbacks f
        WHERE f.action = 'ignore'
          AND f.created_at >= ?
    `).all(since) as { file_path: string; action: string }[];

    if (feedbacks.length === 0) return { ...DEFAULT_ADJUSTMENT };

    const stored = db.prepare(`
        SELECT weights FROM weight_state WHERE project_path = ?
    `).get(projectPath) as { weights: string } | undefined;

    const adjustments: WeightAdjustment = stored
        ? JSON.parse(stored.weights)
        : { ...DEFAULT_ADJUSTMENT };

    for (const { file_path } of feedbacks) {
        const scan = db.prepare(`
            SELECT complexity_score, cognitive_complexity_score, function_size_score,
                   depth_score, churn_score, param_score, fan_in
            FROM scans
            WHERE file_path = ?
            ORDER BY scanned_at DESC
            LIMIT 1
        `).get(file_path) as Record<string, number> | undefined;

        if (!scan) continue;

        let dominantMetric: MetricKey = 'complexity';
        let maxScore = -1;

        for (const [metric, col] of Object.entries(SCORE_COLUMNS) as [MetricKey, string][]) {
            const score = scan[col] ?? 0;
            if (score > maxScore) {
                maxScore       = score;
                dominantMetric = metric;
            }
        }

        const current = adjustments[dominantMetric];
        adjustments[dominantMetric] = Math.max(BOUND_MIN, Math.min(BOUND_MAX, current - LEARNING_RATE));
    }

    return adjustments;
}

export function applyWeightAdjustments(
    baseWeights: Record<string, number>,
    adjustments: WeightAdjustment,
): Record<string, number> {
    const result: Record<string, number> = {};
    for (const [key, weight] of Object.entries(baseWeights)) {
        const adj = (adjustments as unknown as Record<string, number>)[key] ?? 1;
        result[key] = weight * adj;
    }
    return result;
}
