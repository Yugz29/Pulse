import fs from 'node:fs';
import path from 'node:path';


export interface PulseConfig {
    projectPath: string;
    thresholds: {
        alert: number;
        warning: number;
    };
    ignore: string[];
}

export function loadConfig(): PulseConfig {
    const configPath = path.join(process.cwd(), 'pulse.config.json');
    const raw = fs.readFileSync(configPath, 'utf-8');
    return JSON.parse(raw) as PulseConfig;
}

export const config = loadConfig();
