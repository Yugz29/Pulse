import { describe, it, expect } from 'vitest';

// ── Logique de comptage de paires (extraite pour test unitaire) ──
// On teste la logique centrale du buildCouplingMap : comptage des paires co-changées
// à partir de groupes de fichiers par commit.

function countPairs(
    commitGroups: string[][],
    minCoChanges = 3,
): Map<string, number> {
    const pairCounts = new Map<string, number>();

    for (const filesInCommit of commitGroups) {
        if (filesInCommit.length < 2) continue;
        for (let i = 0; i < filesInCommit.length; i++) {
            for (let j = i + 1; j < filesInCommit.length; j++) {
                const a   = filesInCommit[i]!;
                const b   = filesInCommit[j]!;
                const key = a < b ? `${a}|${b}` : `${b}|${a}`;
                pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
            }
        }
    }

    // Filtrer par seuil
    for (const [key, count] of pairCounts) {
        if (count < minCoChanges) pairCounts.delete(key);
    }

    return pairCounts;
}

describe('logique de comptage de paires (change coupling F4)', () => {

    it('aucun commit → map vide', () => {
        expect(countPairs([])).toHaveLength(0);
    });

    it('commits avec un seul fichier → pas de paires', () => {
        const pairs = countPairs([['a.ts'], ['b.ts'], ['c.ts']]);
        expect(pairs.size).toBe(0);
    });

    it('deux fichiers dans 3 commits → une paire avec coChangeCount = 3', () => {
        const groups = [['a.ts', 'b.ts'], ['a.ts', 'b.ts'], ['a.ts', 'b.ts']];
        const pairs  = countPairs(groups, 3);
        expect(pairs.size).toBe(1);
        expect(pairs.get('a.ts|b.ts')).toBe(3);
    });

    it('filtre les paires sous le seuil minCoChanges', () => {
        const groups = [['a.ts', 'b.ts'], ['a.ts', 'b.ts']];  // 2 co-changements
        const pairs  = countPairs(groups, 3);
        expect(pairs.size).toBe(0);
    });

    it('paires canoniques (ordre alphabétique) — pas de duplicata', () => {
        const groups = [
            ['b.ts', 'a.ts'],  // ordre inversé
            ['a.ts', 'b.ts'],  // ordre normal
            ['b.ts', 'a.ts'],
        ];
        const pairs = countPairs(groups, 3);
        // Une seule paire canonique : a.ts|b.ts
        expect(pairs.size).toBe(1);
        expect(pairs.get('a.ts|b.ts')).toBe(3);
    });

    it('3 fichiers dans un commit → 3 paires', () => {
        const groups = [['a.ts', 'b.ts', 'c.ts']];
        const pairs  = countPairs(groups, 1);
        expect(pairs.size).toBe(3);
    });

    it('compte correctement des fréquences mixtes', () => {
        const groups = [
            ['a.ts', 'b.ts'],  // +1 a-b
            ['a.ts', 'b.ts'],  // +1 a-b
            ['a.ts', 'b.ts'],  // +1 a-b → total 3
            ['a.ts', 'c.ts'],  // +1 a-c
            ['a.ts', 'c.ts'],  // +1 a-c → total 2 (sous seuil 3)
        ];
        const pairs = countPairs(groups, 3);
        expect(pairs.size).toBe(1);
        expect(pairs.get('a.ts|b.ts')).toBe(3);
        expect(pairs.has('a.ts|c.ts')).toBe(false);
    });

    it('commit avec 1 fichier ne crée pas de paires parasites', () => {
        const groups = [['a.ts', 'b.ts'], ['a.ts'], ['a.ts', 'b.ts'], ['a.ts', 'b.ts']];
        const pairs  = countPairs(groups, 3);
        expect(pairs.size).toBe(1);
        expect(pairs.get('a.ts|b.ts')).toBe(3);
    });
});

// ── Tests supplémentaires : saveCouplings (déduplication) ──

describe('saveCouplings — déduplication des paires canoniques', () => {

    it("une paire (A,B) et sa symetrique (B,A) ne produisent qu'un seul enregistrement", () => {
        // On simule la logique de déduplication de saveCouplings
        const inserted = new Set<string>();
        const rows: string[] = [];

        function insert(fileA: string, fileB: string) {
            const key = fileA < fileB ? `${fileA}\0${fileB}` : `${fileB}\0${fileA}`;
            if (inserted.has(key)) return;
            inserted.add(key);
            rows.push(key);
        }

        insert('/a.ts', '/b.ts');
        insert('/b.ts', '/a.ts');  // symétrique
        insert('/a.ts', '/b.ts');  // doublon

        expect(rows.length).toBe(1);
    });

    it('deux paires distinctes → deux enregistrements', () => {
        const inserted = new Set<string>();
        const rows: string[] = [];

        function insert(fileA: string, fileB: string) {
            const key = fileA < fileB ? `${fileA}\0${fileB}` : `${fileB}\0${fileA}`;
            if (inserted.has(key)) return;
            inserted.add(key);
            rows.push(key);
        }

        insert('/a.ts', '/b.ts');
        insert('/a.ts', '/c.ts');

        expect(rows.length).toBe(2);
    });
});
