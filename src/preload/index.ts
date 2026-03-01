import { contextBridge, ipcRenderer } from 'electron';

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
    onLLMChunk: (cb: (chunk: string) => void): void => {
        ipcRenderer.removeAllListeners('llm-chunk');
        ipcRenderer.on('llm-chunk', (_ipc, chunk) => cb(chunk));
    },
    onLLMDone: (cb: () => void): void => {
        ipcRenderer.removeAllListeners('llm-done');
        ipcRenderer.on('llm-done', cb);
    },
    onLLMError: (cb: (err: string) => void): void => {
        ipcRenderer.removeAllListeners('llm-error');
        ipcRenderer.on('llm-error', (_ipc, err) => cb(err));
    },
    onScanComplete: (cb: () => void): void => {
        ipcRenderer.removeAllListeners('scan-complete');
        ipcRenderer.on('scan-complete', cb);
    },
    onEvent: (cb: (e: any) => void): void => {
        ipcRenderer.removeAllListeners('pulse-event');
        ipcRenderer.on('pulse-event', (_ipc, e) => cb(e));
    },
});
