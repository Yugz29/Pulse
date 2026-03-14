import { describe, it, expect } from 'vitest';
import { detectFileType } from '../src/main/risk-score/referenceBaselines.js';

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — noms exacts (etape 1)', () => {

    it('index.ts → entrypoint', () => {
        expect(detectFileType('/src/index.ts')).toBe('entrypoint');
    });

    it('index.tsx → entrypoint', () => {
        expect(detectFileType('/src/index.tsx')).toBe('entrypoint');
    });

    it('main.ts → entrypoint', () => {
        expect(detectFileType('/src/main/main.ts')).toBe('entrypoint');
    });

    it('app.tsx → entrypoint', () => {
        expect(detectFileType('/src/renderer/app.tsx')).toBe('entrypoint');
    });

    it('types.ts → config', () => {
        expect(detectFileType('/src/main/types.ts')).toBe('config');
    });

    it('settings.ts → config', () => {
        expect(detectFileType('/src/main/settings.ts')).toBe('config');
    });

    it('constants.ts → config', () => {
        expect(detectFileType('/src/constants.ts')).toBe('config');
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — prefixe config (etape 2)', () => {

    it('config.ts → config', () => {
        expect(detectFileType('/src/config.ts')).toBe('config');
    });

    it('config.db.ts → config (prefixe)', () => {
        expect(detectFileType('/src/config.db.ts')).toBe('config');
    });

    it('configLoader.ts → config (commence par config)', () => {
        expect(detectFileType('/src/configLoader.ts')).toBe('config');
    });

    it('vite.config.ts → config (termine par .config.ts)', () => {
        expect(detectFileType('/vite.config.ts')).toBe('config');
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — fragments dans le nom (etape 3)', () => {

    it('parser.utils.ts → parser (parser avant utility dans NAME_FRAGMENTS)', () => {
        // "parser" est liste avant "util" dans NAME_FRAGMENTS → remporte la priorite
        expect(detectFileType('/src/parser.utils.ts')).toBe('parser');
    });

    it('lexer.ts → parser', () => {
        expect(detectFileType('/src/lexer.ts')).toBe('parser');
    });

    it('analyzer.ts → parser', () => {
        expect(detectFileType('/src/main/analyzer.ts')).toBe('parser');
    });

    it('scanner.ts → service (fragment "scanner")', () => {
        expect(detectFileType('/src/main/scanner.ts')).toBe('service');
    });

    it('churn.ts → service', () => {
        expect(detectFileType('/src/main/analyzer/churn.ts')).toBe('service');
    });

    it('dbManager.ts → service (fragment "manager")', () => {
        expect(detectFileType('/src/dbManager.ts')).toBe('service');
    });

    it('utils.ts → utility (fragment "util")', () => {
        expect(detectFileType('/src/utils.ts')).toBe('utility');
    });

    it('formatHelper.ts → utility (fragment "helper")', () => {
        expect(detectFileType('/src/formatHelper.ts')).toBe('utility');
    });

    it('referenceBaselines.ts → config (fragment "reference")', () => {
        expect(detectFileType('/src/risk-score/referenceBaselines.ts')).toBe('config');
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — dossier shared ou lib (etape 4)', () => {

    it('fichier dans /shared/ → utility', () => {
        expect(detectFileType('/src/shared/bridge.ts')).toBe('utility');
    });

    it('fichier dans /lib/ → utility', () => {
        expect(detectFileType('/src/lib/core.ts')).toBe('utility');
    });

    it('le dossier shared ne surclasse pas un fragment connu', () => {
        // "parser" est detecte a l'etape 3 avant que shared soit consulte (etape 4)
        expect(detectFileType('/src/shared/parser.ts')).toBe('parser');
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — extension seule (etape 5)', () => {

    it('monComponent.tsx → component', () => {
        expect(detectFileType('/src/components/monComponent.tsx')).toBe('component');
    });

    it('Button.jsx → component', () => {
        expect(detectFileType('/src/Button.jsx')).toBe('component');
    });

    it('.ts sans fragment connu → generic', () => {
        expect(detectFileType('/src/mystuff.ts')).toBe('generic');
    });

    it('.js sans fragment connu → generic', () => {
        expect(detectFileType('/src/mystuff.js')).toBe('generic');
    });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('detectFileType — cas ambigus et priorites', () => {

    it('nom exact surclasse le prefixe config (index.ts = entrypoint, pas config)', () => {
        // "index.ts" est dans EXACT_NAMES → entrypoint, meme si on pouvait imaginer config
        expect(detectFileType('/src/index.ts')).toBe('entrypoint');
    });

    it('le prefixe config surclasse les fragments (configService.ts → config, pas service)', () => {
        // "config" en prefixe est evalue a l'etape 2, "service" est un fragment (etape 3)
        expect(detectFileType('/src/configService.ts')).toBe('config');
    });

    it('casse ignoree — INDEX.TS reconnu comme entrypoint', () => {
        expect(detectFileType('/src/INDEX.TS')).toBe('entrypoint');
    });

    it('chemin profond — seul le nom de fichier compte (etapes 1-3)', () => {
        expect(detectFileType('/very/deep/nested/path/utils.ts')).toBe('utility');
    });

    it('chemin sans extension → generic', () => {
        expect(detectFileType('/src/Makefile')).toBe('generic');
    });

    it('fichier vide (chemin /) → generic sans crash', () => {
        expect(() => detectFileType('/')).not.toThrow();
    });
});
