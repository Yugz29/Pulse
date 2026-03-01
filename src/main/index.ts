import { app, BrowserWindow, ipcMain } from 'electron';
import { join } from 'node:path';
import { initDb, getLatestScans, getFunctions, cleanDeletedFiles, saveFeedback, getScoreHistory } from './database/db.js';
import { askLLM } from './llm/llm.js';
import type { LLMContext } from './llm/llm.js';
import { scanProject } from './cli/scanner.js';
import type { FileEdge } from './cli/scanner.js';
import { loadConfig } from './config.js';
import { startWatcher } from './watcher/watcher.js';

let mainWindow: BrowserWindow | null = null;
let lastEdges: FileEdge[] = [];

function createWindow(): void {
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        webPreferences: {
            preload: join(__dirname, '../preload/index.js'),
        }
    });

    if (process.env['ELECTRON_RENDERER_URL']) {
        mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL']);
    } else {
        mainWindow.loadFile(join(__dirname, '../renderer/index.html'));
    }

    mainWindow.on('closed', () => { mainWindow = null; });
}

async function runScan(): Promise<void> {
    try {
        const config = loadConfig();
        mainWindow?.webContents.send('pulse-event', { type: 'scan-start', ts: Date.now() });
        const result = await scanProject(config.projectPath);
        lastEdges = result.edges;
        mainWindow?.webContents.send('pulse-event', { type: 'scan-done', count: result.files.length, edges: result.edges.length, ts: Date.now() });
        mainWindow?.webContents.send('scan-complete');
    } catch (err) {
        console.error('[Pulse] Scan error:', err);
        mainWindow?.webContents.send('pulse-event', { type: 'scan-error', ts: Date.now() });
    }
}

app.whenReady().then(() => {
    initDb();
    const cleaned = cleanDeletedFiles();
    if (cleaned > 0) console.log(`[Pulse] Cleaned ${cleaned} deleted file(s) from DB.`);

    ipcMain.handle('get-scans', () => {
        const config = loadConfig();
        return getLatestScans(config.projectPath);
    });
    ipcMain.handle('get-edges', () => lastEdges);
    ipcMain.handle('get-functions', (_e, filePath: string) => getFunctions(filePath));
    ipcMain.handle('save-feedback', (_e, filePath: string, action: string, score: number) => {
        saveFeedback(filePath, action, score);
    });
    ipcMain.handle('get-score-history', (_e, filePath: string) => getScoreHistory(filePath));

    ipcMain.on('ask-llm', (_e, ctx: LLMContext) => {
        askLLM(
            ctx,
            (chunk) => mainWindow?.webContents.send('llm-chunk', chunk),
            ()      => mainWindow?.webContents.send('llm-done'),
            (err)   => mainWindow?.webContents.send('llm-error', err),
        );
    });

    // 1. Ouvre la fenêtre immédiatement
    createWindow();

    // 2. Lance le scan en arrière-plan (non-bloquant)
    runScan();

    // 3. Watcher : re-scan à chaque changement de fichier
    const { emitter } = startWatcher();
    let scanTimeout: ReturnType<typeof setTimeout> | null = null;

    function sendEvent(type: string, file?: string) {
        mainWindow?.webContents.send('pulse-event', { type, file: file ? file.split('/').pop() : undefined, ts: Date.now() });
    }

    const debouncedScan = (path: string, eventType: string) => {
        sendEvent(eventType, path);
        if (scanTimeout) clearTimeout(scanTimeout);
        scanTimeout = setTimeout(() => runScan(), 1500);
    };

    emitter.on('file:changed', (p: string) => debouncedScan(p, 'changed'));
    emitter.on('file:added',   (p: string) => debouncedScan(p, 'added'));
    emitter.on('file:deleted', (p: string) => debouncedScan(p, 'deleted'));

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
