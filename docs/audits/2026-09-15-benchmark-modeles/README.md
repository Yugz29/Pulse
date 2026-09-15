# Benchmark de modèles du 2026-09-15

Décision : [`2026-09-14-benchmark-modeles-en-local.md`](../../decisions/2026-09-14-benchmark-modeles-en-local.md).

**Attendu :** le jugement du comparatif Qwen / Gemma par l'utilisateur, puis
le verdict de modèle dans la note de décision.

- `comparatif-qwen-gemma.md` : matière brute du jugement, les 13 sessions
  valides pour Qwen et Gemma et, en annexe, `2ce34456` avec la sortie
  rejetée de Gemma, hors compte.
- `out/<modèle>/mlx-<modèle>/` : les 14 sorties et le `meta.json` des trois
  modèles, copie à l'identique de `corpus/`. La note en tire validité,
  durées de génération, tokens et attentes annotées.
- `time-l.txt` : sortie de `/usr/bin/time -l` pour chaque passage, extraite
  telle quelle de `run.log` ; la note en tire la durée du processus et le
  pic mémoire.

Restent hors dépôt, dans `corpus/docs/audits/2026-09-15-benchmark-modeles/` :
`run.log`, les configs et les scripts (`run-benchmark.sh`, `comparatif.py`,
`revalider-chemins-commande.py`, `regex_flag.py`).
