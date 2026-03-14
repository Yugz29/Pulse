import { loadSettings } from '../../app/main/settings.js';

export type ModelRole = 'analyzer' | 'coder' | 'brainstorm' | 'fast' | 'default';

export interface OllamaConfig {
    model:         string;
    chatUrl:       string;
    isPerspective: boolean;
}

export interface ChatMessage {
    role:    'system' | 'user' | 'assistant';
    content: string;
}

export const OLLAMA_OPTIONS         = { num_ctx: 4096, repeat_penalty: 1.1,  num_predict: 900  } as const;
export const OLLAMA_OPTIONS_COMPACT = { num_ctx: 2048, repeat_penalty: 1.15, num_predict: 512  } as const;
export const OLLAMA_OPTIONS_INTEL   = { num_ctx: 4096, repeat_penalty: 1.1,  num_predict: 1400, think: false } as const;
export const OLLAMA_OPTIONS_EXTRACT = { num_ctx: 2048, repeat_penalty: 1.1,  num_predict: 600, temperature: 0.1 } as const;

const FALLBACK_MODEL = 'pulse-qwen3';

export function getOllamaConfig(role: ModelRole = 'default'): OllamaConfig {
    const s          = loadSettings();
    const general    = s.modelGeneral || s.model || FALLBACK_MODEL;
    const defaultUrl = s.baseUrl || 'http://localhost:11434';

    const modelForRole: Record<ModelRole, string> = {
        analyzer:   s.modelAnalyzer   || general,
        coder:      s.modelCoder      || general,
        brainstorm: s.modelBrainstorm || general,
        fast:       s.modelFast       || general,
        default:    general,
    };

    const baseUrl =
        (role === 'fast'     && s.baseUrlFast)     ? s.baseUrlFast     :
        (role === 'analyzer' && s.baseUrlAnalyzer) ? s.baseUrlAnalyzer :
        defaultUrl;

    const isPerspective = baseUrl.includes('11435');

    return {
        model:    isPerspective ? 'apple.local' : modelForRole[role],
        chatUrl:  isPerspective ? `${baseUrl}/v1/chat/completions` : `${baseUrl}/api/chat`,
        isPerspective,
    };
}
