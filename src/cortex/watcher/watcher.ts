import chokidar, { type FSWatcher } from 'chokidar';
import { EventEmitter } from 'node:events';
import { loadConfig } from '../../app/main/config.js';

const SUPPORTED = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.py'];

export function startWatcher() {
    const config  = loadConfig();
    const emitter = new EventEmitter();

    let currentPath    = config.projectPath;
    let currentIgnore  = config.ignore;
    let watcher: FSWatcher | null = null;

    function attachListeners(w: FSWatcher) {
        w.on('add',    (path) => { if (SUPPORTED.some(ext => path.endsWith(ext))) emitter.emit('file:added',   path); });
        w.on('change', (path) => { if (SUPPORTED.some(ext => path.endsWith(ext))) emitter.emit('file:changed', path); });
        w.on('unlink', (path) => emitter.emit('file:deleted', path));
        w.on('error',  (err)  => emitter.emit('error', err));
    }

    function createWatcher(projectPath: string, ignore: string[]): FSWatcher {
        return chokidar.watch(projectPath, {
            ignored: (filePath: string) => {
                const parts = filePath.split('/');
                return parts.some(part => ignore.includes(part));
            },
            ignoreInitial: true,
        });
    }

    watcher = createWatcher(currentPath, currentIgnore);
    attachListeners(watcher);

    async function restart(newPath: string): Promise<void> {
        if (watcher) {
            await watcher.close();
            watcher = null;
        }
        const cfg      = loadConfig();
        currentPath   = newPath;
        currentIgnore = cfg.ignore;
        watcher = createWatcher(currentPath, currentIgnore);
        attachListeners(watcher);
        emitter.emit('watcher:restarted', newPath);
    }

    return {
        emitter,
        restart,
        getCurrentPath: () => currentPath,
        close: async () => { if (watcher) await watcher.close(); },
    };
}
