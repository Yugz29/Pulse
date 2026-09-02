<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Pulse_Core** (1 435 nodes, 4 763 edges, 123 execution flows — index à la racine du repo unique, code sous `core/`).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact analysis before editing.** Use `impact({target: "symbolName", direction: "upstream"})` (MCP) or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .` (CLI fallback); report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/Pulse_Core/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Pulse_Core/clusters` | All functional areas |
| `gitnexus://repo/Pulse_Core/processes` | All execution flows |
| `gitnexus://repo/Pulse_Core/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Pulse — règles du repo unique

Pulse est le système entier ; `core/` est Pulse Core, la couche observation.
Direction, architecture, roadmap et décisions : `docs/VISION.md` (canonique).

## Toujours

- Lire `docs/VISION.md` avant tout travail de conception ; en cas de doute,
  demander plutôt que décider.
- Nouvelle décision de direction → note datée dans `docs/decisions/` et ligne
  dans « Décisions prises » de `docs/VISION.md`.
- Lancer les tests de Core depuis `core/` : `make test` (ou
  `.venv/bin/python -m pytest tests_v2`).
- Tout nouveau code de la couche Intelligence va dans `intelligence/`, jamais
  dans `core/`.

## Jamais

- **Core est gelé en 0.2.0.** Ne pas modifier `core/daemon_v2/`,
  `core/tests_v2/`, `core/scripts/`, `core/macos_observer/` hors du pas 2 de
  la roadmap (Context API), explicitement demandé.
- Pas de `git push` sans accord explicite de l'utilisateur.
- Aucune suppression de fichier sans accord explicite ; préférer l'archive.
- Pas de refactor opportuniste de `core/TODOS.md`, `core/CHANGELOG.md` ni des
  tests.
- Ne pas réintroduire Lab, Ollama, MCP SSE ni un Model Router multi-tiers :
  ils sont hors périmètre (voir « Plus tard » de la Vision). L'archive de Lab
  est dans `~/Projets/ARCHIVE/Pulse_Lab` (tag `archive/lab-2026-09`).

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
