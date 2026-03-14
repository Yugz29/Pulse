import { app, BrowserWindow, ipcMain, dialog, Notification } from 'electron';
import { join } from 'node:path';
import { initDb, getLatestScans, getFunctions, cleanDeletedFiles, saveFeedback, getScoreHistory, getFeedbackHistory, saveTerminalError, getTerminalErrorHistory, updateTerminalErrorResolved, updateTerminalErrorLLM, getProjectScoreHistory, saveLlmReport, getLlmReport, getIntelMessages, saveIntelMessage, clearIntelMessages, getProjectHotspots, getComplexStableFiles } from '../../core/database/db.js';
import { initMemoryTable, runMemoryEngineOnStartup, getMemories, getMemoriesForFile, dismissMemory, updateMemoryContent, extractMemoryFromAnalysis, extractMemoryFromError, buildMemorySnapshot } from '../../core/memory/memoryEngine.js';
import { askLLM, askLLMForError, askLLMProject, abortCurrentLLM } from '../../core/llm/llm.js';
import type { LLMContext, TerminalErrorContext, ProjectContext, IntelMessage } from '../../core/llm/llm.js';
import { scanProject } from './cli/scanner.js';
import type { FileEdge } from './cli/scanner.js';
import { loadConfig } from './config.js';
import { loadSettings, saveSettings, type AppSettings } from './settings.js';
import { startWatcher } from '../../cortex/watcher/watcher.js';
import { startSocketServer } from './terminal/socketServer.js';
import { startClipboardWatcher } from './terminal/clipboardWatcher.js';
import { detectShell, generateHookForShell, getHookInstallPath } from './terminal/shellHook.js';

let mainWindow: BrowserWindow | null = null;
let lastEdges: FileEdge[] = [];
let lastTopFiles: { filePath: string; globalScore: number }[] = [];
let lastScoreSnapshot = new Map<string, number>();

function getActiveProjectPath(): string {
    const settings = loadSettings();
    if (settings.projectPath) return settings.projectPath;
    return loadConfig().projectPath;
}

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

function emit(type: string, message: string, level: 'info' | 'warn' | 'critical' | 'ok' = 'info') {
    mainWindow?.webContents.send('pulse-event', { type, message, level, ts: Date.now() });
}

const _origLog = console.log.bind(console);
console.log = (...args: unknown[]) => {
    _origLog(...args);
    const msg = args.map(a => String(a)).join(' ');
    if (msg.startsWith('[Pulse')) {
        const clean = msg.replace(/^\[Pulse[^\]]*\] /, '');
        const level = clean.includes('error') || clean.includes('failed') ? 'critical'
                    : clean.includes('warn')                              ? 'warn'
                    : clean.includes('Command error received')            ? 'warn'
                    : clean.includes('fact(s) extracted')                 ? 'ok'
                    : 'info';
        mainWindow?.webContents.send('pulse-event', { type: 'log', message: clean, level, ts: Date.now() });
    }
};

