import { simpleGit } from 'simple-git';
import { loadConfig } from '../config.js';

// Cache du churn : construit une seule fois par scan
let _churnCache: Map<string, number> | null = null;

export async function buildChurnCache(): Promise<void> {
    try {
        const config = loadConfig();
        const git = simpleGit(config.projectPath);
        const log = await git.raw(['log', '--since=30 days ago', '--name-only', '--pretty=format:']);

        _churnCache = new Map();
        for (const line of log.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            // simple-git retourne des chemins relatifs au repo
            const abs = `${config.projectPath}/${trimmed}`;
            _churnCache.set(abs, (_churnCache.get(abs) ?? 0) + 1);
        }
        console.log(`[Pulse] Churn cache built — ${_churnCache.size} files tracked.`);
    } catch {
        _churnCache = new Map();
    }
}

export function clearChurnCache(): void {
    _churnCache = null;
}

export async function getChurnScore(filePath: string): Promise<number> {
    if (!_churnCache) await buildChurnCache();
    return _churnCache!.get(filePath) ?? 0;
}
