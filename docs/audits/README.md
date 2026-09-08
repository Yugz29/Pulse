# Audits — rapports dans le dépôt, traces hors dépôt

Chaque audit vit dans un dossier daté `docs/audits/<date>-<sujet>/` avec son
rapport Markdown, ses prompts archivés et ses tables d'analyse (`measurements.json`,
`taxonomy-*.json`, `review-*.json`, `unchanged-inputs.json`, `environment.json`…).
Ces tables sont versionnées : le `.gitignore` racine ignore
`docs/audits/**/*.json` puis réinclut les JSON situés directement à la racine
d'un audit.

## Où vivent les traces

Les traces brutes (sorties de modèle, rejeux `before/`, `after/`, `trial-*/`,
`outputs/`, scénarios contradictoires `scenarios/`) ne sont plus dans le dépôt
depuis le 2026-09-09. Elles vivent dans `corpus/` à la racine du dépôt, ignoré
par Git, avec la même arborescence :

```text
corpus/docs/audits/<date>-<sujet>/<before|after|trial-v5|outputs|scenarios>/…
```

Un lien `after/xxx.json` dans un rapport se lit donc
`corpus/docs/audits/<audit>/after/xxx.json`. Le dossier `corpus/` est une
sauvegarde locale à conserver hors Git (disque, archive) ; il n'est pas
reconstruit automatiquement.

## Rejouer un audit

Le corpus gelé d'entrée reste versionné dans `intelligence/eval/observed/`
(14 sessions, Context API v3) et `intelligence/eval/corpus/` (10 sessions,
lecture historique v2), avec les annotations humaines dans
`intelligence/eval/expected/`. Depuis `intelligence/` :

```bash
.venv/bin/pulse-intel eval --provider mlx --corpus eval/observed --out /chemin/hors/depot
```

`eval` reconstruit l'entrée exacte du modèle, appelle le provider, valide la
sortie et compare `open` aux annotations. Les rapports précisent modèle,
température, plafonds et empreintes SHA-256 utilisés pour chaque passage ; un
rejeu se compare à ces valeurs, pas à un score absolu.

## Dette connue : couplage tests ↔ corpus

La suite de tests Intelligence charge `eval/observed` en dur :
`DEFAULT_CORPUS` dans `evaluation.py`, un test qui exige exactement 14 sessions
de reconstruction v2, et les annotations de `eval/expected` vérifiées contre
leurs sessions du corpus. C'est pour cela que `eval/observed` reste dans le
dépôt. Ce couplage est à casser dans une PR ultérieure (corpus optionnel,
chemin configurable, tests ignorés quand il est absent) avant de sortir le
corpus vers `corpus/`.
