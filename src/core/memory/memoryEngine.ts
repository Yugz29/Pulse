/**
 * Pulse Memory Engine v2
 * Les notes sont générées par le LLM lui-même — pas par des règles déterministes.
 * Principe : seul le LLM sait ce qui vaut la peine d'être retenu à long terme.
 *
 * Triggers :
 *   - Après chaque analyse fichier (askLLM) → extractMemoryFromAnalysis()
 *   - Après résolution d'une erreur terminal → extractMemoryFromError()
 *
 * L'infra (table, CRUD, decay, snapshot) est conservée intacte.
 */

import { getDb } from '../database/db.js';

// ── TYPES ──────────────────────────────────────────────────────────────────────

export type MemoryType =
    | 'insight'     // fait durable sur un fichier (extrait post-analyse)
    | 'pattern'     // comportement développeur observé
    | 'fix'         // solution appliquée à une erreur terminal
    | 'warning';    // signal de risque confirmé par le LLM

export interface MemoryNote {
    id:          number;
    type:        MemoryType;
    subject:     string;   // filePath ou commande terminal
    content:     string;   // la note en langage naturel
    tags:        string[];
    links:       number[];
    weight:      number;   // 0.1–1.0, décroît avec le temps
    projectPath: string;
    createdAt:   string;
    updatedAt:   string;
    dismissed:   boolean;
}

// Réponse attendue du LLM lors de l'extraction
export interface MemoryExtraction {
    facts: Array<{
        type:    MemoryType;
        content: string;      // note atomique, max ~120 chars
        tags:    string[];    // 2-4 mots-clés
    }>;
    noop: boolean;            // true = rien de mémorable
}

// ── INIT TABLE ────────────────────────────────────────────────────────────────

