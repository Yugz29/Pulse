# Benchmark de modèles : le verdict se prend en local

**Date :** 2026-09-14
**Statut :** tranchée ; benchmark passé le 2026-09-15, choix du modèle en
attente du jugement humain
**Voir :** [modèle local du 2026-09-06](2026-09-06-modele-local-qwen.md),
[température explicite](2026-09-14-temperature-explicite.md)

## Décision

Le modèle du résumé de session se départage en local, en MLX 4-bit, sur le
corpus `intelligence/eval/` (`observed/`, 14 sessions). Deux candidats et un
étalon :

- **`gemma-4-26b-a4b-it`** (`mlx-community/gemma-4-26b-a4b-it-4bit`,
  15,4 Go) : 3,8 Md de paramètres actifs, réflexion sur demande.
- **`Ministral-3-14B-Instruct-2512`**
  (`mlx-community/Ministral-3-14B-Instruct-2512-4bit`, 8,5 Go) : dense.
- **Étalon** : le modèle de production, `mlx-community/Qwen3.8-27B-4bit`,
  rejoué sur le même corpus.

## Pourquoi pas de dépistage à distance

Le dépistage devait d'abord passer par le routeur distant. Sur les cinq
candidats initiaux, trois ne sont plus servis en serverless : Llama 3.1 8B,
Mistral Nemo et Gemma 3 27B. Deux d'entre eux, dont Gemma 3 27B, sont routés
en silence vers un autre modèle : on mesurerait Gemma 4 en croyant mesurer
Gemma 3. Le passage ne le montrerait pas, car le `meta.json` d'`eval` inscrit
l'identifiant demandé, pas le modèle servi.

## Candidat écarté après chiffrage

`qwen3.6-35b-a3b` : pic estimé à 23-25 Go, contre 21,6 Go mesurés le
2026-09-14 pour le modèle de production. Il demanderait donc plus de mémoire
qu'aujourd'hui. Sa réflexion est active par défaut, et sa fiche le destine à
l'agent et au code.

## Avertissement `fix_mistral_regex` sur Ministral : faux positif

- **Faux positif.** transformers 5.16.1 annonce une tokenisation fausse en ne
  lisant que `config.json` : `transformers_version` y vaut `5.0.0.dev0`,
  antérieur à `5.0.0` selon PEP 440. La regex de `tokenizer.json` est déjà le
  `pattern` de `tekken.json`, celle que le drapeau substituerait. Le drapeau
  n'est passé nulle part : sur une copie de Gemma 4 ou de Qwen privée de
  `transformers_version`, il change la tokenisation (16 et 7 textes sur 16).
- **Mesure du 2026-09-15.** Avec et sans `fix_mistral_regex=True`, même
  tokenizer sérialisé et mêmes identifiants de tokens pour Ministral, Gemma 4
  et le Qwen de production, sur les 14 sessions d'`eval/observed`, le prompt
  v7 et une ligne d'essai (environ 300 000 tokens par modèle).
- **Rejeu.** transformers 5.16.1, tokenizers 0.23.2, mlx-lm 0.31.3, hors
  ligne : `corpus/docs/audits/2026-09-15-benchmark-modeles/regex_flag.py`
  charge chaque tokenizer par `mlx_lm.utils.load_tokenizer`, avec et sans le
  drapeau, et compare `backend_tokenizer.to_str()` et les identifiants.
- **Limite.** Aucune comparaison avec `mistral-common`, non installé : la
  concordance avec le tokenizer de référence de Mistral repose sur l'identité
  des regex, pas sur une tokenisation mesurée contre lui.

## Résultats du 2026-09-15

Passage complet de 10:09 à 10:32, un modèle en mémoire à la fois, prompt v7
sur les 14 sessions d'`eval/observed`. **Verdict en attente du jugement de
l'utilisateur ; la production reste sur `mlx-community/Qwen3.8-27B-4bit`.**

