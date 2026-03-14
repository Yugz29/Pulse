import { getOllamaConfig, OLLAMA_OPTIONS } from './config.js';
import type { ModelRole, ChatMessage } from './config.js';

// ── ABORT CONTROLLER GLOBAL ──

let _currentAbort: AbortController | null = null;

export function abortCurrentLLM(): void {
    _currentAbort?.abort();
}

// ── STREAMING HELPER ──

export async function streamOllamaChat(
    messages: ChatMessage[],
    onChunk:  (text: string) => void,
    onDone:   () => void,
    onError:  (err: string) => void,
    role:     ModelRole = 'default',
    options:  Record<string, unknown> = OLLAMA_OPTIONS,
): Promise<void> {
    _currentAbort?.abort();
    const abort = new AbortController();
    _currentAbort = abort;

    try {
        const cfg = getOllamaConfig(role);

        const body = cfg.isPerspective
            ? JSON.stringify({ model: cfg.model, messages, stream: true })
            : JSON.stringify({ model: cfg.model, messages, stream: true, options });

        const res = await fetch(cfg.chatUrl, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
            signal:  abort.signal,
        });

        if (!res.ok || !res.body) {
            onError(`Erreur Ollama : ${res.status} ${res.statusText}`);
            return;
        }

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const lines = decoder.decode(value).split('\n').filter(Boolean);
            for (const line of lines) {
                try {
                    if (cfg.isPerspective) {
                        const raw = line.startsWith('data: ') ? line.slice(6) : line;
                        if (raw === '[DONE]') { onDone(); return; }
                        const json = JSON.parse(raw) as {
                            choices?: { delta?: { content?: string }; finish_reason?: string }[];
                        };
                        const content = json.choices?.[0]?.delta?.content;
                        if (content) onChunk(content);
                        if (json.choices?.[0]?.finish_reason === 'stop') { onDone(); return; }
                    } else {
                        const json = JSON.parse(line) as {
                            message?: { content?: string };
                            done?:    boolean;
                        };
                        if (json.message?.content) onChunk(json.message.content);
                        if (json.done) { onDone(); return; }
                    }
                } catch { /* ligne incomplète */ }
            }
        }
        onDone();
    } catch (err) {
        if (abort.signal.aborted) return;
        onError(`Ollama inaccessible : ${err instanceof Error ? err.message : String(err)}`);
    }
}

// ── CONTINUATION (multi-turn, suit une analyse initiale) ──

export async function continueLLM(
    messages: ChatMessage[],
    onChunk:  (text: string) => void,
    onDone:   () => void,
    onError:  (err: string) => void,
): Promise<void> {
    const system: ChatMessage = {
        role:    'system',
        content: 'Tu es un expert senior en qualité de code. Réponds en français, de manière directe et pratique. Appuie-toi sur le code et l\'analyse déjà fournie pour répondre aux questions.',
    };

    let chat = [...messages];
    if (chat[0]?.role === 'assistant') {
        chat = [{ role: 'user', content: 'Analyse ce fichier et donne tes observations.' }, ...chat];
    }

    await streamOllamaChat([system, ...chat], onChunk, onDone, onError, 'analyzer');
}
