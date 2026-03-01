"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("api", {
  getScans: () => electron.ipcRenderer.invoke("get-scans"),
  getEdges: () => electron.ipcRenderer.invoke("get-edges"),
  getFunctions: (filePath) => electron.ipcRenderer.invoke("get-functions", filePath),
  saveFeedback: (filePath, action, score) => electron.ipcRenderer.invoke("save-feedback", filePath, action, score),
  getScoreHistory: (filePath) => electron.ipcRenderer.invoke("get-score-history", filePath),
  getFeedbackHistory: (filePath) => electron.ipcRenderer.invoke("get-feedback-history", filePath),
  askLLM: (ctx) => electron.ipcRenderer.send("ask-llm", ctx),
  onLLMChunk: (cb) => {
    electron.ipcRenderer.removeAllListeners("llm-chunk");
    electron.ipcRenderer.on("llm-chunk", (_ipc, chunk) => cb(chunk));
  },
  onLLMDone: (cb) => {
    electron.ipcRenderer.removeAllListeners("llm-done");
    electron.ipcRenderer.on("llm-done", cb);
  },
  onLLMError: (cb) => {
    electron.ipcRenderer.removeAllListeners("llm-error");
    electron.ipcRenderer.on("llm-error", (_ipc, err) => cb(err));
  },
  onScanComplete: (cb) => {
    electron.ipcRenderer.removeAllListeners("scan-complete");
    electron.ipcRenderer.on("scan-complete", cb);
  },
  onEvent: (cb) => {
    electron.ipcRenderer.removeAllListeners("pulse-event");
    electron.ipcRenderer.on("pulse-event", (_ipc, e) => cb(e));
  }
});
