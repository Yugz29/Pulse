import * as fs from 'node:fs';
import * as path from 'node:path';
import { Project, SyntaxKind, Node } from 'ts-morph';

// ── INTERFACES ──

export interface FunctionMetrics {
    name: string;
    startLine: number;
    lineCount: number;
    cyclomaticComplexity: number;
}

export interface FileMetrics {
    filePath: string;
    totalLines: number;
    totalFunctions: number;
    functions: FunctionMetrics[];
    language: string;
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

// ── COMPLEXITÉ (ts-morph) ──

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

// ── ANALYSE TS/JS via ts-morph ──

function analyzeWithTsMorph(filePath: string): FileMetrics {
    const project = new Project({
        useInMemoryFileSystem: false,
        skipAddingFilesFromTsConfig: true,
        compilerOptions: { allowJs: true },
    });

    const sourceFile = project.addSourceFileAtPath(filePath);
    const totalLines = sourceFile.getEndLineNumber();

    const allFunctions = [
        ...sourceFile.getFunctions(),
        ...sourceFile.getDescendantsOfKind(SyntaxKind.ArrowFunction),
        ...sourceFile.getClasses().flatMap(cls => cls.getMethods()),
    ];

    const functions: FunctionMetrics[] = allFunctions.map(fn => {
        let name = 'anonymous';
        if ('getName' in fn && typeof fn.getName === 'function') {
            const raw = fn.getName() as string | undefined;
            if (raw) name = raw;
        }
        if (name === 'anonymous') {
            const parent = fn.getParent();
            if (parent && 'getName' in parent && typeof (parent as { getName?: () => string | undefined }).getName === 'function') {
                const parentName = (parent as { getName: () => string | undefined }).getName();
                if (parentName) name = parentName;
            }
        }

        const startLine = fn.getStartLineNumber();
        const lineCount = fn.getEndLineNumber() - startLine + 1;

        let cyclomaticComplexity = 1;
        fn.forEachDescendant((node: Node) => {
            if (COMPLEXITY_KINDS.has(node.getKind())) cyclomaticComplexity++;
        });

        return { name, startLine, lineCount, cyclomaticComplexity };
    });

    return { filePath, totalLines, totalFunctions: functions.length, functions, language: 'typescript' };
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

                functions.push({ name, startLine: i + 1, lineCount: fnLines.length, cyclomaticComplexity });
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
            const result = analyzeWithTsMorph(filePath);
            return { ...result, language };
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
