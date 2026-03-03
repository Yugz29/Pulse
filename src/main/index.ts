import { app, BrowserWindow, ipcMain } from 'electron';
import { join } from 'node:path';
import { initDb, getLatestScans, getFunctions, cleanDeletedFiles, saveFeedback, getScoreHistory, getFeedbackHistory, saveTerminalError, getTerminalErrorHistory, updateTerminalErrorResolved, updateTerminalErrorLLM } from './database/db.js';
import { askLLM, askLLMForError } from './llm/llm.js';
import type { LLMContext, TerminalErrorContext } from './llm/llm.js';
import { scanProject } from './cli/scanner.js';
import type { FileEdge } from './cli/scanner.js';
import { loadConfig } from './config.js';
import { startWatcher } from './watcher/watcher.js';
import { startSocketServer } from './terminal/socketServer.js';
import { startClipboardWatcher } from './terminal/clipboardWatcher.js';

let mainWindow: BrowserWindow | null = null;
let lastEdges: FileEdge[] = [];
let lastTopFiles: { filePath: string; globalScore: number }[] = [];

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
        lastEdges    = result.edges;
        lastTopFiles = result.files
            .slice(0, 10)
            .map(f => ({ filePath: f.filePath, globalScore: f.globalScore }));
        mainWindow?.webContents.send('pulse-event', { type: 'scan-done', count: result.files.length, edges: result.edges.length, ts: Date.now() });
        mainWindow?.webContents.send('scan-complete');
    } catch (err) {
        console.error('[Pulse] Scan error:', err);
        mainWindow?.webContents.send('pulse-event', { type: 'scan-error', ts: Date.now() });
    }
}

app.whenReady().then(async () => {
    initDb();
    const cleaned = cleanDeletedFiles();
    if (cleaned > 0) console.log(`[Pulse] Cleaned ${cleaned} deleted file(s) from DB.`);

    // ── Socket server + clipboard watcher ──
    const config       = loadConfig();
    const socketServer = await startSocketServer(config.socketPort ?? 7891);
    const clipWatcher  = startClipboardWatcher(
        () => socketServer.getLastCommandError(),
        (ctx: TerminalErrorContext) => {
            const projectPath  = loadConfig().projectPath;
            const pastHistory  = getTerminalErrorHistory(ctx.errorHash, projectPath);
            const savedId      = saveTerminalError({
                command:      ctx.command,
                exit_code:    ctx.exit_code,
                error_hash:   ctx.errorHash,
                error_text:   ctx.errorText,
                cwd:          ctx.cwd,
                project_path: projectPath,
            });
            mainWindow?.webContents.send('terminal-error', {
                ...ctx,
                id:              savedId,
                pastOccurrences: pastHistory.length + 1,
                lastSeen:        pastHistory[0]?.created_at ?? null,
            });
        },
    );

    // ── IPC handlers ──
    ipcMain.handle('get-scans', () => {
        const cfg = loadConfig();
        return getLatestScans(cfg.projectPath);
    });
    ipcMain.handle('get-edges', () => lastEdges);
    ipcMain.handle('get-functions', (_e, filePath: string) => getFunctions(filePath));
    ipcMain.handle('save-feedback', (_e, filePath: string, action: string, score: number) => {
        saveFeedback(filePath, action, score);
    });
    ipcMain.handle('get-score-history', (_e, filePath: string) => getScoreHistory(filePath));
    ipcMain.handle('get-feedback-history', (_e, filePath: string) => getFeedbackHistory(filePath));
    ipcMain.handle('get-socket-port', () => socketServer.port);
    ipcMain.handle('get-terminal-error-history', (_e, hash: string, projectPath: string) =>
        getTerminalErrorHistory(hash, projectPath),
    );

    ipcMain.on('ask-llm', (_e, ctx: LLMContext) => {
        askLLM(
            ctx,
            (chunk) => mainWindow?.webContents.send('llm-chunk', chunk),
            ()      => mainWindow?.webContents.send('llm-done'),
            (err)   => mainWindow?.webContents.send('llm-error', err),
        );
    });

    ipcMain.on('analyze-terminal-error', (_e, ctx: TerminalErrorContext & { id: number; pastOccurrences: number }) => {
        let llmAccumulated = '';
        askLLMForError(
            ctx,
            lastTopFiles.slice(0, 5),
            ctx.pastOccurrences,
            (chunk) => {
                llmAccumulated += chunk;
                mainWindow?.webContents.send('llm-chunk', chunk);
            },
            () => {
                mainWindow?.webContents.send('llm-done');
                if (ctx.id) updateTerminalErrorLLM(ctx.id, llmAccumulated);
            },
            (err) => mainWindow?.webContents.send('llm-error', err),
        );
    });

    ipcMain.on('resolve-terminal-error', (_e, id: number, resolved: 1 | -1) => {
        updateTerminalErrorResolved(id, resolved);
    });

    // 1. Ouvre la fenêtre immédiatement
    createWindow();

    // Cleanup on quit
    app.on('before-quit', () => {
        socketServer.stop();
        clipWatcher.stop();
    });

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
