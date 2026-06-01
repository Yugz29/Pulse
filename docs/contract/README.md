# Contracts

Ce dossier contient les contrats actifs de Pulse.

Les contrats définissent ce que Pulse peut faire, ne peut pas faire, et quelles frontières doivent rester stables. Ils passent avant les notes d'audit, les documents Lab et les archives.

Si un contrat contredit une doc Lab ou archive, le contrat gagne. Si deux contrats semblent contradictoires, traiter cela comme un blocage de conception à clarifier avant patch.

## Sommaire

- `observation.md` — observation locale, filtrage, bruit, événements.
- `interpretation.md` — signaux, scoring prudent, incertitude.
- `session.md` — sessions, lock, idle, lifecycle.
- `minimal-memory.md` — mémoire minimale Core.
- `proposal.md` — propositions contrôlées / MCP.

Les contrats mémoire/apprentissage futurs sont hors parcours public tant que Lab/R7 est gelé. Les copies locales éventuelles vivent sous `docs/private/memory/` et ne doivent pas être ajoutées au repo public.
