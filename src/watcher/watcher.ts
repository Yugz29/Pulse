import chokidar from 'chokidar';
import { EventEmitter } from 'node:events';

export function startWatcher() {
    const emitter = new EventEmitter();

    const watcher = chokidar.watch('/Users/yugz/Projets/DevNote/', {
        ignored: /node_modules|\.git|dist|build|\.vscode|\.idea|\.DS_Store|\.log/,
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
        pause: () => watcher.unwatch('**/*'),
        resume: () => watcher.add('/Users/yugz/Projets/DevNote/'),
    };
}