| | Qwen3.8-27B (étalon) | Gemma 4 26B-A4B | Ministral 3 14B |
| --- | --- | --- | --- |
| Sorties valides | 14/14 | 13/14 | 10/14 |
| Attentes annotées (journal d'`eval`) | 3/4 | 2/4 | 2/4 |
| dont atteignables en v7 | 3/3 | 2/3 | 2/3 |
| Génération, somme des 14 sessions | 739 s | 143 s | 467 s |
| Génération, médiane par session | 43,4 s | 8,7 s | 27,7 s |
| Durée du processus (`real`) | 744 s | 148 s | 470 s |
| Pic mémoire | 23,9 Go | 19,3 Go | 17,1 Go |
| Tokens d'entrée / de sortie | 77 696 / 4 066 | 82 926 / 3 419 | 80 608 / 5 784 |
| Code de sortie d'`eval` | 0 | 1 | 1 |

- **Attentes atteignables.** Sur `eef4956b`, l'attente est un point
  `carried_over` repris de `previous_summary:1` ; v7 ne reçoit plus d'annexe
  (`uses_annexes("v7")` est faux), aucun modèle ne peut la satisfaire.
- **Mesures.** Validité, durées de génération et tokens viennent des
  `meta.json`, tokens comptés par le tokenizer de chaque modèle ; attentes
  recalculées par `compare_run` sur les sorties. Durée du processus et pic
  viennent de `/usr/bin/time -l` (`real`, `peak memory footprint` en octets,
  ici en Go décimaux), pris de la même façon pour les trois. Ce pic ne se
  compare pas tel quel aux 21,6 Go cités plus haut, dont la méthode n'est pas
  consignée. Toutes ces preuves sont versionnées (voir « Rejeu ») et
  redonnent chaque chiffre du tableau.

### Rejets

- **Gemma, `2ce34456`** (work-3 du 2026-08-22) : `structured.central_files:
  devops_culture_git/README.md absent de l'entrée`. La session n'a aucun fait
  `file` ; le chemin figure tel quel dans la commande o14 (quatre lignes
  `git add` et `git commit`, code 1). Le rejet tombe sur le TODO ouvert
  « `central_files` n'accepte que les faits `file` » (`intelligence/TODOS.md`,
  P3, « à décider, pas à implémenter »), même cas que le rejet de work-5
  `057a0f56` du 2026-09-11 au lot du 12 (`config.yml`, cité dans trois
  commandes). **Tant que cette règle n'est pas tranchée, ce rejet ne compte
  pas comme un défaut du modèle, et 13/14 ne se compare pas à 14/14 sur ce
  point.** Repassée au validateur sans modèle, en admettant les chemins cités
  tels quels dans une commande observée, cette sortie est valide, point
  `open` faux compris (voir « Écarts de contenu »).
- **Ministral bute au même endroit** sur `2ce34456`
  (`devops_culture_git/0-environment.md`, même commande o14) ; au même rejeu,
  sa sortie est valide, alors que son premier point `open` situe o7 « dans un
  répertoire de téléchargement » (o7 tourne dans `devops_culture_git`). Ses
  trois autres rejets sortent de ce cas :
  - `1e420dda` : `central_files` cite le dossier `intelligence/llm/` en chemin
    absolu, absent de l'entrée sous cette forme ; `intelligence/llm/`
    n'apparaît que dans le message du commit o3. `eval` tronque la sortie
    brute à 2 000 caractères : elle ne se rejoue pas.
  - `6a416635` : `open[0]` cite l'échec o20 (`git add vue/ .gitignore`,
    code 128), `superseded_observed` par o23.
  - `7bbaca78` : `open[0]` est un `recorded_statement` dont la citation vient
    du message d'un tag, dans la commande o5, pas d'un message de commit.

### Écarts de contenu

Gemma a deux écarts de contenu :

- **Attente manquée sur `1e420dda`** (work-26 du 2026-09-05) : le point
  observé sur le commit `f30781f` (« consigner la divergence list/run sur le
  modèle »). Qwen le rend en `recorded_statement` avec la citation du commit,
  Gemma laisse `open` vide : 2/3 contre 3/3. Ministral manque la même
  attente, sa sortie sur `1e420dda` étant rejetée.
- **Preuve qui ne porte pas le texte, sur `2ce34456`** (sortie rejetée) : le
  deuxième point `open` décrit l'échec o10 (`bash check-setup.s`, code 127,
  `superseded_observed` par o11) en citant comme preuve o14 (quatre lignes
  `git add` et `git commit`, code 1, `unresolved_observed`). Le validateur
  vérifie que la preuve est un dernier échec non résolu, pas que le texte la
  décrit.

Quatre points `open` valides, deux de Gemma et deux de Qwen, disent plus que
leur preuve ; la vérification est symétrique et ne départage pas les
modèles : ils sont versés à « Citation de `command_failure` non littérale »
(`intelligence/TODOS.md`), exemple type Gemma sur `8faf4569`.