export function initMemoryTable(): void {
    const db = getDb();
    db.exec(`
        CREATE TABLE IF NOT EXISTS memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            type         TEXT    NOT NULL,
            subject      TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            tags         TEXT    NOT NULL DEFAULT '[]',
            links        TEXT    NOT NULL DEFAULT '[]',
            weight       REAL    NOT NULL DEFAULT 1.0,
            project_path TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL,
            dismissed    INTEGER NOT NULL DEFAULT 0
        )
    `);
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export function upsertMemory(params: {
    type:        MemoryType;
    subject:     string;
    content:     string;
    tags:        string[];
    links:       number[];
    weight:      number;
    projectPath: string;
}): number {
    const db  = getDb();
    const now = new Date().toISOString();

    // Déduplique par (type, subject, contenu similaire)
    // On compare les 60 premiers chars du content pour éviter les doublons quasi-identiques
    const existing = db.prepare(`
        SELECT id FROM memories
        WHERE type = ? AND subject = ? AND project_path = ? AND dismissed = 0
          AND SUBSTR(content, 1, 60) = SUBSTR(?, 1, 60)
        LIMIT 1
    `).get(params.type, params.subject, params.projectPath, params.content) as { id: number } | undefined;

    if (existing) {
        db.prepare(`
            UPDATE memories
            SET content = ?, tags = ?, weight = ?, updated_at = ?
            WHERE id = ?
        `).run(
            params.content,
            JSON.stringify(params.tags),
            Math.min(1.0, params.weight),
            now,
            existing.id,
        );
        return existing.id;
    }

    const result = db.prepare(`
        INSERT INTO memories (type, subject, content, tags, links, weight, project_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
        params.type,
        params.subject,
        params.content,
        JSON.stringify(params.tags),
        JSON.stringify(params.links),
        Math.min(1.0, params.weight),
        params.projectPath,
        now,
        now,
    );
    return result.lastInsertRowid as number;
}

export function getMemories(projectPath: string): MemoryNote[] {
    const rows = getDb().prepare(`
        SELECT * FROM memories
        WHERE project_path = ? AND dismissed = 0
        ORDER BY weight DESC, updated_at DESC
        LIMIT 30
    `).all(projectPath) as any[];
    return rows.map(rowToNote);
}

export function getMemoriesForFile(filePath: string, projectPath: string): MemoryNote[] {
    const fileName = filePath.split('/').pop() ?? filePath;
    const rows = getDb().prepare(`
        SELECT * FROM memories
        WHERE project_path = ? AND dismissed = 0
          AND (subject = ? OR subject = ? OR tags LIKE ?)
        ORDER BY weight DESC, updated_at DESC
        LIMIT 10
    `).all(projectPath, filePath, fileName, `%"${fileName}"%`) as any[];
    return rows.map(rowToNote);
}

export function dismissMemory(id: number): void {
    getDb().prepare(`UPDATE memories SET dismissed = 1, updated_at = ? WHERE id = ?`)
        .run(new Date().toISOString(), id);
}

export function updateMemoryContent(id: number, content: string): void {
    getDb().prepare(`UPDATE memories SET content = ?, updated_at = ? WHERE id = ?`)
        .run(content, new Date().toISOString(), id);
}

export function cleanMemoriesForDeletedFiles(existingPaths: Set<string>, projectPath: string): void {
    const db   = getDb();
    const rows = db.prepare(`
        SELECT id, subject FROM memories WHERE project_path = ? AND dismissed = 0
    `).all(projectPath) as { id: number; subject: string }[];

    for (const row of rows) {
        if (row.subject.startsWith('/') && !existingPaths.has(row.subject)) {
            db.prepare(`UPDATE memories SET dismissed = 1 WHERE id = ?`).run(row.id);
        }
    }
}

function rowToNote(r: any): MemoryNote {
    return {
        id:          r.id,
        type:        r.type as MemoryType,
        subject:     r.subject,
        content:     r.content,
        tags:        JSON.parse(r.tags  ?? '[]'),
        links:       JSON.parse(r.links ?? '[]'),
        weight:      r.weight,
        projectPath: r.project_path,
        createdAt:   r.created_at,
        updatedAt:   r.updated_at,
        dismissed:   r.dismissed === 1,
    };
}

// ── DECAY ─────────────────────────────────────────────────────────────────────
// Appelé au démarrage — réduit le poids des notes anciennes non confirmées

export function applyDecay(projectPath: string): void {
    const db  = getDb();
    const now = Date.now();

    const notes = db.prepare(`
        SELECT id, weight, updated_at FROM memories
        WHERE project_path = ? AND dismissed = 0
    `).all(projectPath) as { id: number; weight: number; updated_at: string }[];

    for (const note of notes) {
        const ageDays = (now - new Date(note.updated_at).getTime()) / (1000 * 60 * 60 * 24);
        const decayed = Math.max(0.1, note.weight - ageDays * 0.03);
        if (Math.abs(decayed - note.weight) > 0.01) {
            db.prepare(`UPDATE memories SET weight = ? WHERE id = ?`).run(decayed, note.id);
        }
    }
}

// ── EXTRACTION POST-ANALYSE ───────────────────────────────────────────────────

/**
 * Appelé après askLLM() — prend l'analyse générée et demande au LLM
 * d'en extraire 0-2 faits atomiques mémorables.
 * Fire-and-forget : les erreurs sont silencieuses (pas bloquant pour l'UI).
 */
export async function extractMemoryFromAnalysis(params: {
    filePath:    string;
    analysis:    string;   // le texte complet généré par askLLM
    projectPath: string;
}): Promise<void> {
    try {
        const { extractMemoryFacts } = await import('../llm/llm.js');
        const fileName = params.filePath.split('/').pop() ?? params.filePath;

        const result = await extractMemoryFacts({
            context: `Fichier analysé : ${fileName}\n\n${params.analysis}`,
            subject: params.filePath,
        });

        if (result.noop || result.facts.length === 0) return;

        for (const fact of result.facts.slice(0, 2)) {
            upsertMemory({
                type:        fact.type,
                subject:     params.filePath,
                content:     fact.content,
                tags:        [fileName, ...fact.tags].slice(0, 5),
                links:       [],
                weight:      0.85,
                projectPath: params.projectPath,
            });
        }

        console.log(`[Pulse Memory] ${result.facts.length} fact(s) extracted from ${fileName}`);
    } catch (err) {
        // Silencieux — l'extraction mémoire ne doit jamais bloquer l'UI
        console.warn('[Pulse Memory] extractMemoryFromAnalysis failed silently:', err);
    }
}

/**
 * Appelé quand le dev clique "Résolu" sur une erreur terminal.
 * Mémorise ce qui a été appris de la résolution.
 */
export async function extractMemoryFromError(params: {
    command:     string;
    errorText:   string;
    llmAnalysis: string;   // l'analyse LLM déjà générée pour cette erreur
    projectPath: string;
}): Promise<void> {
    try {
        const { extractMemoryFacts } = await import('../llm/llm.js');
        const cmdShort = params.command.length > 60
            ? params.command.slice(0, 60) + '…'
            : params.command;

        const result = await extractMemoryFacts({
            context: `Erreur terminal résolue.\nCommande : ${cmdShort}\n\nAnalyse LLM :\n${params.llmAnalysis}`,
            subject: params.command,
        });

        if (result.noop || result.facts.length === 0) return;

        for (const fact of result.facts.slice(0, 2)) {
            upsertMemory({
                type:        fact.type === 'insight' ? 'fix' : fact.type,
                subject:     params.command,
                content:     fact.content,
                tags:        ['terminal', 'resolved', ...fact.tags].slice(0, 5),
                links:       [],
                weight:      0.9,   // erreurs résolues ont plus de poids — connaissance active
                projectPath: params.projectPath,
            });
        }

        console.log(`[Pulse Memory] Error memory extracted for: ${cmdShort}`);
    } catch (err) {
        console.warn('[Pulse Memory] extractMemoryFromError failed silently:', err);
    }
}

// ── POINT D'ENTRÉE (startup uniquement) ──────────────────────────────────────
// Plus de règles déterministes — juste le decay au démarrage

export function runMemoryEngineOnStartup(projectPath: string): void {
    try {
        applyDecay(projectPath);
        console.log('[Pulse Memory] Startup decay applied.');
    } catch (err) {
        console.error('[Pulse Memory] Startup error:', err);
    }
}

// ── SNAPSHOT LLM ──────────────────────────────────────────────────────────────

export function buildMemorySnapshot(projectPath: string, filePath?: string): string {
    const notes = filePath
        ? getMemoriesForFile(filePath, projectPath)
        : getMemories(projectPath).slice(0, 5);

    if (notes.length === 0) return '';

    const lines  = notes.map(n => `· [${n.type}] ${n.content}`).join('\n');
    const header = filePath
        ? `[PULSE MEMORY · ${filePath.split('/').pop()}]`
        : '[PULSE MEMORY · project]';

    return `${header}\n${lines}`;
}