async function runScan(): Promise<void> {
    try {
        const projectPath = getActiveProjectPath();
        emit('scan-start', 'analysis triggered', 'info');

        const result = await scanProject(projectPath);
        lastEdges    = result.edges;
        lastTopFiles = result.files.slice(0, 10).map(f => ({ filePath: f.filePath, globalScore: f.globalScore }));

        const newCritical:  string[] = [];
        const degraded:     string[] = [];
        const improved:     string[] = [];
        const thresholdHit: { name: string; filePath: string; score: number }[] = [];

        for (const file of result.files) {
            const prev = lastScoreSnapshot.get(file.filePath);
            const curr = file.globalScore;
            const name = file.filePath.split('/').pop() ?? file.filePath;

            if (prev === undefined) continue;

            const delta = curr - prev;
            if (prev < 50 && curr >= 50) thresholdHit.push({ name, filePath: file.filePath, score: curr });
            else if (delta >= 8)          degraded.push(`${name} +${delta.toFixed(0)}`);
            else if (delta <= -8)         improved.push(`${name} ${delta.toFixed(0)}`);
            if (prev === 0 && curr >= 50)  newCritical.push(name);
        }

        const totalDegraded = degraded.length + thresholdHit.length;
        const totalImproved = improved.length;

        if (thresholdHit.length > 0) {
            for (const t of thresholdHit) {
                emit('threshold', `${t.name} · crossed critical threshold`, 'critical');
            }
            if (Notification.isSupported()) {
                const toNotify = thresholdHit.slice(0, 3);
                const extra    = thresholdHit.length - toNotify.length;
                const body     = [
                    ...toNotify.map(t => `${t.name}  ·  score ${t.score.toFixed(0)}`),
                    ...(extra > 0 ? [`+${extra} more`] : []),
                ].join('\n');
                const notif = new Notification({ title: '⚠ Pulse — Critical', body, silent: false });
                notif.on('click', () => {
                    if (mainWindow) {
                        if (mainWindow.isMinimized()) mainWindow.restore();
                        mainWindow.focus();
                        if (toNotify[0]) mainWindow.webContents.send('focus-file', toNotify[0]!.filePath);
                    }
                });
                notif.show();
            }
        }
        if (degraded.length > 0) emit('degraded', `${degraded.slice(0, 2).join(', ')}${degraded.length > 2 ? ` +${degraded.length - 2} more` : ''} · score up`, 'warn');
        if (improved.length > 0) emit('improved', `${improved.slice(0, 2).join(', ')}${improved.length > 2 ? ` +${improved.length - 2} more` : ''} · score down`, 'ok');

        const summary = totalDegraded > 0
            ? `${result.files.length} modules · ${totalDegraded} degraded${totalImproved > 0 ? ` · ${totalImproved} improved` : ''}`
            : totalImproved > 0 ? `${result.files.length} modules · ${totalImproved} improved`
            : `${result.files.length} modules · stable`;

        emit('scan-done', summary, totalDegraded > 0 ? 'warn' : totalImproved > 0 ? 'ok' : 'info');
        lastScoreSnapshot = new Map(result.files.map(f => [f.filePath, f.globalScore]));
        mainWindow?.webContents.send('scan-complete');
    } catch (err) {
        console.error('[Pulse] Scan error:', err);
        emit('scan-error', 'scan failed · check console', 'critical');
    }
}

