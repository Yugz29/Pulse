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
    onScanComplete: (cb: () => void): void => {
        ipcRenderer.removeAllListeners('scan-complete');
        ipcRenderer.on('scan-complete', cb);
    },
    onEvent: (cb: (e: any) => void): void => {
        ipcRenderer.removeAllListeners('pulse-event');
        ipcRenderer.on('pulse-event', (_ipc, e) => cb(e));
    },
});
