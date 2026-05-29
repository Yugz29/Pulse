# Contracts

Ce dossier contient les contrats actifs de Pulse.

Les contrats définissent ce que Pulse peut faire, ne peut pas faire, et quelles frontières doivent rester stables. Ils passent avant les notes d'audit, les documents Lab et les archives.

Si un contrat contredit une doc Lab ou archive, le contrat gagne. Si deux contrats semblent contradictoires, traiter cela comme un blocage de conception à clarifier avant patch.

## Sommaire

- `OBSERVATION_CONTRACT.md` — observation locale, filtrage, bruit, événements.
- `INTERPRETATION_CONTRACT.md` — signaux, scoring prudent, incertitude.
- `SESSION_CONTRACT.md` — sessions, lock, idle, lifecycle.
- `MINIMAL_MEMORY_CONTRACT.md` — mémoire minimale Core.
- `PROPOSAL_CONTRACT.md` — propositions contrôlées / MCP.
- `MEMORY_LEARNING_CONTRACT.md` — règles C3 mémoire / apprentissage.
- `MEMORY_CANDIDATES_READINESS.md` — readiness technique avant MVP candidates.
- `MEMORY_CANDIDATES_MVP.md` — cadre MVP conceptuel des candidates.
