import { clipboard } from 'electron';
import type { CommandError } from './socketServer.js';

export interface TerminalErrorContext {
    command: string;
    exit_code: number;
    cwd: string;
    errorText: string;
    errorHash: string;
    timestamp: number;
}

const ERROR_PATTERNS: RegExp[] = [
    // Node / TS
    /Error:/,
    /error TS\d+/,
    /ENOENT/,
    /EACCES/,
    /ECONNREFUSED/,
    /EADDRINUSE/,
    /npm ERR!/,
    /TypeError/,
    /SyntaxError/,
    /ReferenceError/,
    /RangeError/,
    /Cannot find module/,
    /Module not found/,
    // Unix / shell
    /No such file or directory/,
    /Permission denied/,
    /command not found/,
    /not found:/,
    /cannot open/i,
    /Segmentation fault/,
    // Python
    /Traceback \(most recent call last\)/,
    /ModuleNotFoundError/,
    /ImportError/,
    /AssertionError/,
    /IndentationError/,
    // Build tools
    /Build failed/i,
    /failed to compile/i,
    /Compilation failed/i,
    /failed with exit code/i,
    /exited with code [^0]/,
    /FAILED/,
    // Rust / Go / other
    /error\[E\d+\]/,
    /fatal:/i,
    /panic:/i,
];

const CORRELATION_WINDOW_MS = 30_000;
const POLL_INTERVAL_MS      = 600;

function makeHash(text: string): string {
    return text.trim().slice(0, 80);
}

function isErrorText(text: string): boolean {
    if (text.trim().length < 30) return false;
    return ERROR_PATTERNS.some(p => p.test(text));
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

        if (!isErrorText(text)) return;

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
        onError({
            command:   inWindow ? cmdError!.command : '(commande inconnue)',
            exit_code: inWindow ? cmdError!.exit_code : 1,
            cwd:       inWindow ? cmdError!.cwd : '',
            errorText: text,
            errorHash: hash,
            timestamp: now,
        });
    }, POLL_INTERVAL_MS);

    return {
        stop: () => clearInterval(timer),
    };
}
