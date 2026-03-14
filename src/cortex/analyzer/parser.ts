import * as fs from 'node:fs';
import * as path from 'node:path';
import { Project, SyntaxKind, Node, SourceFile } from 'ts-morph';

// ── INTERFACES ──

export interface FunctionMetrics {
    name:                 string;
    startLine:            number;
    lineCount:            number;
    cyclomaticComplexity: number;
    cognitiveComplexity:  number;   // P2 — charge mentale réelle (imbrication pénalisée)
    parameterCount:       number;
    maxDepth:             number;
}

export interface FileMetrics {
    filePath:       string;
    totalLines:     number;
    totalFunctions: number;
    functions:      FunctionMetrics[];
    language:       string;
}

// ── LANGAGES SUPPORTÉS ──

type Language = 'typescript' | 'javascript' | 'python' | 'unknown';

const EXTENSION_MAP: Record<string, Language> = {
    '.ts':  'typescript',
    '.tsx': 'typescript',
    '.js':  'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.py':  'python',
};

function detectLanguage(filePath: string): Language {
    const ext = path.extname(filePath).toLowerCase();
    return EXTENSION_MAP[ext] ?? 'unknown';
}

// ── INSTANCE PROJECT PARTAGÉE (P1) ──
// Une seule instance ts-morph réutilisée entre tous les fichiers du scan.
// Évite de créer/détruire 30+ instances par scan.

let _sharedProject: Project | null = null;

export function getSharedProject(): Project {
    if (!_sharedProject) {
        _sharedProject = new Project({
            useInMemoryFileSystem: false,
            skipAddingFilesFromTsConfig: true,
            compilerOptions: { allowJs: true, skipLibCheck: true },
        });
    }
    return _sharedProject;
}

export function resetSharedProject(): void {
    _sharedProject = null;
}

// ── RÉSOLUTION DU NOM (P1 — fix React arrow functions) ──
//
// Stratégie en cascade :
//  1. Fonction déclarée (function foo) ou méthode de classe → getName() direct
//  2. Arrow function assignée à const/let/var (VariableDeclaration)
//  3. Arrow function assignée comme propriété d'objet (PropertyAssignment)
//  4. Arrow function dans un paramètre nommé (Parameter)
//  5. Arrow function assignée via = (BinaryExpression, ex: this.handler = () => {})
//  6. Fallback → 'anonymous'

function resolveFunctionName(fn: Node): string {
    // Cas 1 : getFunctions() et getMethods() ont getName()
    if ('getName' in fn && typeof (fn as { getName?: () => string | undefined }).getName === 'function') {
        const name = (fn as { getName: () => string | undefined }).getName();
        if (name) return name;
    }

    // Pour les ArrowFunctions, on remonte l'arbre AST
    let cursor: Node | undefined = fn.getParent();

    // Remonte jusqu'à 3 niveaux pour trouver un ancêtre nommé
    for (let i = 0; i < 3 && cursor; i++) {
        const kind = cursor.getKind();

        // const handleClick = () => {}  →  VariableDeclaration
        if (kind === SyntaxKind.VariableDeclaration) {
            const varDecl = cursor as import('ts-morph').VariableDeclaration;
            const name = varDecl.getName();
            if (name) return name;
        }

        // { onClick: () => {} }  →  PropertyAssignment
        if (kind === SyntaxKind.PropertyAssignment) {
            const prop = cursor as import('ts-morph').PropertyAssignment;
            const nameNode = prop.getNameNode();
            const text = nameNode.getText();
            if (text) return text;
        }

        // function foo(callback: () => void)  →  Parameter
        if (kind === SyntaxKind.Parameter) {
            const param = cursor as import('ts-morph').ParameterDeclaration;
            const name = param.getName();
            if (name) return `<param:${name}>`;
        }

        // this.handler = () => {}  →  BinaryExpression
        if (kind === SyntaxKind.BinaryExpression) {
            const bin = cursor as import('ts-morph').BinaryExpression;
            const left = bin.getLeft().getText();
            // Prend la partie droite du point : this.handleClick → handleClick
            const shortName = left.split('.').pop();
            if (shortName) return shortName;
        }

        cursor = cursor.getParent();
    }

    return 'anonymous';
}

// ── PROFONDEUR D'IMBRICATION (ts-morph) ──

const NESTING_KINDS = new Set([
    SyntaxKind.IfStatement,
    SyntaxKind.ForStatement,
    SyntaxKind.ForInStatement,
    SyntaxKind.ForOfStatement,
    SyntaxKind.WhileStatement,
    SyntaxKind.DoStatement,
    SyntaxKind.SwitchStatement,
    SyntaxKind.TryStatement,
    // JSX conditionnel — on compte l'imbrication logique, pas l'imbrication HTML structurelle
    // JsxExpression = { condition && <X/> } ou { condition ? <A/> : <B/> } dans du JSX
    SyntaxKind.JsxExpression,
]);

