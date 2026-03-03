import http from 'node:http';

export interface CommandError {
    command: string;
    exit_code: number;
    cwd: string;
    timestamp: number;
    receivedAt: number;
}

let lastCommandError: CommandError | null = null;

export interface SocketServer {
    port: number;
    getLastCommandError: () => CommandError | null;
    stop: () => void;
}

export function startSocketServer(preferredPort = 7891): Promise<SocketServer> {
    return new Promise((resolve, reject) => {
        const server = http.createServer((req, res) => {
            if (req.method === 'POST' && req.url === '/command-error') {
                let body = '';
                req.on('data', chunk => { body += chunk; });
                req.on('end', () => {
                    try {
                        const parsed = JSON.parse(body) as {
                            command: string;
                            exit_code: number;
                            cwd: string;
                            timestamp: number;
                        };
                        lastCommandError = {
                            command:    parsed.command ?? '',
                            exit_code:  parsed.exit_code ?? 1,
                            cwd:        parsed.cwd ?? '',
                            timestamp:  parsed.timestamp ?? Date.now(),
                            receivedAt: Date.now(),
                        };
                        console.log(`[Pulse] Command error received: "${lastCommandError.command}" (exit ${lastCommandError.exit_code})`);
                    } catch (e) {
                        console.warn('[Pulse] Failed to parse command-error payload:', e);
                    }
                    res.writeHead(200);
                    res.end('OK');
                });
            } else {
                res.writeHead(404);
                res.end('Not found');
            }
        });

        const tryBind = (port: number, attemptsLeft: number) => {
            server.once('error', (err: NodeJS.ErrnoException) => {
                if (err.code === 'EADDRINUSE' && attemptsLeft > 0) {
                    console.warn(`[Pulse] Port ${port} in use, trying ${port + 1}`);
                    tryBind(port + 1, attemptsLeft - 1);
                } else {
                    reject(err);
                }
            });

            server.listen(port, '127.0.0.1', () => {
                console.log(`[Pulse] Socket server listening on port ${port}`);
                resolve({
                    port,
                    getLastCommandError: () => lastCommandError,
                    stop: () => server.close(),
                });
            });
        };

        tryBind(preferredPort, 3);
    });
}