app.whenReady().then(async () => {
    initDb();
    initMemoryTable();
    runMemoryEngineOnStartup(getActiveProjectPath());
    const cleaned = cleanDeletedFiles();
    if (cleaned > 0) console.log(`[Pulse] Cleaned ${cleaned} deleted file(s) from DB.`);

    const config       = loadConfig();
    const onCommandError = (cmd: import('./terminal/socketServer.js').CommandError) => {
        const projectPath = getActiveProjectPath();
        const hash        = cmd.command.trim().slice(0, 80) + ':' + cmd.exit_code;
        const errorText   = cmd.stderr || `${cmd.command} · exited with code ${cmd.exit_code}`;
        const mode        = cmd.exit_code === 130 ? 'hint' : 'error';
        const savedId     = saveTerminalError({
            command: cmd.command, exit_code: cmd.exit_code, error_hash: hash,
            error_text: errorText, cwd: cmd.cwd, project_path: projectPath,
        });
        const pastHistory = getTerminalErrorHistory(hash, projectPath);
        mainWindow?.webContents.send('terminal-error', {
            command: cmd.command, exit_code: cmd.exit_code, cwd: cmd.cwd,
            errorText, errorHash: hash, timestamp: Date.now(), mode, id: savedId,
            pastOccurrences: pastHistory.length + 1, lastSeen: pastHistory[0]?.created_at ?? null,
        });
    };

    const socketServer = await startSocketServer(config.socketPort ?? 7891, onCommandError);
    const clipWatcher  = startClipboardWatcher(
        () => socketServer.getLastCommandError(),
        (ctx: TerminalErrorContext) => {
            const projectPath  = getActiveProjectPath();
            const pastHistory  = getTerminalErrorHistory(ctx.errorHash, projectPath);
            const savedId      = saveTerminalError({
                command: ctx.command, exit_code: ctx.exit_code, error_hash: ctx.errorHash,
                error_text: ctx.errorText, cwd: ctx.cwd, project_path: projectPath,
            });
            mainWindow?.webContents.send('terminal-error', {
                ...ctx, id: savedId, pastOccurrences: pastHistory.length + 1,
                lastSeen: pastHistory[0]?.created_at ?? null,
            });
        },
    );

    ipcMain.handle('get-scans', () => getLatestScans(getActiveProjectPath()));
    ipcMain.handle('get-project-path', () => getActiveProjectPath());
    ipcMain.handle('pick-project', async () => {
        const result = await dialog.showOpenDialog(mainWindow!, { properties: ['openDirectory'], title: 'Select project folder' });
        if (result.canceled || !result.filePaths[0]) return null;
        const newPath = result.filePaths[0];
        const current = loadSettings();
        saveSettings({ ...current, projectPath: newPath } as AppSettings);
        lastScoreSnapshot = new Map();
        emit('project-switch', `switched · ${newPath.split('/').pop()}`, 'info');
        const w = (global as any).__pulseWatcher;
        if (w) await w.restart(newPath);
        runScan();
        return newPath;
    });
    ipcMain.handle('get-edges', () => lastEdges);
    ipcMain.handle('get-functions', (_e, filePath: string) => getFunctions(filePath));
    ipcMain.handle('save-feedback', (_e, filePath: string, action: string, score: number) => { saveFeedback(filePath, action, score); });
    ipcMain.handle('get-score-history', (_e, filePath: string) => getScoreHistory(filePath));
    ipcMain.handle('get-feedback-history', (_e, filePath: string) => getFeedbackHistory(filePath));
    ipcMain.handle('get-socket-port', () => socketServer.port);
    ipcMain.handle('get-shell-hook', () => {
        const shell    = detectShell();
        const snippet  = generateHookForShell(shell, { port: socketServer.port });
        const installPath = getHookInstallPath(shell);
        return { shell, snippet, installPath };
    });
    ipcMain.handle('get-terminal-error-history', (_e, hash: string, projectPath: string) => getTerminalErrorHistory(hash, projectPath));
    ipcMain.handle('get-project-score-history', () => getProjectScoreHistory(getActiveProjectPath()));
    ipcMain.handle('get-settings', () => loadSettings());
    ipcMain.handle('save-settings', (_e, s) => saveSettings(s));
    ipcMain.handle('test-connection', async (_e, url: string): Promise<{ ok: boolean; error?: string }> => {
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 4000);
            const res = await fetch(url, { signal: controller.signal });
            clearTimeout(timer);
            return { ok: res.ok || res.status < 500 };
        } catch (err) {
            return { ok: false, error: err instanceof Error ? err.message : String(err) };
        }
    });
    ipcMain.handle('get-available-models', async (_e, payload: { url: string; serverType: 'ollama' | 'perspective' }): Promise<{ models: string[]; error?: string }> => {
        try {
            const base = payload.url.replace(/\/$/, '');
            const endpoint = payload.serverType === 'ollama' ? `${base}/api/tags` : `${base}/v1/models`;
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 5000);
            const res = await fetch(endpoint, { signal: controller.signal });
            clearTimeout(timer);
            if (!res.ok) return { models: [], error: `HTTP ${res.status}` };
            const data = await res.json() as any;
            const models: string[] = payload.serverType === 'ollama'
                ? (data.models ?? []).map((m: any) => m.name as string)
                : (data.data ?? []).map((m: any) => m.id as string);
            return { models };
        } catch (err) {
            return { models: [], error: err instanceof Error ? err.message : String(err) };
        }
    });

    ipcMain.handle('get-memories', () => getMemories(getActiveProjectPath()));
    ipcMain.handle('get-memories-for-file', (_e, filePath: string) => getMemoriesForFile(filePath, getActiveProjectPath()));
    ipcMain.handle('dismiss-memory', (_e, id: number) => dismissMemory(id));
    ipcMain.handle('update-memory', (_e, id: number, content: string) => updateMemoryContent(id, content));
    ipcMain.handle('get-hotspots', () => getProjectHotspots(getActiveProjectPath()));
    ipcMain.handle('get-complex-stable', () => getComplexStableFiles(getActiveProjectPath()));
    ipcMain.handle('get-intel-messages', () => getIntelMessages(getActiveProjectPath()));
    ipcMain.handle('save-intel-message', (_e, role: 'user' | 'assistant', content: string) => saveIntelMessage(getActiveProjectPath(), role, content));
    ipcMain.handle('clear-intel-messages', () => clearIntelMessages(getActiveProjectPath()));
    ipcMain.handle('get-llm-report', (_e, filePath: string) => getLlmReport(filePath));

    ipcMain.on('ask-llm', (_e, ctx: LLMContext) => {
        let accumulated = '';
        const projectPath = getActiveProjectPath();
        const memSnap = buildMemorySnapshot(projectPath, ctx.filePath);
        askLLM(ctx,
            (chunk) => { accumulated += chunk; mainWindow?.webContents.send('llm-chunk', chunk); },
            () => {
                mainWindow?.webContents.send('llm-done');
                if (accumulated) {
                    saveLlmReport(ctx.filePath, accumulated);
                    extractMemoryFromAnalysis({ filePath: ctx.filePath, analysis: accumulated, projectPath })
                        .then(() => { mainWindow?.webContents.send('memories-updated'); })
                        .catch(() => { });
                }
            },
            (err) => mainWindow?.webContents.send('llm-error', err),
            memSnap || undefined,
        );
    });

    ipcMain.on('analyze-terminal-error', (_e, ctx: TerminalErrorContext & { id: number; pastOccurrences: number }) => {
        let llmAccumulated = '';
        askLLMForError(ctx, lastTopFiles.slice(0, 5), ctx.pastOccurrences,
            (chunk) => { llmAccumulated += chunk; mainWindow?.webContents.send('llm-chunk', chunk); },
            () => { mainWindow?.webContents.send('llm-done'); if (ctx.id) updateTerminalErrorLLM(ctx.id, llmAccumulated); },
            (err) => mainWindow?.webContents.send('llm-error', err),
        );
    });

    ipcMain.on('resolve-terminal-error', (_e, id: number, resolved: 1 | -1, errorContext?: { command: string; errorText: string; llmResponse?: string }) => {
        updateTerminalErrorResolved(id, resolved);
        if (resolved === 1 && errorContext?.llmResponse) {
            extractMemoryFromError({ command: errorContext.command, errorText: errorContext.errorText, llmAnalysis: errorContext.llmResponse, projectPath: getActiveProjectPath() })
                .then(() => { mainWindow?.webContents.send('memories-updated'); })
                .catch(() => { });
        }
    });

    ipcMain.on('ask-llm-project', (_e, payload: { ctx: ProjectContext; messages: IntelMessage[] }) => {
        askLLMProject(payload.ctx, payload.messages,
            (chunk) => mainWindow?.webContents.send('llm-chunk', chunk),
            ()      => mainWindow?.webContents.send('llm-done'),
            (err)   => mainWindow?.webContents.send('llm-error', err),
        );
    });

    ipcMain.on('abort-llm', () => abortCurrentLLM());

    createWindow();
    runScan();

    const watcher = startWatcher();
    let scanTimeout: ReturnType<typeof setTimeout> | null = null;

    const debouncedScan = (path: string, eventType: string) => {
        const file = path.split('/').pop();
        mainWindow?.webContents.send('pulse-event', { type: eventType, file, message: `${file} · ${eventType}`, level: 'info', ts: Date.now() });
        if (scanTimeout) clearTimeout(scanTimeout);
        scanTimeout = setTimeout(() => runScan(), 1500);
    };

    watcher.emitter.on('file:changed', (p: string) => debouncedScan(p, 'changed'));
    watcher.emitter.on('file:added',   (p: string) => debouncedScan(p, 'added'));
    watcher.emitter.on('file:deleted', (p: string) => debouncedScan(p, 'deleted'));
    watcher.emitter.on('watcher:restarted', (newPath: string) => {
        emit('watcher-restarted', `watching · ${newPath.split('/').pop()}`, 'info');
    });

    (global as any).__pulseWatcher = watcher;

    app.on('before-quit', async () => {
        socketServer.stop();
        clipWatcher.stop();
        await watcher.close();
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
