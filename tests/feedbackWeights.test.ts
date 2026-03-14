import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.mock est hoiste en haut du fichier — on ne peut pas referencer de variables
// declarees avant. On retourne des vi.fn() inline et on configure via vi.mocked() apres.
vi.mock('../src/main/database/db.js', () => ({
    getDb: vi.fn(),
}));

import { getDb } from '../src/main/database/db.js';
import { applyWeightAdjustments, computeWeightAdjustments } from '../src/main/risk-score/feedbackWeights.js';
import type { WeightAdjustment } from '../src/main/risk-score/feedbackWeights.js';

const DEFAULT: WeightAdjustment = {
    complexity: 1, cognitiveComplexity: 1, functionSize: 1,
    depth: 1, churn: 1, params: 1, fanIn: 1,
};

// Helper : cree un prepare() qui retourne plusieurs resultats successifs
function setupMockDb(calls: Array<{ all?: () => unknown[]; get?: () => unknown }>) {
    let callIndex = 0;
    const mockPrepare = vi.fn(() => {
        const response = calls[callIndex++] ?? { all: () => [], get: () => undefined };
        return response;
    });
    vi.mocked(getDb).mockReturnValue({ prepare: mockPrepare } as never);
    return mockPrepare;
}

// ─────────────────────────────────────────────────────────────────────────────
describe('applyWeightAdjustments', () => {

    it('multiplicateurs a 1.0 — poids inchanges', () => {
        const base = { complexity: 0.28, cognitiveComplexity: 0.19, churn: 0.12 };
        const result = applyWeightAdjustments(base, DEFAULT);
        expect(result.complexity).toBeCloseTo(0.28);
        expect(result.cognitiveComplexity).toBeCloseTo(0.19);
        expect(result.churn).toBeCloseTo(0.12);
    });

    it('multiplicateur 0.5 reduit le poids de moitie', () => {
        const base = { complexity: 0.28 };
        const result = applyWeightAdjustments(base, { ...DEFAULT, complexity: 0.5 });
        expect(result.complexity).toBeCloseTo(0.14);
    });

    it('multiplicateur 1.5 augmente le poids de 50%', () => {
        const base = { churn: 0.12 };
        const result = applyWeightAdjustments(base, { ...DEFAULT, churn: 1.5 });
        expect(result.churn).toBeCloseTo(0.18);
    });

    it('les metriques absentes du base ne sont pas creees', () => {
        const base = { complexity: 0.28 };
        const result = applyWeightAdjustments(base, DEFAULT);
        expect(Object.keys(result)).toEqual(['complexity']);
    });

    it('une metrique sans correspondance dans adjustments recoit le multiplicateur 1', () => {
        const base = { unknownMetric: 0.5 };
        const result = applyWeightAdjustments(base, DEFAULT);
        expect(result.unknownMetric).toBeCloseTo(0.5);
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('computeWeightAdjustments', () => {

    beforeEach(() => {
        vi.mocked(getDb).mockReset();
    });

    it('retourne les poids par defaut si aucun feedback', () => {
        setupMockDb([
            { all: () => [] },          // SELECT feedbacks
            { get: () => undefined },   // SELECT weight_state
        ]);
        const adj = computeWeightAdjustments('/project');
        expect(adj).toEqual(DEFAULT);
    });

    it("reduit le poids complexity si c'est la metrique dominante du feedback", () => {
        setupMockDb([
            { all: () => [{ file_path: '/file.ts', action: 'ignore' }] },
            { get: () => undefined },
            { get: () => ({
                complexity_score:           80,
                cognitive_complexity_score: 20,
                function_size_score:        10,
                depth_score:                 5,
                churn_score:                15,
                param_score:                 3,
                fan_in:                      2,
            }) },
        ]);
        const adj = computeWeightAdjustments('/project');
        expect(adj.complexity).toBeCloseTo(1 - 0.02);
        expect(adj.cognitiveComplexity).toBe(1);
        expect(adj.churn).toBe(1);
    });

    it("borne a 0.5 — ne descend pas en-dessous de 0.5", () => {
        setupMockDb([
            { all: () => [{ file_path: '/f.ts', action: 'ignore' }] },
            { get: () => ({ weights: JSON.stringify({ ...DEFAULT, complexity: 0.51 }) }) },
            { get: () => ({
                complexity_score:           90,
                cognitive_complexity_score: 10,
                function_size_score:         5,
                depth_score:                 2,
                churn_score:                 5,
                param_score:                 1,
                fan_in:                      0,
            }) },
        ]);
        const adj = computeWeightAdjustments('/project');
        expect(adj.complexity).toBeGreaterThanOrEqual(0.5);
    });

    it('ignore un feedback sur un fichier sans scan associe', () => {
        setupMockDb([
            { all: () => [{ file_path: '/ghost.ts', action: 'ignore' }] },
            { get: () => undefined },
            { get: () => undefined },   // aucun scan pour /ghost.ts
        ]);
        const adj = computeWeightAdjustments('/project');
        expect(adj).toEqual(DEFAULT);
    });

    it('retourne les poids par defaut quand aucun feedback', () => {
        // weight_state n'est pas consulte dans ce chemin — on ne passe qu'un seul appel (feedbacks)
        setupMockDb([
            { all: () => [] },  // SELECT feedbacks → vide, on s'arrete la
        ]);
        const adj = computeWeightAdjustments('/project');
        expect(adj).toEqual(DEFAULT);
    });

    it('utilise les poids stockes dans weight_state quand des feedbacks existent', () => {
        // Avec un feedback, le weight_state sert de base pour l'ajustement
        const stored = { ...DEFAULT, complexity: 0.9 };
        setupMockDb([
            { all: () => [{ file_path: '/f.ts', action: 'ignore' }] },
            { get: () => ({ weights: JSON.stringify(stored) }) },
            { get: () => ({
                complexity_score:           80,
                cognitive_complexity_score: 10,
                function_size_score:         5,
                depth_score:                 2,
                churn_score:                 5,
                param_score:                 1,
                fan_in:                      0,
            }) },
        ]);
        const adj = computeWeightAdjustments('/project');
        // Complexite dominante → 0.9 - 0.02 = 0.88
        expect(adj.complexity).toBeCloseTo(0.9 - 0.02);
    });
});
