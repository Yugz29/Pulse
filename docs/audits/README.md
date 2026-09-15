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
  un dépôt public. Rejoué avant la poussée `a0a7880..d8872b6`, il a levé une
  alerte, lue et classée fausse par l'utilisateur avant l'envoi ; le hook a
  ensuite affiché la même : « 1 MEDIUM finding(s) ».
- Cette alerte vient du détecteur `internal.hostname` (« Internal hostname
  (*.internal/.corp/.local/.prod/.staging) ») sur `settings.local`, dans le
  nom de fichier `.claude/settings.local.json`. Il signale tout nom de la
  forme `nom.<suffixe>` pour six suffixes (`local`, `internal`, `corp`, `lan`,
  `prod`, `staging`), sans distinguer un nom de fichier d'un nom d'hôte et
  sans tenir compte de la casse. Mesuré le 2026-09-15 : alerte sur
  `settings.local.json`, `printer.local`, `env.local`, `docker-compose.prod.yml`,
  `config.staging.json`, `api.internal`, `nas.lan`, `foo.corp`. Sa seule
  exception est `.env.<suffixe>` précédé d'un point (`.env.local`,
  `.env.staging`, `.env.prod` : aucune alerte) ; un nom précédé d'un tiret bas
  (`my_settings.local`) échappe aussi au motif.
- Avant ce passage, l'arbre suivi ne contenait qu'une chaîne de cette forme,
  celle-là ; les exemples ci-dessus en ajoutent dix, que la poussée
  `d8872b6..f2fd0cd` a signalées. Toute nouvelle ligne poussée qui cite un tel
  nom de fichier lèvera la même alerte.
- **Exception décidée par l'utilisateur le 2026-09-15 :** un texte qui
  documente un détecteur déclenche ce détecteur. La règle de soumission des
  alertes ne s'applique pas aux passages qui décrivent le hook lui-même. Les
  10 alertes de la poussée `d8872b6..f2fd0cd`, dues aux exemples ci-dessus,
  ont été classées fausses d'avance, sans lecture de la liste, après
  vérification que le scan rejoué n'en levait pas d'autre. Ce fichier porte
  aussi d'autres questions, qui restent soumises à la règle. L'exception est
  écrite ici, pas dans `AGENTS.md`, où vit la règle.

## Question ouverte : les trailers `Claude-Session` d'un dépôt public

Ouverte le 2026-09-15 ; requalifiée le même jour en question d'hygiène, pas
de sécurité.

- Le dépôt `Yugz29/Pulse` est public.
- 234 des 433 messages de commit d'`origin/main` portent une ligne
  `Claude-Session: https://claude.ai/code/session_…`, pour 18 sessions
  distinctes. Premier trailer le 2026-08-30 (`b2123e5`, 15:49 +0200),
  dernier le 2026-09-13 (`0d4a864`, écrit à 22:10 +0200, commité à 22:42).
- **Test de l'utilisateur, le 2026-09-15** : ouvert hors session, un lien
  `Claude-Session` demande une authentification. Le contenu des sessions
  n'est pas exposé.
- **Ce qui reste : des métadonnées.** Un identifiant `session_…` est
  persistant : deux commits qui portent le même viennent de la même session.
  Les 234 commits à trailer exposent ainsi le découpage de ce travail en 18
  sessions ; avec les dates de commit, publiques pour les 433, ils en exposent
  aussi le rythme.
- **Sans objet depuis le test, conservé :** visibilité sur cette fenêtre. Le
  dépôt est public à chacun des événements que l'API GitHub rend encore, du
  2026-09-03 au 2026-09-14, sans passage de privé à public entre-temps (aucun
  `PublicEvent`). Les événements antérieurs ne sont plus disponibles : 67 des
  234 commits (du 2026-08-30 au 2026-09-03) étaient déjà sur le distant avant
  la plus ancienne poussée visible (2026-09-03, 20:04 UTC), et la visibilité
  du dépôt au moment de leur publication n'est pas établie.
- Les faits `commit` des sessions figées recopient ces messages : 49
  occurrences dans l'arbre d'`origin/main` (`a0a7880`), pour 2 sessions
  distinctes. 44 sont dans six fichiers d'`intelligence/eval/observed/`, 5 dans
  `2026-09-15-benchmark-modeles/comparatif-qwen-gemma.md`, ajoutées par la
  poussée du 2026-09-15.
- Aucun contrôle local n'a lu ces messages avant publication. Le hook de
  pré-poussée ne scanne jamais les messages de commit (et n'existe que depuis
  le 2026-08-31, 00:14). Les trois règles de poussée d'`AGENTS.md` portent sur
  le diff, pas sur les messages. Seules les 5 lignes du comparatif, parce
  qu'elles sont dans le diff, ont été signalées en MEDIUM par le détecteur
  `env.kv` (clé terminée par « Session »).
- **Sans objet depuis le test, conservé :** côté GitHub, `secret_scanning` et
  `secret_scanning_push_protection` sont activés sur le dépôt au 2026-09-15,
  date d'activation inconnue. La page « About secret scanning » décrit une
  recherche d'identifiants connus dans l'historique Git ; elle ne dit pas si
  les messages de commit sont lus.
- Origine : Claude Code ajoute ce lien aux commits des sessions web et
  Remote Control (réglage `attribution.sessionUrl`, vrai par défaut). Les
  transcripts locaux portent la consigne dans les sessions CLI du 2026-09-05
  au 2026-09-13 ; 199 des 234 commits ont été créés dans ce dépôt local. Aucun
  trailer depuis le 2026-09-14 (sessions de l'application de bureau). Le
  2026-09-15, `attribution.sessionUrl` est passé à `false` dans
  `.claude/settings.local.json`, hors dépôt ; aucun commit existant n'est
  modifié.
- **Décision de l'utilisateur, le 2026-09-15** : aucune réécriture
  d'historique ni nettoyage rétroactif ; le réglage local reste en place,
  rien à versionner.
