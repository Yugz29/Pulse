import fs from 'node:fs';
import { streamOllamaChat } from './stream.js';
import { getOllamaConfig, OLLAMA_OPTIONS, OLLAMA_OPTIONS_COMPACT, OLLAMA_OPTIONS_INTEL, OLLAMA_OPTIONS_EXTRACT } from './config.js';
import {
    buildAnalysisMessages,
    buildProjectSystemPrompt,
    buildErrorPrompt,
    buildExplainPrompt,
    buildMemoryExtractionPrompt,
} from './prompts.js';
import type { LLMContext, ProjectContext, IntelMessage, IntelScan } from './prompts.js';
import type { TerminalErrorContext } from '../../app/main/terminal/clipboardWatcher.js';
import type { ChatMessage } from './config.js';

export { abortCurrentLLM, continueLLM } from './stream.js';
export type { ChatMessage }              from './config.js';
export type { TerminalErrorContext }     from '../../app/main/terminal/clipboardWatcher.js';
export type { LLMContext, ProjectContext, IntelMessage, IntelScan } from './prompts.js';

export async function askLLM(
    ctx:             LLMContext,
    onChunk:         (text: string) => void,
    onDone:          () => void,
    onError:         (err: string) => void,
    memorySnapshot?: string,
): Promise<void> {
    let source: string;
    try {
        source = fs.readFileSync(ctx.filePath, 'utf-8');
    } catch {
        onError(`Impossible de lire le fichier : ${ctx.filePath}`);
        return;
    }
    const messages = buildAnalysisMessages(ctx, source, memorySnapshot);
    await streamOllamaChat(messages, onChunk, onDone, onError, 'analyzer', OLLAMA_OPTIONS);
}

export async function askLLMForError(
    ctx:             TerminalErrorContext,
    topFiles:        { filePath: string; globalScore: number }[],
    pastOccurrences: number,
    onChunk:         (text: string) => void,
    onDone:          () => void,
    onError:         (err: string) => void,
): Promise<void> {
    const prompt   = ctx.mode === 'hint' ? buildExplainPrompt(ctx) : buildErrorPrompt(ctx, topFiles, pastOccurrences);
    const messages: ChatMessage[] = [{ role: 'user', content: prompt }];
    await streamOllamaChat(messages, onChunk, onDone, onError, 'fast', OLLAMA_OPTIONS_COMPACT);
}

export async function askLLMProject(
    ctx:      ProjectContext,
    messages: IntelMessage[],
    onChunk:  (text: string) => void,
    onDone:   () => void,
    onError:  (err: string) => void,
): Promise<void> {
    const systemContent  = buildProjectSystemPrompt(ctx);
    const chatMessages: ChatMessage[] = [
        { role: 'system', content: systemContent },
        ...messages.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })),
    ];
    await streamOllamaChat(chatMessages, onChunk, onDone, onError, 'analyzer', OLLAMA_OPTIONS_INTEL);
}

export async function extractMemoryFacts(
    input: { context: string; subject: string },
): Promise<import('../../core/memory/memoryEngine.js').MemoryExtraction> {
    const NOOP: import('../../core/memory/memoryEngine.js').MemoryExtraction = { facts: [], noop: true };

    try {
        const cfg    = getOllamaConfig('fast');
        const prompt = buildMemoryExtractionPrompt(input.context);
        const res    = await fetch(cfg.chatUrl, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    cfg.isPerspective
                ? JSON.stringify({ model: cfg.model, messages: [{ role: 'user', content: prompt }], stream: false })
                : JSON.stringify({ model: cfg.model, messages: [{ role: 'user', content: prompt }], stream: false, think: false, options: OLLAMA_OPTIONS_EXTRACT }),
        });

        if (!res.ok) return NOOP;

        const data = await res.json() as {
            message?: { content?: string };
            choices?: { message?: { content?: string } }[];
        };
        let raw = (data.message?.content ?? data.choices?.[0]?.message?.content ?? '').trim();
        raw = raw.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();

        console.log('[Pulse Memory] Extract raw response:', raw.slice(0, 200));

        const jsonMatch = raw.match(/\{[\s\S]*\}/);
        if (!jsonMatch) {
            console.warn('[Pulse Memory] No JSON found in extraction response');
            return NOOP;
        }

        const parsed = JSON.parse(jsonMatch[0]) as import('../../core/memory/memoryEngine.js').MemoryExtraction;
        console.log('[Pulse Memory] Extracted facts:', parsed.noop ? 'noop' : parsed.facts?.length ?? 0);
        return parsed.noop ? NOOP : parsed;
    } catch {
        return NOOP;
    }
}
