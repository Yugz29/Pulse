// ── REFERENCE BASELINES ──────────────────────────────────────────────────────
//
// Percentiles de référence construits à partir de l'analyse de projets
// open source TypeScript/React/Python de taille moyenne (50–300 fichiers).
//
// Sources :
//   - Distributions de complexité cyclomatique (McCabe, SonarSource research)
//   - Métriques observées sur des projets GitHub populaires (React, Vite, ESLint, etc.)
//   - Ajustées empiriquement via les scans de Pulse sur lui-même
//
// Ces valeurs servent de PLANCHER pour les baselines projet :
//   - Si le projet est globalement sain (p90 faible), la référence empêche
//     de normaliser vers le bas et de rater les vrais outliers.
//   - Si le projet est globalement complexe, la référence ancre le jugement
//     à une réalité externe (évite le paradoxe "tout est normal ici").
//
// Mise à jour : les valeurs peuvent être raffinées manuellement ou via un
// script d'analyse de corpus GitHub (voir docs/reference-methodology.md).
// ─────────────────────────────────────────────────────────────────────────────

import type { ProjectBaselines } from './riskScore.js';

// Référence générale — tous projets TypeScript/JS/Python confondus
export const REFERENCE_BASELINES: ProjectBaselines = {
    // Complexité cyclomatique max par fichier
    // p25 : la plupart des fichiers ont des fonctions simples (cx ≤ 3)
    // p90 : 10% des fichiers ont une fonction avec cx > 12 — au-delà c'est notable
    complexity: { p25: 3, p90: 12 },

    // Complexité cyclomatique moyenne par fichier
    // Plus stable que le max — un fichier avec mean > 5 a globalement des fonctions denses
    complexityMean: { p25: 1.5, p90: 5 },

    // Complexité cognitive max
    // Modèle SonarSource : p90 à 30 correspond aux fonctions de parsing/routing complexes
    cognitiveComplexity: { p25: 4, p90: 30 },

    // Taille max de fonction (lignes)
    // p90 à 60L : au-delà on entre dans les fonctions monolithiques
    functionSize: { p25: 15, p90: 60 },

    // Taille moyenne de fonction (lignes)
    // Un fichier avec mean > 30L a globalement des grandes fonctions
    functionSizeMean: { p25: 8, p90: 30 },

    // Profondeur d'imbrication max
    // depth > 4 est rare dans du code bien structuré
    depth: { p25: 1, p90: 4 },

    // Nombre max de paramètres
    // params > 5 commence à signaler un problème de design
    params: { p25: 2, p90: 5 },

    // Churn git sur 30 jours
    // p90 à 10 : un fichier modifié + de 10x en 30 jours est une zone instable
    churn: { p25: 1, p90: 10 },
};

// ── BASELINES PAR TYPE DE FICHIER ────────────────────────────────────────────
//
// Certains types de fichiers ont des profils de complexité naturellement
// différents. On surcharge les valeurs de référence pour ces cas spécifiques.
//
// Types détectés via nom/chemin dans detectFileType().

export type FileType = 'entrypoint' | 'component' | 'service' | 'parser' | 'utility' | 'config' | 'generic';

