import { Project, SyntaxKind, Node } from 'ts-morph';


// Métriques pour une seule fonction
export interface FunctionMetrics {
    name: string;               // Nom de la fonction (ou "anonymous" si sans nom)
    startLine: number;          // Ligne de début dans le fichier
    lineCount: number;          // Nombre de lignes de la fonction
    cyclomaticComplexity: number; // Score de complexité (expliqué plus bas)
}

// Résultat global pour un fichier entier
export interface FileMetrics {
    filePath: string;           // Chemin absolu du fichier analysé
    totalLines: number;         // Nombre total de lignes du fichier
    totalFunctions: number;     // Nombre de fonctions détectées
    functions: FunctionMetrics[]; // Détail par fonction
}


// SyntaxKind est une énumération de ts-morph qui liste tous les types de nœuds AST.
// On définit ici les nœuds qui augmentent la complexité cyclomatique.
const COMPLEXITY_NODES = new Set([
    SyntaxKind.IfStatement,           // if (...)
    SyntaxKind.ForStatement,          // for (...)
    SyntaxKind.ForInStatement,        // for (x in obj)
    SyntaxKind.ForOfStatement,        // for (x of arr)
    SyntaxKind.WhileStatement,        // while (...)
    SyntaxKind.DoStatement,           // do { } while (...)
    SyntaxKind.CaseClause,            // case X: dans un switch
    SyntaxKind.CatchClause,           // catch (err)
    SyntaxKind.ConditionalExpression, // condition ? a : b (ternaire)
    SyntaxKind.AmpersandAmpersandToken, // &&
    SyntaxKind.BarBarToken,           // ||
    SyntaxKind.QuestionQuestionToken, // ?? (nullish coalescing)
]);

// -----------------------------------------------------------------------------
// analyzeFile
// -----------------------------------------------------------------------------


export function analyzeFile(filePath: string): FileMetrics {

    // --- Étape 1 : Créer un "projet" ts-morph ---
    // Un Project est le point d'entrée de ts-morph.
    // useInMemoryFileSystem: false = on lit les vrais fichiers sur le disque.
    // skipAddingFilesFromTsConfig: true = on ne charge pas tout le projet,
    // juste le fichier qu'on lui donne explicitement.
    const project = new Project({
        useInMemoryFileSystem: false,
        skipAddingFilesFromTsConfig: true,
        compilerOptions: {
            allowJs: true, // Accepte aussi les fichiers .js, pas seulement .ts
        },
    });

    // --- Étape 2 : Charger le fichier source ---
    // addSourceFileAtPath lit le fichier et construit son AST en mémoire.
    const sourceFile = project.addSourceFileAtPath(filePath);

    // --- Étape 3 : Métriques globales du fichier ---
    const totalLines = sourceFile.getEndLineNumber();

    // --- Étape 4 : Collecter toutes les fonctions du fichier ---
    // ts-morph distingue plusieurs types de fonctions dans le code :
    //
    //   getFunctions()      → function foo() {}  (déclarations classiques)
    //   getArrowFunctions() → const foo = () => {}  (fonctions fléchées)
    //   getMethods()        → méthodes dans une classe
    //
    // On les rassemble toutes dans un seul tableau avec le spread operator (...).

    const allFunctions = [
        ...sourceFile.getFunctions(),
        ...sourceFile.getDescendantsOfKind(SyntaxKind.ArrowFunction),
        ...sourceFile
            .getClasses()
            .flatMap((cls) => cls.getMethods()), // flatMap = map + aplatit les tableaux imbriqués
    ];

    // --- Étape 5 : Calculer les métriques pour chaque fonction ---
    const functions: FunctionMetrics[] = allFunctions.map((fn) => {

        // Récupère le nom de la fonction si elle en a un.
        // Pour les fonctions fléchées, on remonte au nœud parent pour trouver
        // le nom de la variable (ex: "const maFonction = () => {}")
        let name = 'anonymous';
        if ('getName' in fn && typeof fn.getName === 'function') {
            const rawName: string | undefined = fn.getName();
            if (rawName !== undefined) name = rawName;
        }
        if (name === 'anonymous') {
            // Tentative de récupérer le nom depuis le parent (cas arrow function)
            const parent = fn.getParent();
            if (parent && 'getName' in parent && typeof parent.getName === 'function') {
                const parentName: string | undefined = (parent as { getName: () => string | undefined }).getName();
                if (parentName !== undefined) name = parentName;
            }
        }

        // Position dans le fichier
        const startLine = fn.getStartLineNumber();
        const endLine = fn.getEndLineNumber();
        const lineCount = endLine - startLine + 1;

        // --- Calculation of cyclomatic complexity ---
        let cyclomaticComplexity = 1;
        fn.forEachDescendant((node: Node) => {
            if (COMPLEXITY_NODES.has(node.getKind())) {
                cyclomaticComplexity++;
            }
        });

        return { name, startLine, lineCount, cyclomaticComplexity };
    });

    // --- Étape 6 : Retourner le résultat final ---
    return {
        filePath,
        totalLines,
        totalFunctions: functions.length,
        functions,
    };
}
