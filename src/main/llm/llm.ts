import fs from 'node:fs';
import type { FunctionMetrics } from '../analyzer/parser.js';

const OLLAMA_URL = 'http://localhost:11434/api/generate';
const MODEL      = 'qwen2.5-coder:7b-instruct-q4_K_M';

export interface LLMContext {
    filePath: string;
    globalScore: number;
    details: {
        complexityScore: number;
        functionSizeScore: number;
        churnScore: number;
        depthScore: number;
        paramScore: number;
    };
    functions: FunctionMetrics[];
}

function getFileName(p: string): string {
    return p.split('/').pop() ?? p;
}

function buildPrompt(ctx: LLMContext, source: string): string {
    const topFns = ctx.functions
        .filter(fn => fn.name !== 'anonymous')
        .sort((a, b) => b.cyclomaticComplexity - a.cyclomaticComplexity)
        .slice(0, 5)
        .map(fn => `  - ${fn.name}(): cx=${fn.cyclomaticComplexity}, ${fn.lineCount} lines, depth=${fn.maxDepth}, params=${fn.parameterCount}`)
        .join('\n');

    return `You are a code quality expert. Analyze the following file and provide actionable refactoring suggestions.

## File: ${getFileName(ctx.filePath)}
## Risk Score: ${ctx.globalScore.toFixed(1)}/100

## Metrics breakdown:
- Cyclomatic complexity score: ${ctx.details.complexityScore.toFixed(1)}/100
- Function size score: ${ctx.details.functionSizeScore.toFixed(1)}/100
- Nesting depth score: ${ctx.details.depthScore.toFixed(1)}/100
- Parameter count score: ${ctx.details.paramScore.toFixed(1)}/100
- Churn score: ${ctx.details.churnScore.toFixed(1)}/100

## Most complex functions:
${topFns || '  (none)'}

## Source code:
\`\`\`
${source.slice(0, 6000)}${source.length > 6000 ? '\n... (truncated)' : ''}
\`\`\`

Réponds en français. Fournis une analyse concise (3-5 phrases) expliquant POURQUOI ce fichier a un score de risque élevé, puis liste 2-3 suggestions de refactorisation concrètes avec de brefs exemples de code si pertinent. Sois direct et pratique.`;
}

export async function askLLM(
    ctx: LLMContext,
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: string) => void,
): Promise<void> {
    let source: string;
    try {
        source = fs.readFileSync(ctx.filePath, 'utf-8');
    } catch {
        onError(`Cannot read file: ${ctx.filePath}`);
        return;
    }

    const prompt = buildPrompt(ctx, source);

    try {
        const res = await fetch(OLLAMA_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: MODEL, prompt, stream: true }),
        });

        if (!res.ok || !res.body) {
            onError(`Ollama error: ${res.status} ${res.statusText}`);
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const lines = decoder.decode(value).split('\n').filter(Boolean);
            for (const line of lines) {
                try {
                    const json = JSON.parse(line) as { response?: string; done?: boolean };
                    if (json.response) onChunk(json.response);
                    if (json.done) { onDone(); return; }
                } catch { /* ligne incomplète */ }
            }
        }
        onDone();
    } catch (err) {
        onError(`Ollama unreachable: ${err instanceof Error ? err.message : String(err)}`);
    }
}