// Surcharges partielles par type — seules les métriques qui diffèrent significativement
const FILE_TYPE_OVERRIDES: Record<FileType, Partial<ProjectBaselines>> = {

    // App.tsx, index.tsx, main.ts — points d'entrée React/Electron
    // Naturellement grands : state global, IPC, routing. Complexité élevée tolérée.
    entrypoint: {
        complexity:          { p25: 8,  p90: 40  },
        cognitiveComplexity: { p25: 10, p90: 80  },
        functionSize:        { p25: 30, p90: 200 },
        functionSizeMean:    { p25: 15, p90: 80  },
    },

    // Composants React (*.tsx hors entrypoint) — taille modérée attendue
    component: {
        complexity:          { p25: 3,  p90: 15  },
        cognitiveComplexity: { p25: 4,  p90: 35  },
        functionSize:        { p25: 20, p90: 80  },
        functionSizeMean:    { p25: 10, p90: 40  },
    },

    // Services, modules métier (db.ts, llm.ts, scanner.ts...)
    // Complexité modérée-haute attendue, churn potentiellement élevé
    service: {
        complexity:          { p25: 4,  p90: 18  },
        cognitiveComplexity: { p25: 6,  p90: 40  },
        functionSize:        { p25: 20, p90: 80  },
        functionSizeMean:    { p25: 12, p90: 40  },
        churn:               { p25: 2,  p90: 15  },
    },

    // Parsers, analyseurs (parser.ts, lexer.ts, analyzer.ts...)
    // Complexité intrinsèquement élevée — c'est le cœur algorithmique
    parser: {
        complexity:          { p25: 6,  p90: 25  },
        cognitiveComplexity: { p25: 8,  p90: 50  },
        functionSize:        { p25: 25, p90: 100 },
        functionSizeMean:    { p25: 15, p90: 50  },
        depth:               { p25: 2,  p90: 6   },
    },

    // Utilitaires (utils.ts, helpers.ts, shared/*)
    // Fonctions petites et nombreuses — complexité basse attendue
    utility: {
        complexity:          { p25: 1, p90: 6  },
        cognitiveComplexity: { p25: 1, p90: 12 },
        functionSize:        { p25: 8, p90: 30 },
        functionSizeMean:    { p25: 5, p90: 20 },
    },

    // Configs, types, déclarations, données statiques (config.ts, types.ts, baselines...)
    // Peu de logique métier, mais peut contenir de grands objets littéraux
    config: {
        complexity:          { p25: 1, p90: 6  },
        cognitiveComplexity: { p25: 1, p90: 10 },
        functionSize:        { p25: 5, p90: 40 },
        functionSizeMean:    { p25: 3, p90: 20 },
    },

    // Cas général — on utilise REFERENCE_BASELINES tel quel
    generic: {},
};

// ── DÉTECTION DU TYPE DE FICHIER ─────────────────────────────────────────────
//
// Implémentation en table de données — évite une cascade de if/else
// qui génèrerait une complexité cyclomatique élevée sur detectFileType elle-même.

// Noms exacts → type
const EXACT_NAMES: Record<string, FileType> = {
    'app.tsx': 'entrypoint', 'app.ts': 'entrypoint', 'app.jsx': 'entrypoint',
    'index.tsx': 'entrypoint', 'index.ts': 'entrypoint', 'main.ts': 'entrypoint',
    'index.js': 'entrypoint', 'main.js': 'entrypoint',
    'types.ts': 'config', 'types.tsx': 'config',
    'constants.ts': 'config', 'settings.ts': 'config',
};

// Fragments de nom → type (ordre prioritaire)
const NAME_FRAGMENTS: [string, FileType][] = [
    // config
    ['baseline',   'config'],
    ['reference',  'config'],
    ['constants',  'config'],
    ['fixtures',   'config'],
    ['defaults',   'config'],
    ['thresholds', 'config'],
    // parser
    ['parser',     'parser'],
    ['lexer',      'parser'],
    ['analyzer',   'parser'],
    // service
    ['service',    'service'],
    ['store',      'service'],
    ['engine',     'service'],
    ['manager',    'service'],
    ['handler',    'service'],
    ['controller', 'service'],
    ['scanner',    'service'],
    ['watcher',    'service'],
    ['socket',     'service'],
    ['churn',      'service'],
    // utility
    ['util',       'utility'],
    ['helper',     'utility'],
    ['common',     'utility'],
    ['format',     'utility'],
    ['transform',  'utility'],
];

export function detectFileType(filePath: string): FileType {
    const name  = filePath.split('/').pop()?.toLowerCase() ?? '';
    const ext   = name.split('.').pop() ?? '';
    const parts = filePath.toLowerCase().split('/');

    // 1. Nom exact
    if (name in EXACT_NAMES) return EXACT_NAMES[name]!;

    // 2. Préfixe config
    if (name.startsWith('config') || name.endsWith('.config.ts')) return 'config';

    // 3. Fragments dans le nom
    for (const [fragment, type] of NAME_FRAGMENTS) {
        if (name.includes(fragment)) return type;
    }

    // 4. Dossier shared → utility
    if (parts.includes('shared') || parts.includes('lib')) return 'utility';

    // 5. Extension
    if (ext === 'tsx' || ext === 'jsx') return 'component';

    return 'generic';
}

// ── MERGE : baselines de référence + surcharge par type ──────────────────────

export function getReferenceBaselines(filePath: string): ProjectBaselines {
    const fileType = detectFileType(filePath);
    const overrides = FILE_TYPE_OVERRIDES[fileType];

    // Fusionne REFERENCE_BASELINES avec les surcharges du type
    const result = { ...REFERENCE_BASELINES };
    for (const [key, value] of Object.entries(overrides)) {
        (result as any)[key] = value;
    }

    return result;
}
