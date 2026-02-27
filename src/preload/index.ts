import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('api', {
    getScans: () => ipcRenderer.invoke('get-scans'),
});
