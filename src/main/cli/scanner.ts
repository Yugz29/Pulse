import fs from 'node:fs';
import path from 'node:path';
import { analyzeFile } from '../analyzer/parser.js';
import { extractRaw, scoreFromRaw, computeProjectBaselines } from '../risk-score/riskScore.js';
import type { RawMetrics, RiskScoreResult } from '../risk-score/riskScore.js';
import { saveScan, saveFunctions } from '../database/db.js';
import { loadConfig } from '../config.js';
import { buildChurnCache, clearChurnCache, getChurnScore } from '../analyzer/churn.js';
import type { FileMetrics } from '../analyzer/parser.js';

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

interface FileAnalysis {
    metrics:  FileMetrics;
    raw:      RawMetrics;
}

export async function scanProject(projectPath: string): Promise<ScanResult> {
    const config = loadConfig();
    const files  = getFiles(projectPath, config.ignore);

    clearChurnCache();
    await buildChurnCache();
    console.log(`[Pulse] Found ${files.length} files to scan`);

    // ── Passe 1 : analyse statique + collecte des métriques brutes ──

    const analyses: FileAnalysis[] = [];
    const fileSources = new Map<string, string>();

    for (const file of files) {
        try {
            const source = fs.readFileSync(file, 'utf-8');
            fileSources.set(file, source);

            const metrics = await analyzeFile(file);
            saveFunctions(file, metrics.functions, projectPath);

            // Churn déjà en cache — appel synchrone-like
            const fns  = metrics.functions.filter(fn => fn.name !== 'anonymous');
            const churn = await getChurnScore(file);
            const raw: RawMetrics = {
                complexity:          fns.length > 0 ? Math.max(...fns.map(f => f.cyclomaticComplexity))                          : 0,
                complexityMean:      fns.length > 0 ? fns.reduce((s, f) => s + f.cyclomaticComplexity, 0) / fns.length           : 0,
                cognitiveComplexity: fns.length > 0 ? Math.max(...fns.map(f => f.cognitiveComplexity ?? 0))                      : 0,
                functionSize:        fns.length > 0 ? Math.max(...fns.map(f => f.lineCount))                                     : 0,
                functionSizeMean:    fns.length > 0 ? fns.reduce((s, f) => s + f.lineCount, 0) / fns.length                      : 0,
                depth:               fns.length > 0 ? Math.max(...fns.map(f => f.maxDepth))                                      : 0,
                params:              fns.length > 0 ? Math.max(...fns.map(f => f.parameterCount))                                : 0,
                churn,
            };

            analyses.push({ metrics, raw });
        } catch (error) {
            console.error(`[Pulse] Error analyzing ${path.basename(file)}:`, error);
        }
    }

    // ── Baselines : calcul des percentiles sur l'ensemble du projet ──

    const baselines = computeProjectBaselines(analyses.map(a => a.raw));
    console.log('[Pulse] Baselines —', Object.entries(baselines).map(
        ([k, v]) => `${k}: p25=${v.p25.toFixed(1)} p90=${v.p90.toFixed(1)}`
    ).join(' | '));

    // ── Passe 2 : scoring adaptatif ──

    const results: RiskScoreResult[] = analyses.map(({ metrics, raw }) =>
        scoreFromRaw(raw, metrics.filePath, metrics.language, baselines)
    );

    // ── Edges + fan-in / fan-out ──

    const edges = buildEdges(files, fileSources);

    const fanOutMap = new Map<string, number>();
    const fanInMap  = new Map<string, number>();
    for (const file of files) { fanOutMap.set(file, 0); fanInMap.set(file, 0); }
    for (const edge of edges) {
        fanOutMap.set(edge.from, (fanOutMap.get(edge.from) ?? 0) + 1);
        fanInMap.set(edge.to,   (fanInMap.get(edge.to)   ?? 0) + 1);
    }

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
