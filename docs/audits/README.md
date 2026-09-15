# Audits

Un audit produit une **note de décision** (`docs/decisions/`) ou une **entrée
de journal** (`docs/dogfooding.md`). Ses données de travail — prompts
archivés, taxonomies, revues, rejeux, sorties de modèle — restent hors dépôt,
dans `corpus/` à la racine (ignoré par Git). Seul un audit **en attente d'une
réponse de l'utilisateur** garde un dossier ici.

## En attente

| Audit | Ce qui est attendu |
| --- | --- |
| [`2026-09-09-adjudication-reprise/`](2026-09-09-adjudication-reprise/) | Les 18 fiches sont répondues (2026-09-10) et la synthèse lue (2026-09-11, décisions consignées dans [`SYNTHESE.md`](2026-09-09-adjudication-reprise/SYNTHESE.md)). Les réponses restent ici comme **vérité terrain reconstruite** tant que le format d'annotation n'est pas validé. Le dossier attend le rejeu sur `open` (trois variantes du prompt v6, en batch) avant de se clore. |
| [`2026-09-15-benchmark-modeles/`](2026-09-15-benchmark-modeles/) | Le jugement du comparatif Qwen / Gemma, puis le verdict de modèle dans la [note de décision](../decisions/2026-09-14-benchmark-modeles-en-local.md). Les preuves des chiffres de la note, mesure de référence, vivent à côté d'elle, sous [`docs/decisions/2026-09-14-benchmark-modeles-en-local/`](../decisions/2026-09-14-benchmark-modeles-en-local/). |

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

## Question ouverte : ce qui protège `corpus/`

Ouverte le 2026-09-15, à trancher ; aucune solution retenue.

- `corpus/` sort du dépôt par règle (`AGENTS.md`, `.gitignore`) et n'a aucune
  sauvegarde : aucune destination Time Machine n'est configurée sur la
  machine (`tmutil`, 2026-09-15).
- Il porte ce qui ne se régénère pas : journaux et mesures de passage
  (`run.log`), sorties de modèle d'anciens passages, rejeux, copies locales
  des audits retirés (`audits-retired/`). 2,8 Mo le 2026-09-15.
- Le benchmark du 2026-09-15 l'a rendu concret : les chiffres de référence de
  sa note reposaient sur ce dossier. Les sorties, les `meta.json` et l'extrait
  `time -l` ont été versionnés à part, à côté de la note, sous
  `docs/decisions/2026-09-14-benchmark-modeles-en-local/` ; `run.log` et les
  scripts restent dans `corpus/`.

## Question ouverte : ce que protège le hook de pré-poussée

Ouverte le 2026-09-15, à trancher ; aucune solution retenue.

- `.git/hooks/pre-push` appelle `gstack-redact-prepush` (gstack, hors dépôt,
  hook « managed »). Il scanne les lignes ajoutées de `<distant>..<local>` ;
  il ne lit ni les messages de commit, ni l'historique, ni les fichiers
  binaires.
- Une alerte HIGH (identifiant) bloque la poussée avant l'envoi. Une alerte
  MEDIUM (PII, interne) ne bloque pas : le hook n'écrit qu'un nombre, sans
  fichier, ligne ni chaîne, et la poussée se poursuit dans la même commande.
- Il scanne en visibilité « private », quelle que soit celle du dépôt.
- `git push --no-verify` et `GSTACK_REDACT_PREPUSH=skip` le contournent.
- Le 2026-09-15, sur ce dépôt public, la poussée `6c3b05c..a0a7880` a affiché
  « 20 MEDIUM finding(s) in pushed diff (PII/internal). Not blocking. » et
  s'est achevée : les 20 alertes n'ont été listées et lues qu'après
  publication, par un scan rejoué à part.
- Depuis le 2026-09-15, `AGENTS.md` fait rejouer ce scan avant `git push` sur
  un dépôt public.

## Question ouverte : les trailers `Claude-Session` d'un dépôt public

Ouverte le 2026-09-15, à trancher ; aucune solution retenue.

- Le dépôt `Yugz29/Pulse` est public.
- 234 des 433 messages de commit d'`origin/main` portent une ligne
  `Claude-Session: https://claude.ai/code/session_…`, pour 18 sessions
  distinctes, du 2026-08-30 au 2026-09-13.
- Les faits `commit` des sessions figées recopient ces messages : 49
  occurrences dans l'arbre d'`origin/main` (`a0a7880`), pour 2 sessions
  distinctes. 44 sont dans six fichiers d'`intelligence/eval/observed/`, 5 dans
  `2026-09-15-benchmark-modeles/comparatif-qwen-gemma.md`, ajoutées par la
  poussée du 2026-09-15.
- Le hook ne lit pas les messages de commit. Sur les lignes ajoutées, son
  détecteur `env.kv` a signalé les 5 lignes du comparatif en MEDIUM (clé
  terminée par « Session »).
- Ce que ces liens ouvrent sans authentification n'est pas établi au
  2026-09-15 ; l'utilisateur le vérifie.
