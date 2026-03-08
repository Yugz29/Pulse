import { contextBridge, ipcRenderer } from 'electron';

// ── Terminal error types (inline pour éviter imports circulaires en CJS preload) ──
export interface TerminalErrorNotification {
    command: string;
    exit_code: number;
    cwd: string;
    errorText: string;
    errorHash: string;
    timestamp: number;
    id: number;
    pastOccurrences: number;
    lastSeen: string | null;
}

export interface LatestScan {
    filePath: string;
    globalScore: number;
    complexityScore: number;
    functionSizeScore: number;
    churnScore: number;
    language: string;
    scannedAt: string;
    trend: '↑' | '↓' | '↔';
    feedback: string | null;
}

export interface Edge {
    from: string;
    to: string;
}

contextBridge.exposeInMainWorld('api', {
    getScans: (): Promise<LatestScan[]> => ipcRenderer.invoke('get-scans'),
    getEdges: (): Promise<Edge[]>       => ipcRenderer.invoke('get-edges'),
    getFunctions: (filePath: string): Promise<any[]> => ipcRenderer.invoke('get-functions', filePath),
    saveFeedback: (filePath: string, action: string, score: number): Promise<void> => ipcRenderer.invoke('save-feedback', filePath, action, score),
    getScoreHistory: (filePath: string): Promise<{ score: number; scanned_at: string }[]> => ipcRenderer.invoke('get-score-history', filePath),
    getFeedbackHistory: (filePath: string): Promise<{ action: string; created_at: string }[]> => ipcRenderer.invoke('get-feedback-history', filePath),
    askLLM: (ctx: any): void => ipcRenderer.send('ask-llm', ctx),
    askLLMProject: (payload: { ctx: any; messages: any[] }): void => ipcRenderer.send('ask-llm-project', payload),
    abortLLM: (): void => ipcRenderer.send('abort-llm'),

    // ── LLM listeners — retournent un unlisten() pour cleanup propre ──
    onLLMChunk: (cb: (chunk: string) => void): (() => void) => {
        const handler = (_ipc: any, chunk: string) => cb(chunk);
        ipcRenderer.on('llm-chunk', handler);
        return () => ipcRenderer.removeListener('llm-chunk', handler);
    },
    onLLMDone: (cb: () => void): (() => void) => {
        const handler = () => cb();
        ipcRenderer.on('llm-done', handler);
        return () => ipcRenderer.removeListener('llm-done', handler);
    },
    onLLMError: (cb: (err: string) => void): (() => void) => {
        const handler = (_ipc: any, err: string) => cb(err);
        ipcRenderer.on('llm-error', handler);
        return () => ipcRenderer.removeListener('llm-error', handler);
    },

    onScanComplete: (cb: () => void): void => {
        ipcRenderer.removeAllListeners('scan-complete');
        ipcRenderer.on('scan-complete', cb);
    },
    onEvent: (cb: (e: any) => void): void => {
        ipcRenderer.removeAllListeners('pulse-event');
        ipcRenderer.on('pulse-event', (_ipc, e) => cb(e));
    },

    // ── Project ──
    getProjectPath: (): Promise<string> =>
        ipcRenderer.invoke('get-project-path'),

    // ── Shell hook ──
    getShellHook: (): Promise<{ shell: string; snippet: string; installPath: string }> =>
        ipcRenderer.invoke('get-shell-hook'),

    pickProject: (): Promise<string | null> =>
        ipcRenderer.invoke('pick-project'),

    getProjectScoreHistory: (): Promise<{ date: string; score: number }[]> =>
        ipcRenderer.invoke('get-project-score-history'),

    // ── Terminal shell integration ──
    getSocketPort: (): Promise<number> =>
        ipcRenderer.invoke('get-socket-port'),

    onTerminalError: (cb: (ctx: TerminalErrorNotification) => void): void => {
        ipcRenderer.removeAllListeners('terminal-error');
        ipcRenderer.on('terminal-error', (_ipc, ctx) => cb(ctx));
    },

    dismissTerminalError: (): void =>
        ipcRenderer.send('dismiss-terminal-error'),

    analyzeTerminalError: (ctx: TerminalErrorNotification): void =>
        ipcRenderer.send('analyze-terminal-error', ctx),

    resolveTerminalError: (id: number, resolved: 1 | -1, errorContext?: { command: string; errorText: string; llmResponse?: string }): void =>
        ipcRenderer.send('resolve-terminal-error', id, resolved, errorContext),

    getLlmReport: (filePath: string): Promise<string | null> =>
        ipcRenderer.invoke('get-llm-report', filePath),

    // ── Intel memory ──
    getIntelMessages: (): Promise<{ role: 'user' | 'assistant'; content: string }[]> =>
        ipcRenderer.invoke('get-intel-messages'),

    saveIntelMessage: (role: 'user' | 'assistant', content: string): Promise<void> =>
        ipcRenderer.invoke('save-intel-message', role, content),

    clearIntelMessages: (): Promise<void> =>
        ipcRenderer.invoke('clear-intel-messages'),

    // ── Memory ──
    getMemories: (): Promise<any[]> =>
        ipcRenderer.invoke('get-memories'),
    getMemoriesForFile: (filePath: string): Promise<any[]> =>
        ipcRenderer.invoke('get-memories-for-file', filePath),
    dismissMemory: (id: number): Promise<void> =>
        ipcRenderer.invoke('dismiss-memory', id),
    updateMemory: (id: number, content: string): Promise<void> =>
        ipcRenderer.invoke('update-memory', id, content),
    onMemoriesUpdated: (cb: () => void): void => {
        ipcRenderer.removeAllListeners('memories-updated');
        ipcRenderer.on('memories-updated', cb);
    },

    // ── Settings ──
    getSettings: (): Promise<{
        model: string;
        baseUrl: string;
        modelGeneral: string;
        modelAnalyzer: string;
        modelCoder: string;
        modelBrainstorm: string;
        modelFast: string;
    }> => ipcRenderer.invoke('get-settings'),

    saveSettings: (s: {
        model: string;
        baseUrl: string;
        modelGeneral: string;
        modelAnalyzer: string;
        modelCoder: string;
        modelBrainstorm: string;
        modelFast: string;
    }): Promise<void> => ipcRenderer.invoke('save-settings', s),
});
