import chokidar from 'chokidar';


export function startWatcher() {
    const watcher = chokidar.watch('.');

    watcher.on('add', (path) => {
        console.log('Nouveau fichier :', path);
    });

    watcher.on('change', (path) => {
        console.log('Fichier modifié :', path);
    });

    watcher.on('unlink', (path) => {
        console.log('Fichier supprimé :', path);
    });
}