**Conséquence pour le TODO `central_files`.** Assouplir la règle ferait
passer la sortie de Gemma sur `2ce34456` telle quelle, point faux compris :
repassée au validateur en admettant les chemins cités tels qu'écrits dans une
commande observée, elle est valide. Le rejet a protégé la production par
accident, pas par justesse. Ce constat ne tranche pas le TODO, mais il
appartient à la décision qui le tranchera ; la forme d'admission mesurée sur
ce cas est versée à l'entrée du TODO.

### Conditions observées

- **Machine et code.** Apple M3 Max, 36 Go ; main à `6c3b05c`, mlx-lm
  0.31.3, mlx 0.32.2, transformers 5.16.1, hors ligne. Config de production où
  seul `model_id` change : prompt v7, `llm_max_tokens` 2048, température 0.0,
  plafond d'entrée 30 000.
- **Déroulé.** Relance complète du passage lancé le 15 à 00:56 et arrêté à
  01:00 à la demande, pendant l'étalon. Le lot launchd du jour avait fini à
  09:48 : aucun autre modèle en mémoire. Avant la relance, `run-benchmark.sh`
  a été corrigé : il journalisait toujours `exit=0` (`$?` lu après un
  `$(date)`), et il reporte désormais aussi un passage tant que
  `com.pulse.intelligence-run` tourne.
- **Alimentation et veille.** Lancé au branchement du secteur (10:09:14),
  capot ouvert, sous `caffeinate -i` ; aucune transition de veille dans
  `pmset -g log` entre 09:46 et 10:37. **Batterie déchargée sur secteur** :
  79 % à 10:09 et 65 % à 10:33, sur secteur et en charge aux deux relevés ;
  le chargeur de 68 W ne couvre pas la charge d'inférence.
- **Corpus antérieur à la reconstruction courante.** Les 14 sessions sont
  figées en reconstruction 2 (observations v1, contexte schéma 2) ; le Core de
  production sert la reconstruction 4 au schéma 3, et `eval` l'a signalé à
  chaque passage. Les trois modèles lisent la même entrée, qui n'est pas la
  vue servie aujourd'hui.
- **Tokenizer.** L'avertissement `fix_mistral_regex` s'affiche au chargement
  de Ministral ; le drapeau n'est pas passé (faux positif, section
  précédente).

### Rejeu

- **Preuves versionnées**, sous
  [`docs/audits/2026-09-15-benchmark-modeles/`](../audits/2026-09-15-benchmark-modeles/) :
  les 14 sorties et le `meta.json` de chaque modèle (`out/`), l'extrait
  `time-l.txt` de `run.log` (sortie de `/usr/bin/time -l` des trois
  passages) et le comparatif.
- **Hors dépôt**, dans `corpus/docs/audits/2026-09-15-benchmark-modeles/` :
  `run.log`, configs, `run-benchmark.sh` (`caffeinate -i ./run-benchmark.sh
  >> run.log 2>&1`), `comparatif.py`, `revalider-chemins-commande.py`,
  paramètres dans le README.
- Rejets `central_files` repassés au validateur sans modèle :
  `cd intelligence && .venv/bin/python ../corpus/docs/audits/2026-09-15-benchmark-modeles/revalider-chemins-commande.py`.
- Matière du jugement : `comparatif-qwen-gemma.md`, les 13 sessions valides
  des deux côtés, sorties côte à côte, sans verdict ; en annexe, `2ce34456`
  avec la sortie rejetée de Gemma, hors compte, o10, o11 et o14 résolus.
  Regénéré depuis `intelligence/` :
  `.venv/bin/python ../corpus/docs/audits/2026-09-15-benchmark-modeles/comparatif.py > ../docs/audits/2026-09-15-benchmark-modeles/comparatif-qwen-gemma.md`.

### Un changement de modèle relance le compteur de l'étape 4

`model_id` entre dans l'identité d'un résumé : `summary_event_id` hache la
session, la version de prompt et le modèle
(`intelligence/pulse_intelligence/session_summary.py`), et la sélection ne
tient une session pour résumée que sous le même triplet (`selection.py`). Un
autre modèle produit donc d'autres résumés, y compris pour les sessions encore
dans `lookback_days`. **Un changement de modèle relance le compteur de
l'étape 4** (spec du 2026-09-03, §12, repris par la décision du 2026-09-12 sur
v7) : la décision de modèle doit être datée avant d'accumuler des jours de
compteur, pas après.