function computeMaxDepth(node: Node, current = 0): number {
    let max = current;
    for (const child of node.getChildren()) {
        const next = NESTING_KINDS.has(child.getKind()) ? current + 1 : current;
        max = Math.max(max, computeMaxDepth(child, next));
    }
    return max;
}

// ── COMPLEXITÉ CYCLOMATIQUE (ts-morph) ──

const COMPLEXITY_KINDS = new Set([
    SyntaxKind.IfStatement,
    SyntaxKind.ForStatement,
    SyntaxKind.ForInStatement,
    SyntaxKind.ForOfStatement,
    SyntaxKind.WhileStatement,
    SyntaxKind.DoStatement,
    SyntaxKind.CaseClause,
    SyntaxKind.CatchClause,
    SyntaxKind.ConditionalExpression,
    SyntaxKind.AmpersandAmpersandToken,
    SyntaxKind.BarBarToken,
    SyntaxKind.QuestionQuestionToken,
]);

// ── COMPLEXITÉ COGNITIVE (P2 — SonarSource model) ──
//
// Règles :
//  - +1 pour chaque rupture de flux (if, for, while, catch, switch, ternaire, &&, ||, ??)
//  - +profondeur_courante pour chaque structure imbriquée (pénalité d'imbrication)
//  - +1 pour else / else-if / finally (rupture de séquence)
//  - Pas de bonus de base comme la cyclomatique
//
// Résultat : un if imbriqué dans 3 boucles coûte +4 (1 + 3 de profondeur),
// vs une cyclomatique de +1 identique pour tous les cas.

const COGNITIVE_BREAK_KINDS = new Set([
    SyntaxKind.IfStatement,
    SyntaxKind.ForStatement,
    SyntaxKind.ForInStatement,
    SyntaxKind.ForOfStatement,
    SyntaxKind.WhileStatement,
    SyntaxKind.DoStatement,
    SyntaxKind.SwitchStatement,
    SyntaxKind.CatchClause,
    SyntaxKind.ConditionalExpression,
    SyntaxKind.AmpersandAmpersandToken,
    SyntaxKind.BarBarToken,
    SyntaxKind.QuestionQuestionToken,
]);

const COGNITIVE_NESTING_KINDS = new Set([
    SyntaxKind.IfStatement,
    SyntaxKind.ForStatement,
    SyntaxKind.ForInStatement,
    SyntaxKind.ForOfStatement,
    SyntaxKind.WhileStatement,
    SyntaxKind.DoStatement,
    SyntaxKind.SwitchStatement,
    SyntaxKind.TryStatement,
]);

function computeCognitiveComplexity(node: Node, nestingLevel = 0): number {
    let score = 0;

    for (const child of node.getChildren()) {
        const kind = child.getKind();

        if (COGNITIVE_BREAK_KINDS.has(kind)) {
            // +1 de base + pénalité d'imbrication
            score += 1 + nestingLevel;
        }

        // else / else-if → +1 rupture de séquence (pas de pénalité d'imbrication)
        if (kind === SyntaxKind.ElseKeyword) {
            score += 1;
        }

        // Récursion — on approfondit le niveau si c'est une structure imbriquante
        const nextLevel = COGNITIVE_NESTING_KINDS.has(kind) ? nestingLevel + 1 : nestingLevel;
        score += computeCognitiveComplexity(child, nextLevel);
    }

    return score;
}

// ── ANALYSE TS/JS via ts-morph ──

function analyzeSourceFile(sourceFile: SourceFile, filePath: string, language: Language): FileMetrics {
    const totalLines = sourceFile.getEndLineNumber();

    const allFunctions = [
        ...sourceFile.getFunctions(),
        ...sourceFile.getDescendantsOfKind(SyntaxKind.ArrowFunction),
        ...sourceFile.getClasses().flatMap(cls => cls.getMethods()),
    ];

    const functions: FunctionMetrics[] = allFunctions.map(fn => {
        const name = resolveFunctionName(fn);

        const startLine = fn.getStartLineNumber();
        const lineCount = fn.getEndLineNumber() - startLine + 1;

        // Complexité cyclomatique
        let cyclomaticComplexity = 1;
        fn.forEachDescendant((node: Node) => {
            if (COMPLEXITY_KINDS.has(node.getKind())) cyclomaticComplexity++;
        });

        // Complexité cognitive (P2)
        const cognitiveComplexity = computeCognitiveComplexity(fn);

        // Compte les paramètres réels — détecte le destructuring d'objet React ({ prop1, prop2 })
        // pour éviter de scorer 1 quand la fonction reçoit N props encapsulées dans un objet
        const parameterCount = (() => {
            if (!('getParameters' in fn) || typeof fn.getParameters !== 'function') return 0;
            const params = fn.getParameters() as import('ts-morph').ParameterDeclaration[];
            if (params.length === 0) return 0;
            // Si un seul paramètre et qu'il est un ObjectBindingPattern ({ a, b, c })
            // → compter les éléments du binding comme paramètres réels
            if (params.length === 1) {
                const nameNode = params[0]!.getNameNode();
                if (nameNode.getKind() === SyntaxKind.ObjectBindingPattern) {
                    const elements = (nameNode as import('ts-morph').ObjectBindingPattern).getElements();
                    return elements.length;
                }
            }
            return params.length;
        })();

        const maxDepth = computeMaxDepth(fn);

        return { name, startLine, lineCount, cyclomaticComplexity, cognitiveComplexity, parameterCount, maxDepth };
    });

    return { filePath, totalLines, totalFunctions: functions.length, functions, language };
}

