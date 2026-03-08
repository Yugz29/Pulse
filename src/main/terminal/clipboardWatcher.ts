import { clipboard } from 'electron';
import type { CommandError } from './socketServer.js';

export type ClipboardMode = 'error' | 'hint';

export interface TerminalErrorContext {
    command:   string;
    exit_code: number;
    cwd:       string;
    errorText: string;
    errorHash: string;
    timestamp: number;
    mode:      ClipboardMode; // 'error' → banner rouge | 'hint' → pastille bleue
}

// Patterns de signal fort — détection directe sans ambiguïté
const STRONG_PATTERNS: RegExp[] = [
    /Error:/i, /error TS\d+/, /TypeError/, /SyntaxError/, /ReferenceError/, /RangeError/,
    /ENOENT/, /EACCES/, /ECONNREFUSED/, /EADDRINUSE/,
    /npm ERR!/, /Cannot find module/, /Module not found/,
    /No such file or directory/, /Permission denied/, /command not found/,
    /Traceback \(most recent call last\)/,
    /ModuleNotFoundError/, /ImportError/, /AssertionError/, /IndentationError/,
    /Build failed/i, /failed to compile/i, /Compilation failed/i,
    /failed with exit code/i, /exited with code [^0]/, /FAILED/,
    /error\[E\d+\]/, /fatal:/i, /panic:/i,
    /warning:/i, /deprecated/i,
    // Build tools — prefixes de warning/erreur courants
    /^\(!\)/m,           // Vite / Rollup warning
    /^\[warn\]/im,       // divers bundlers
    /^\[error\]/im,
    /DeprecationWarning/i,
    /ExperimentalWarning/i,
];

// Détection large — ressemble à une sortie terminal même sans mot-clé connu
// Heuristiques : multiligne + contient des patterns de terminal (prompt, path, stack)
const TERMINAL_HEURISTICS: RegExp[] = [
    /^\s+at\s+/m,              // stack trace JS (  at Function.xxx)
    /File ".+", line \d+/,     // stack trace Python
    /\^+$/m,                   // pointeur d'erreur (^^^)
    /-->\s+\S+:\d+:\d+/,       // pointeur Rust/TS
    /\d+\s*\|\s*.+/m,          // contexte de ligne numérotée
    /at\s+\S+:\d+:\d+/,        // localisation fichier:ligne:col
    /\/[\w./-]+\.\w{2,5}:\d+/, // chemin absolu avec numéro de ligne (/foo/bar.ts:42)
    /is dynamically imported/,  // Vite bundling warnings
    /chunk|bundle|build/i,      // messages de build génériques multiligne
];

const CORRELATION_WINDOW_MS = 30_000;
const POLL_INTERVAL_MS      = 600;

function makeHash(text: string): string {
    return text.trim().slice(0, 80);
}

// Patterns qui indiquent une vraie erreur (mode 'error' → banner rouge)
const ERROR_STRONG: RegExp[] = [
    /Error:/i, /error TS\d+/, /TypeError/, /SyntaxError/, /ReferenceError/, /RangeError/,
    /ENOENT/, /EACCES/, /ECONNREFUSED/, /EADDRINUSE/,
    /npm ERR!/, /Cannot find module/, /Module not found/,
    /No such file or directory/, /Permission denied/, /command not found/,
    /Traceback \(most recent call last\)/,
    /ModuleNotFoundError/, /ImportError/, /AssertionError/, /IndentationError/,
    /Build failed/i, /failed to compile/i, /Compilation failed/i,
    /failed with exit code/i, /exited with code [^0]/, /FAILED/,
    /error\[E\d+\]/, /fatal:/i, /panic:/i,
];

function classifyContent(text: string): ClipboardMode {
    // Signal d'erreur fort → mode error
    if (ERROR_STRONG.some(p => p.test(text))) return 'error';
    // Exit code non-zéro connu → error
    if (/exited with code [^0]/.test(text))   return 'error';
    // Tout le reste détecté → hint (warning, build output, logs...)
    return 'hint';
}

// Patterns qui indiquent une origine terminal (prompt, commande, sortie)
const TERMINAL_ORIGIN: RegExp[] = [
    /^%\s/m,                        // prompt zsh (% commande)
    /^\$\s/m,                        // prompt bash
    /@[\w-]+[:\s]/,                  // user@machine:
    /&&|\|\||>>|2>&1/,               // opérateurs shell
    /^-{1,2}[a-z]/m,                 // flags CLI (-v, --help)
    /\/Users\/|~\//,                 // chemins macOS
    /npm|yarn|pnpm|npx|git|brew/,    // outils dev courants
    /\d+ms|\d+s elapsed/,            // durées de build
];

function isTerminalContent(text: string): boolean {
    const trimmed = text.trim();

    // Trop court pour être utile
    if (trimmed.length < 20) return false;

    // Signal fort : mot-clé d'erreur ou warning connu
    if (STRONG_PATTERNS.some(p => p.test(trimmed))) return true;

    // Signal heuristique : ressemble à une sortie terminal (multiligne + pattern)
    const hasMultipleLines = trimmed.includes('\n');
    if (hasMultipleLines && TERMINAL_HEURISTICS.some(p => p.test(trimmed))) return true;

    // Origine terminal détectée — même sans erreur → mode hint
    if (TERMINAL_ORIGIN.some(p => p.test(trimmed))) return true;

    return false;
}

export interface ClipboardWatcher {
    stop: () => void;
}

export function startClipboardWatcher(
    getLastCommandError: () => CommandError | null,
    onError: (ctx: TerminalErrorContext) => void,
): ClipboardWatcher {
    let lastClipboardText = clipboard.readText();
    let lastNotifiedHash  = '';

    const timer = setInterval(() => {
        const text = clipboard.readText();

        if (text === lastClipboardText) return;
        lastClipboardText = text;

        if (!isTerminalContent(text)) return;

        const hash = makeHash(text);
        if (hash === lastNotifiedHash) return;

        const cmdError = getLastCommandError();
        const now      = Date.now();

        // Corrélation : le hook a-t-il tiré récemment (< 30s) ?
        const inWindow = cmdError !== null && (now - cmdError.receivedAt) < CORRELATION_WINDOW_MS;

        // On fire toujours quand le clipboard contient une erreur :
        // - si le hook a tiré récemment → on enrichit avec la commande connue
        // - sinon (hook non configuré ou stale) → commande inconnue, mais on notifie quand même
        lastNotifiedHash = hash;

        // Priorité au stderr capturé par le hook (plus propre que le clipboard)
        const hookStderr = inWindow ? (cmdError!.stderr ?? '') : '';
        const errorText  = hookStderr.length > text.length ? hookStderr : text;

        // Mode : erreur forte → banner rouge | warning/output → pastille bleue
        const mode = inWindow && cmdError!.exit_code !== 0
            ? 'error'
            : classifyContent(errorText);

        onError({
            command:   inWindow ? cmdError!.command : '(commande inconnue)',
            exit_code: inWindow ? cmdError!.exit_code : 1,
            cwd:       inWindow ? cmdError!.cwd : '',
            errorText,
            errorHash: hash,
            timestamp: now,
            mode,
        });
    }, POLL_INTERVAL_MS);

    return {
        stop: () => clearInterval(timer),
    };
}
