import { useState, useMemo } from 'react';
import { marked } from 'marked';
import type { TerminalErrorNotification } from '../types';

export interface UseTerminalLLMReturn {
    terminalError:      TerminalErrorNotification | null;
    terminalErrorMode:  'error' | 'hint';
    terminalLlm:        string;
    terminalLlmLoading: boolean;
    terminalLlmHtml:    string;
    setTerminalError:   (e: TerminalErrorNotification | null) => void;
    handleAnalyze:      () => void;
    handleDismiss:      () => void;
    handleResolve:      () => void;
    clearLlm:           () => void;
}

export function useTerminalLLM(): UseTerminalLLMReturn {
    const [terminalError,      setTerminalError]      = useState<TerminalErrorNotification | null>(null);
    const [terminalErrorMode,  setTerminalErrorMode]  = useState<'error' | 'hint'>('error');
    const [terminalLlm,        setTerminalLlm]        = useState('');
    const [terminalLlmLoading, setTerminalLlmLoading] = useState(false);

    const terminalLlmHtml = useMemo(() => {
        if (!terminalLlm) return '';
        return marked(terminalLlm) as string;
    }, [terminalLlm]);

    function handleAnalyze() {
        if (!terminalError) return;
        setTerminalErrorMode(terminalError.mode ?? 'error');
        setTerminalLlm('');
        setTerminalLlmLoading(true);

        const offChunk = window.api.onLLMChunk(chunk => setTerminalLlm(prev => prev + chunk));
        const offDone  = window.api.onLLMDone(() => {
            setTerminalLlmLoading(false);
            offChunk(); offDone(); offError();
        });
        const offError = window.api.onLLMError(err => {
            setTerminalLlm(`Error: ${err}`);
            setTerminalLlmLoading(false);
            offChunk(); offDone(); offError();
        });

        window.api.analyzeTerminalError(terminalError);
        setTerminalError(null);
    }

    function handleDismiss() {
        window.api.dismissTerminalError();
        setTerminalError(null);
    }

    function handleResolve() {
        if (!terminalError) return;
        window.api.resolveTerminalError(terminalError.id, 1, {
            command:     terminalError.command,
            errorText:   terminalError.errorText,
            llmResponse: terminalLlm || undefined,
        });
        setTerminalError(null);
        setTerminalLlm('');
    }

    function clearLlm() {
        setTerminalLlm('');
        setTerminalLlmLoading(false);
    }

    return {
        terminalError,
        terminalErrorMode,
        terminalLlm,
        terminalLlmLoading,
        terminalLlmHtml,
        setTerminalError,
        handleAnalyze,
        handleDismiss,
        handleResolve,
        clearLlm,
    };
}
