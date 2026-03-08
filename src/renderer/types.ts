// ── PULSE TYPES ───────────────────────────────────────────────────────────────

export interface Scan {
  filePath: string;
  globalScore: number;
  complexityScore: number;
  cognitiveComplexityScore: number;  // P2
  functionSizeScore: number;
  churnScore: number;
  depthScore: number;
  paramScore: number;
  fanIn: number;
  fanOut: number;
  language: string;
  trend: '↑' | '↓' | '↔';
  feedback: string | null;
  scannedAt: string;
  rawComplexity: number;
  rawCognitiveComplexity: number;    // P2
  rawFunctionSize: number;
  rawDepth: number;
  rawParams: number;
  rawChurn: number;
}

export interface Edge {
  from: string;
  to: string;
}

export interface FunctionDetail {
  name: string;
  start_line: number;
  line_count: number;
  cyclomatic_complexity: number;
  cognitive_complexity: number;   // P2
  parameter_count: number;
  max_depth: number;
}

export type ClipboardMode = 'error' | 'hint';

export interface TerminalErrorNotification {
  command:        string;
  exit_code:      number;
  cwd:            string;
  errorText:      string;
  errorHash:      string;
  timestamp:      number;
  id:             number;
  pastOccurrences: number;
  lastSeen:       string | null;
  mode:           ClipboardMode;
}

export type AppSettings = {
  model: string;
  baseUrl: string;
  modelGeneral: string;
  modelAnalyzer: string;
  modelCoder: string;
  modelBrainstorm: string;
  modelFast: string;
};

export type MemoryType = 'insight' | 'pattern' | 'fix' | 'warning';

export interface MemoryNote {
  id:          number;
  type:        MemoryType;
  subject:     string;
  content:     string;
  tags:        string[];
  links:       number[];
  weight:      number;
  projectPath: string;
  createdAt:   string;
  updatedAt:   string;
  dismissed:   boolean;
}

export interface IntelMessage {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

// ── WINDOW API CONTRACT ────────────────────────────────────────────────────────

declare global {
  interface Window {
    api: {
      getScans: () => Promise<Scan[]>;
      getEdges: () => Promise<Edge[]>;
      getFunctions: (filePath: string) => Promise<FunctionDetail[]>;
      saveFeedback: (filePath: string, action: string, score: number) => Promise<void>;
      getScoreHistory: (filePath: string) => Promise<{ score: number; scanned_at: string }[]>;
      getFeedbackHistory: (filePath: string) => Promise<{ action: string; created_at: string }[]>;
      askLLM: (ctx: any) => void;
      askLLMProject: (payload: { ctx: any; messages: any[] }) => void;
      abortLLM: () => void;
      onLLMChunk: (cb: (chunk: string) => void) => (() => void);
      onLLMDone: (cb: () => void) => (() => void);
      onLLMError: (cb: (err: string) => void) => (() => void);
      onScanComplete: (cb: () => void) => void;
      onEvent: (cb: (e: any) => void) => void;
      getSocketPort: () => Promise<number>;
      getProjectPath: () => Promise<string>;
      pickProject: () => Promise<string | null>;
      getProjectScoreHistory: () => Promise<{ date: string; score: number }[]>;
      onTerminalError: (cb: (ctx: TerminalErrorNotification) => void) => void;
      dismissTerminalError: () => void;
      analyzeTerminalError: (ctx: TerminalErrorNotification) => void;
      resolveTerminalError: (id: number, resolved: 1 | -1, errorContext?: { command: string; errorText: string; llmResponse?: string }) => void;
      getLlmReport: (filePath: string) => Promise<string | null>;
      getIntelMessages: () => Promise<{ role: 'user' | 'assistant'; content: string }[]>;
      saveIntelMessage: (role: 'user' | 'assistant', content: string) => Promise<void>;
      clearIntelMessages: () => Promise<void>;
      getSettings: () => Promise<AppSettings>;
      saveSettings: (s: AppSettings) => Promise<void>;
      getMemories: () => Promise<MemoryNote[]>;
      getMemoriesForFile: (filePath: string) => Promise<MemoryNote[]>;
      dismissMemory: (id: number) => Promise<void>;
      updateMemory: (id: number, content: string) => Promise<void>;
      onMemoriesUpdated: (cb: () => void) => void;
    };
  }
}
