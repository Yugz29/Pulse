# Audits

Un audit produit une **note de décision** (`docs/decisions/`) ou une **entrée
de journal** (`docs/dogfooding.md`). Ses données de travail — prompts
archivés, taxonomies, revues, rejeux, sorties de modèle — restent hors dépôt,
dans `corpus/` à la racine (ignoré par Git). Seul un audit **en attente d'une
réponse de l'utilisateur** garde un dossier ici.

## En attente

| Audit | Ce qui est attendu |
| --- | --- |
| [`2026-09-09-adjudication-reprise/`](2026-09-09-adjudication-reprise/) | Vos réponses aux 14 fiches (`fiches/`, questions A–E) : vérité terrain sur ce qui aide vraiment à reprendre. Commencer par 13, 14, 03, 04 ; répondre A et B avant de lire la sortie du modèle. |

## Clos

Retirés du dépôt le 2026-09-09 : leurs conclusions sont dans les décisions et
le journal listés ci-dessous. Les rapports complets sont dans l'historique Git
(dernier commit avant le retrait) et, localement, dans
`corpus/docs/audits-retired/`.

| Date | Audit | Verdict | Où c'est consigné |
| --- | --- | --- | --- |
| 09-06 | Audit Core + Intelligence après le jour 1 de dogfooding, puis relecture du soir | 11 défauts, tous corrigés en PR #56 à #69 sous gel fonctionnel | Décisions du 09-06 : exécution unique, fuseau de reconstruction, modèle local Qwen, rédaction des champs libres ; hardening dans `core/TODOS.md` |
| 09-07 | Validation MLX (prompt v2, 14 sessions) | 14/14 valides en format ; défauts de sens dans `open` reproductibles | `dogfooding.md` jour 2 ; décision modèle local Qwen |
| 09-07 | Validation `open` v3 | Le gabarit v3 déplace l'erreur au lieu de la corriger (D6) | `dogfooding.md` jour 3 |
| 09-08 | Évaluation v3 sur D6 | Passage d'évaluation, sans nouvelle conclusion | `dogfooding.md` jour 3 |
| 09-08 | Reconstruction unique des sessions | 245 lignes retirées, un seul moteur, insertion 42× plus rapide | [décision](../decisions/2026-09-08-reconstruction-unique-des-sessions.md) |
| 09-08 | Observations ordonnées | `/context` schéma 3, entrée v2 / prompt v4 ; `open` régresse encore | [décision](../decisions/2026-09-08-observations-ordonnees.md) |
| 09-08 | Reprise fondée | Prompt v5 : 14/14 valides, 2/4 attentes humaines ; non fiable au quotidien sans relecture | [décision](../decisions/2026-09-08-reprise-fondee.md) |
| 09-09 | Assouplissement des consignes | Gel de Core levé, `AGENTS.md` unique, autonomie bornée au chantier | [décision](../decisions/2026-09-09-assouplissement-instructions.md) |

## Rejouer un audit

Le corpus gelé d'entrée reste versionné dans `intelligence/eval/observed/`
(14 sessions, Context API v3) et `intelligence/eval/corpus/` (10 sessions,
lecture historique v2), avec les annotations humaines dans
`intelligence/eval/expected/`. Les prompts v1 à v5 sont dans le code. Depuis
`intelligence/` :

```bash
.venv/bin/pulse-intel eval --provider mlx --corpus eval/observed --out /chemin/hors/depot
```

Les décisions précisent modèle, température, plafonds et empreintes SHA-256
de chaque passage ; un rejeu se compare à ces valeurs, pas à un score absolu.

## Dette connue : couplage tests ↔ corpus

La suite de tests Intelligence charge `eval/observed` en dur
(`DEFAULT_CORPUS` dans `evaluation.py`, un test qui exige exactement 14
sessions, annotations vérifiées contre le corpus). C'est pour cela que
`eval/observed` reste dans le dépôt. À casser avant de sortir le corpus vers
`corpus/` : corpus optionnel, chemin configurable, tests ignorés quand il est
absent.
