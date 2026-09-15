# Benchmark de modèles du 2026-09-15

Décision : [`2026-09-14-benchmark-modeles-en-local.md`](../../decisions/2026-09-14-benchmark-modeles-en-local.md).

**Attendu :** le jugement du comparatif Qwen / Gemma par l'utilisateur, puis
le verdict de modèle dans la note de décision. Le dossier est retiré une fois
le verdict consigné.

- `comparatif-qwen-gemma.md` : matière brute du jugement, les 13 sessions
  valides pour Qwen et Gemma et, en annexe, `2ce34456` avec la sortie
  rejetée de Gemma, hors compte.

Les preuves des chiffres de la note (sorties, `meta.json`, `time-l.txt`) ne
sont pas ici : mesure de référence, elles vivent à côté de la note, sous
[`docs/decisions/2026-09-14-benchmark-modeles-en-local/`](../../decisions/2026-09-14-benchmark-modeles-en-local/).
Restent hors dépôt, dans `corpus/docs/audits/2026-09-15-benchmark-modeles/` :
`run.log`, les configs et les scripts (`run-benchmark.sh`, `comparatif.py`,
`revalider-chemins-commande.py`, `regex_flag.py`).
