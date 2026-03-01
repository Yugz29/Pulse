import fs from 'node:fs';
import path from 'node:path';
import { analyzeFile } from '../analyzer/parser.js';
import { calculateRiskScore } from '../risk-score/riskScore.js';
import { saveScan, saveFunctions } from '../database/db.js';
import type { RiskScoreResult } from '../risk-score/riskScore.js';
import { loadConfig } from '../config.js';
import { clearChurnCache } from '../analyzer/churn.js';

// Extensions supportées
const SUPPORTED_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.py']);

// Patterns de fichiers à ignorer (bundles, déclarations, maps)
const IGNORE_FILE_PATTERNS = ['.min.js', '.min.ts', '.d.ts', '.map', '.spec.', '.test.', '__tests__'];

function shouldIgnoreFile(filename: string): boolean {
    return IGNORE_FILE_PATTERNS.some(p => filename.includes(p));
}

export function getFiles(dir: string, ignore: string[], fileList: string[] = [], visited = new Set<string>()): string[] {
    let realDir: string;
    try { realDir = fs.realpathSync(dir); } catch { return fileList; }
    if (visited.has(realDir)) return fileList;
    visited.add(realDir);

    let entries: string[];
    try { entries = fs.readdirSync(dir); } catch { return fileList; }

    for (const entry of entries) {
        if (ignore.includes(entry)) continue;

        const fullPath = path.join(dir, entry);
        let stat;
        try { stat = fs.statSync(fullPath); } catch { continue; }

        if (stat.isDirectory()) {
            getFiles(fullPath, ignore, fileList, visited);
            continue;
        }

        const ext = path.extname(entry).toLowerCase();
        if (SUPPORTED_EXTENSIONS.has(ext) && !shouldIgnoreFile(entry)) {
            fileList.push(fullPath);
        }
    }

    return fileList;
}

// ── ANALYSE DES IMPORTS (pour les edges) ──

const IMPORT_PATTERNS: Record<string, RegExp[]> = {
    js: [
        /import\s+.*\s+from\s+['"]([^'"]+)['"]/g,
        /require\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
        /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
    ],
    py: [
        /^from\s+(\.{0,2}[\w.]+)\s+import/gm,
        /^import\s+([\w.]+)/gm,
    ],
};

export interface FileEdge {
    from: string;   // chemin absolu
    to:   string;   // chemin absolu
}

function extractImports(filePath: string, source: string): string[] {
    const ext    = path.extname(filePath).toLowerCase();
    const isPy   = ext === '.py';
    const pats   = isPy ? IMPORT_PATTERNS.py : IMPORT_PATTERNS.js;
    const imports: string[] = [];

    for (const pat of pats) {
        pat.lastIndex = 0;
        let match;
        while ((match = pat.exec(source)) !== null) {
            const raw = match[1];
            // On ignore les packages npm/stdlib (pas de chemin relatif)
            if (raw.startsWith('.')) imports.push(raw);
        }
    }
    return imports;
}

function resolveImport(fromFile: string, importPath: string, allFiles: Set<string>): string | null {
    const dir  = path.dirname(fromFile);
    // Strip .js extension (TypeScript ESM imports use .js but files are .ts)
    const stripped = importPath.replace(/\.js$/, '');
    const base = path.resolve(dir, stripped);

    // Essaie différentes extensions
    const candidates = [
        base,
        base + '.ts', base + '.tsx', base + '.js', base + '.jsx',
        path.join(base, 'index.ts'), path.join(base, 'index.js'),
    ];

    for (const c of candidates) {
        if (allFiles.has(c)) return c;
    }
    return null;
}

export function buildEdges(files: string[], fileSources: Map<string, string>): FileEdge[] {
    const fileSet = new Set(files);
    const edges: FileEdge[] = [];
    const seen  = new Set<string>();

    for (const file of files) {
        const source = fileSources.get(file);
        if (!source) continue;

        const imports = extractImports(file, source);
        for (const imp of imports) {
            const resolved = resolveImport(file, imp, fileSet);
            if (!resolved) continue;

            const key = `${file}→${resolved}`;
            if (seen.has(key)) continue;
            seen.add(key);

            edges.push({ from: file, to: resolved });
        }
    }

    return edges;
}

// ── SCAN PRINCIPAL ──

export interface ScanResult {
    files: RiskScoreResult[];
    edges: FileEdge[];
}

export async function scanProject(projectPath: string): Promise<ScanResult> {
    const config = loadConfig();
    const files  = getFiles(projectPath, config.ignore);

    clearChurnCache();
    console.log(`[Pulse] Found ${files.length} files to scan`);

    const results: RiskScoreResult[] = [];
    const fileSources = new Map<string, string>();

    for (const file of files) {
        try {
            // Lire le source une fois (réutilisé pour les edges)
            const source = fs.readFileSync(file, 'utf-8');
            fileSources.set(file, source);

            const analysis  = await analyzeFile(file);
            const riskScore = await calculateRiskScore(analysis);
            saveFunctions(file, analysis.functions, projectPath);
            results.push(riskScore);
        } catch (error) {
            console.error(`[Pulse] Error analyzing ${path.basename(file)}:`, error);
        }
    }

    // Construire les edges depuis les imports réels
    const edges = buildEdges(files, fileSources);

    // Calculer fan-in / fan-out par fichier
    const fanOutMap = new Map<string, number>();
    const fanInMap  = new Map<string, number>();
    for (const file of files) { fanOutMap.set(file, 0); fanInMap.set(file, 0); }
    for (const edge of edges) {
        fanOutMap.set(edge.from, (fanOutMap.get(edge.from) ?? 0) + 1);
        fanInMap.set(edge.to,   (fanInMap.get(edge.to)   ?? 0) + 1);
    }

    // Injecter dans les résultats puis sauvegarder
    for (const result of results) {
        result.details.fanIn  = fanInMap.get(result.filePath)  ?? 0;
        result.details.fanOut = fanOutMap.get(result.filePath) ?? 0;
        saveScan(result, projectPath);
    }

    console.log(`[Pulse] Scan complete — ${results.length} files, ${edges.length} connections`);

    return {
        files: results.sort((a, b) => b.globalScore - a.globalScore),
        edges,
    };
}
