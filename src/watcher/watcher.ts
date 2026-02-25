import chokidar from 'chokidar';
import { EventEmitter } from 'node:events';
import { config } from '../config.js';

export function startWatcher() {
    const emitter = new EventEmitter();

    const watcher = chokidar.watch(config.projectPath, {
        ignored: (filePath: string) => {
            const parts = filePath.split('/');
            return parts.some(part => config.ignore.includes(part));
        },
        ignoreInitial: true
    }).on('error', (err) => emitter.emit('error', err));

    watcher.on('add', (path) => {
        emitter.emit('file:added', path);
    });

    watcher.on('change', (path) => {
        if (!(path.endsWith('.js') || path.endsWith('.ts'))) return;
        emitter.emit('file:changed', path);
    });

    watcher.on('unlink', (path) => {
        emitter.emit('file:deleted', path);
    });

    return {
        emitter,
        pause: () => watcher.unwatch(config.projectPath),
        resume: () => watcher.add(config.projectPath),
    };
}
