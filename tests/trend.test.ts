import { describe, it, expect } from 'vitest';
import { computeDegradationSlope, getTrendSignal } from '../src/main/risk-score/trend.js';

describe('computeDegradationSlope', () => {

    it('retourne 0 si moins de 3 points', () => {
        expect(computeDegradationSlope([])).toBe(0);
        expect(computeDegradationSlope([50])).toBe(0);
        expect(computeDegradationSlope([30, 50])).toBe(0);
    });

    it('détecte une tendance croissante (dégradation)', () => {
        const slope = computeDegradationSlope([10, 20, 30, 40, 50]);
        expect(slope).toBeGreaterThan(0.5);
    });

    it('détecte une tendance décroissante (amélioration)', () => {
        const slope = computeDegradationSlope([50, 40, 30, 20, 10]);
        expect(slope).toBeLessThan(-0.5);
    });

    it('retourne une pente proche de 0 sur une série stable', () => {
        const slope = computeDegradationSlope([30, 30, 30, 30, 30]);
        expect(Math.abs(slope)).toBeLessThan(0.1);
    });

    it('calcule une pente exacte sur 3 points alignés (0, 10, 20)', () => {
        // y = 10x → pente attendue = 10
        const slope = computeDegradationSlope([0, 10, 20]);
        expect(slope).toBeCloseTo(10, 1);
    });

    it('est robuste face aux valeurs identiques (évite division par zéro)', () => {
        // dénominateur = 0 si tous les x sont identiques — impossible ici, mais cas de
        // n=1 déjà couvert. Avec n ≥ 3 et valeurs identiques en y → pente 0.
        const slope = computeDegradationSlope([42, 42, 42]);
        expect(slope).toBe(0);
    });

    it('fonctionne sur un fichier sans fonctions (scores tous à 0)', () => {
        const slope = computeDegradationSlope([0, 0, 0, 0]);
        expect(slope).toBe(0);
    });

    it('gère des valeurs non monotones avec une tendance nette', () => {
        // Bruit autour d'une progression positive
        const slope = computeDegradationSlope([10, 15, 12, 20, 18, 25]);
        expect(slope).toBeGreaterThan(0);
    });
});

describe('getTrendSignal', () => {

    it('retourne insufficient_data quand slope = 0', () => {
        expect(getTrendSignal(0)).toBe('insufficient_data');
    });

    it('retourne degrading quand slope > 0.5', () => {
        expect(getTrendSignal(0.6)).toBe('degrading');
        expect(getTrendSignal(10)).toBe('degrading');
    });

    it('retourne improving quand slope < -0.5', () => {
        expect(getTrendSignal(-0.6)).toBe('improving');
        expect(getTrendSignal(-10)).toBe('improving');
    });

    it('retourne stable pour les pentes faibles (-0.5 < slope < 0.5, hors 0)', () => {
        expect(getTrendSignal(0.3)).toBe('stable');
        expect(getTrendSignal(-0.3)).toBe('stable');
        expect(getTrendSignal(0.49)).toBe('stable');
        expect(getTrendSignal(-0.49)).toBe('stable');
    });

    it('retourne degrading exactement à la limite haute (> 0.5)', () => {
        expect(getTrendSignal(0.5)).toBe('stable');  // strictement > 0.5
        expect(getTrendSignal(0.51)).toBe('degrading');
    });
});
