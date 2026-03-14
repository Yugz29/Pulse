import { app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';

export interface AppSettings {
    // Modèle legacy (conservé pour rétrocompatibilité)
    model: string;
    baseUrl: string;
    projectPath?: string;
    // Modèle général : utilisé pour tous les rôles non définis
    modelGeneral: string;
    // Overrides par rôle (optionnels — fallback sur modelGeneral si vide)
    modelAnalyzer?: string;
    modelCoder?: string;
    modelBrainstorm?: string;
    modelFast?: string;
    // URL overrides par rôle (ex: Perspective Server sur 11435)
    baseUrlFast?:     string;
    baseUrlAnalyzer?: string;
    // Serveur secondaire (Perspective / Apple Intelligence)
    perspectiveUrl?:  string;
    // Quel serveur utiliser pour chaque rôle ('primary' = baseUrl, 'perspective' = perspectiveUrl)
    serverForRole?:   Partial<Record<'analyzer' | 'coder' | 'brainstorm' | 'fast', 'primary' | 'perspective'>>;
}

const DEFAULTS: AppSettings = {
    model:        'pulse-qwen3',
    baseUrl:      'http://localhost:11434',
    modelGeneral: 'pulse-qwen3',  // modèle général par défaut
    // overrides vides = tout passe par modelGeneral
    modelAnalyzer:   '',
    modelCoder:      '',
    modelBrainstorm: '',
    modelFast:       '',
    baseUrlFast:     '',
    baseUrlAnalyzer: '',
    perspectiveUrl:  '',
    serverForRole:   {},
};

function getSettingsPath(): string {
    return path.join(app.getPath('userData'), 'settings.json');
}

export function loadSettings(): AppSettings {
    try {
        const raw = fs.readFileSync(getSettingsPath(), 'utf-8');
        return { ...DEFAULTS, ...JSON.parse(raw) };
    } catch {
        return { ...DEFAULTS };
    }
}

export function saveSettings(s: AppSettings): void {
    const p = getSettingsPath();
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, JSON.stringify(s, null, 2), 'utf-8');
}
