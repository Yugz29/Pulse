import { simpleGit } from 'simple-git';
import { join } from 'node:path';
import { loadConfig } from '../../app/main/config.js';

export interface FileCoupling {
    fileA:        string;
    fileB:        string;
    coChangeCount: number;
}

let _churnCache: Map<string, number> | null = null;

export async function buildChurnCache(): Promise<void> {
    try {
        const config = loadConfig();
        const git = simpleGit(config.projectPath);
        const gitRoot = (await git.revparse(['--show-toplevel'])).trim();
        const log = await git.raw(['log', '--since=30 days ago', '--name-only', '--pretty=format:']);
        _churnCache = new Map();
        for (const line of log.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            const abs = join(gitRoot, trimmed);
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

export async function buildCouplingMap(
    projectPath: string,
    minCoChanges = 3,
): Promise<Map<string, FileCoupling[]>> {
    const result = new Map<string, FileCoupling[]>();
    try {
        const git     = simpleGit(projectPath);
        const gitRoot = (await git.revparse(['--show-toplevel'])).trim();
        const log = await git.raw(['log', '--since=90 days ago', '--name-only', '--pretty=format:%H']);
        const commitGroups = new Map<string, string[]>();
        let currentHash: string | null = null;
        for (const line of log.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            if (/^[0-9a-f]{40}$/.test(trimmed)) {
                currentHash = trimmed;
                commitGroups.set(currentHash, []);
            } else if (currentHash) {
                const abs = join(gitRoot, trimmed);
                commitGroups.get(currentHash)!.push(abs);
            }
        }
        const pairCounts = new Map<string, number>();
        for (const [, filesInCommit] of commitGroups) {
            if (filesInCommit.length < 2) continue;
            for (let i = 0; i < filesInCommit.length; i++) {
                for (let j = i + 1; j < filesInCommit.length; j++) {
                    const a   = filesInCommit[i]!;
                    const b   = filesInCommit[j]!;
                    const key = a < b ? `${a}\0${b}` : `${b}\0${a}`;
                    pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
                }
            }
        }
        for (const [key, count] of pairCounts) {
            if (count < minCoChanges) continue;
            const [fileA, fileB] = key.split('\0') as [string, string];
            const coupling: FileCoupling = { fileA, fileB, coChangeCount: count };
            if (!result.has(fileA)) result.set(fileA, []);
            if (!result.has(fileB)) result.set(fileB, []);
            result.get(fileA)!.push(coupling);
            result.get(fileB)!.push(coupling);
        }
    } catch { }
    return result;
}
