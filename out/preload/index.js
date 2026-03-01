"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("api", {
  getScans: () => electron.ipcRenderer.invoke("get-scans"),
  getEdges: () => electron.ipcRenderer.invoke("get-edges"),
  getFunctions: (filePath) => electron.ipcRenderer.invoke("get-functions", filePath),
  saveFeedback: (filePath, action, score) => electron.ipcRenderer.invoke("save-feedback", filePath, action, score),
  getScoreHistory: (filePath) => electron.ipcRenderer.invoke("get-score-history", filePath),
  onScanComplete: (cb) => {
    electron.ipcRenderer.removeAllListeners("scan-complete");
    electron.ipcRenderer.on("scan-complete", cb);
  },
  onEvent: (cb) => {
    electron.ipcRenderer.removeAllListeners("pulse-event");
    electron.ipcRenderer.on("pulse-event", (_ipc, e) => cb(e));
  }
});
