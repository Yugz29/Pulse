import fs from 'node:fs';
import path from 'node:path';

export interface PulseConfig {
    projectPath: string;
    languages?: string[];
    thresholds: {
        alert: number;
        warning: number;
    };
    ignore: string[];
}

let _cached: PulseConfig | null = null;

export function loadConfig(): PulseConfig {
    if (_cached) return _cached;

    const candidates = [
        path.join(process.cwd(), 'pulse.config.json'),
        path.join(__dirname, '../../pulse.config.json'),
        path.join(__dirname, '../../../pulse.config.json'),
        path.join(path.dirname(process.execPath), 'pulse.config.json'),
    ];

    for (const p of candidates) {
        if (fs.existsSync(p)) {
            console.log(`[Pulse] Config loaded from: ${p}`);
            const raw = JSON.parse(fs.readFileSync(p, 'utf-8')) as Partial<PulseConfig>;
            _cached = {
                projectPath: raw.projectPath ?? process.cwd(),
                thresholds: {
                    alert:   raw.thresholds?.alert   ?? 50,
                    warning: raw.thresholds?.warning ?? 20,
                },
                ignore: raw.ignore ?? ['node_modules', '.git', 'dist', 'build', '.vite', 'vendor', '__pycache__'],
            };
            return _cached;
        }
    }

    throw new Error(
        `[Pulse] pulse.config.json introuvable.\nChemins essayés :\n${candidates.join('\n')}`
    );
}