function analyzeWithTsMorph(filePath: string): FileMetrics {
    const language = detectLanguage(filePath) as Language;
    const project  = getSharedProject();

    // Supprime le fichier s'il était déjà dans le projet (scan précédent / live watcher)
    const existing = project.getSourceFile(filePath);
    if (existing) project.removeSourceFile(existing);

    const sourceFile = project.addSourceFileAtPath(filePath);
    const result = analyzeSourceFile(sourceFile, filePath, language);

    // Cleanup : retire le fichier après analyse pour éviter l'accumulation en mémoire
    project.removeSourceFile(sourceFile);

    return result;
}

// ── ANALYSE PYTHON via regex ──

function analyzeWithRegex(source: string, filePath: string, language: Language): FileMetrics {
    const lines = source.split('\n');

    const patterns: RegExp[] = [
        /^\s*def\s+(\w+)\s*\(/,
        /^\s*async\s+def\s+(\w+)\s*\(/,
    ];

    const complexityPatterns: RegExp[] = [
        /\bif\b/, /\belif\b/, /\bfor\b/, /\bwhile\b/,
        /\bexcept\b/, /\band\b/, /\bor\b/,
    ];

    // Patterns pour la complexité cognitive Python (structures imbriquantes)
    const cogNestingPatterns: RegExp[] = [
        /^\s*(if|elif|for|while|with|try)\b/,
    ];
    const cogBreakPatterns: RegExp[] = [
        /\bif\b/, /\belif\b/, /\belse\b/, /\bfor\b/, /\bwhile\b/,
        /\bexcept\b/, /\bfinally\b/, /\band\b/, /\bor\b/,
    ];

    const functions: FunctionMetrics[] = [];

    lines.forEach((line, i) => {
        for (const pat of patterns) {
            if (pat.test(line)) {
                const nameMatch = /(?:def\s+|async\s+def\s+)(\w+)/.exec(line);
                const name = nameMatch?.[1] ?? 'anonymous';

                let endLine = lines.length;
                for (let j = i + 1; j < lines.length; j++) {
                    if (patterns.some(p => p.test(lines[j] ?? ''))) { endLine = j; break; }
                }

                const fnLines = lines.slice(i, endLine);

                const cyclomaticComplexity = 1 + fnLines.reduce((acc, l) =>
                    acc + complexityPatterns.filter(p => p.test(l)).length, 0);

                // Complexité cognitive Python — approximation via indentation
                let cognitiveComplexity = 0;
                let prevIndent = 0;
                for (const fl of fnLines) {
                    const indent = Math.floor((fl.match(/^(\s+)/)?.[1]?.replace(/\t/g, '    ').length ?? 0) / 4);
                    const nestingLevel = Math.max(0, indent - 1);
                    if (cogBreakPatterns.some(p => p.test(fl))) {
                        cognitiveComplexity += 1 + (cogNestingPatterns.some(p => p.test(fl)) ? nestingLevel : 0);
                    }
                    prevIndent = indent;
                }

                const sigMatch = /\(([^)]*)\)/.exec(line);
                const parameterCount = sigMatch?.[1]?.trim()
                    ? sigMatch[1].split(',').filter(p => p.trim().length > 0).length
                    : 0;

                const maxDepth = fnLines.reduce((max, l) => {
                    const indent = l.match(/^(\s+)/)?.[1] ?? '';
                    const depth  = Math.floor(indent.replace(/\t/g, '    ').length / 4);
                    return Math.max(max, depth);
                }, 0);

                functions.push({
                    name, startLine: i + 1, lineCount: fnLines.length,
                    cyclomaticComplexity, cognitiveComplexity,
                    parameterCount, maxDepth,
                });
                break;
            }
        }
    });

    return { filePath, totalLines: lines.length, totalFunctions: functions.length, functions, language };
}

// ── POINT D'ENTRÉE ──

export async function analyzeFile(filePath: string): Promise<FileMetrics> {
    const language = detectLanguage(filePath);

    if (language === 'typescript' || language === 'javascript') {
        try {
            return analyzeWithTsMorph(filePath);
        } catch (err) {
            console.warn(`[Pulse] ts-morph failed for ${filePath}, using regex fallback:`, err);
        }
    }

    const source = fs.readFileSync(filePath, 'utf-8');
    return analyzeWithRegex(source, filePath, language);
}

export function analyzeFileSync(filePath: string): FileMetrics {
    const language = detectLanguage(filePath);
    const source   = fs.readFileSync(filePath, 'utf-8');
    return analyzeWithRegex(source, filePath, language);
}
