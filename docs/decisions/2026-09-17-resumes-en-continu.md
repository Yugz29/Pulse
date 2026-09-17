# Résumés en continu : l'état du travail pendant la session

**Date :** 2026-09-17
**Statut :** en cadrage (aucun code ; les points « À trancher » attendent
l'utilisateur)
**Voir :** piste « Résumés dans la journée » (`intelligence/TODOS.md`, P3),
[benchmark de modèles du 2026-09-14](2026-09-14-benchmark-modeles-en-local.md),
[prompt v7](2026-09-12-prompt-v7.md),
[résumés dans le journal](2026-09-13-resumes-dans-le-journal.md),
références oN cliquables (Core 0.8.4.0, #103)

## Principe acté

Un seul produit : **l'état du travail**, visible pendant la session et après.
Deux étages, qui ne se mélangent pas :

- **En journée, des notes jetables.** Elles aident à reprendre après une
  bascule ou une pause. Elles peuvent être fausses, périmées, effacées.
- **La nuit, le résumé v7, qui fait foi.** Il est calculé uniquement sur les
  faits bruts de Core, jamais sur les notes : une note fausse ne contamine
  pas le résumé, et le compteur de l'étape 4 continue de juger la même chose.

Conséquence de construction : une note n'entre jamais dans l'entrée du modèle
de nuit. Le plus sûr est qu'elle n'entre pas non plus dans `trace.db`, dont le
brut est conservé indéfiniment (« Mémoire », `docs/VISION.md`) : jetable et
immuable ne vont pas ensemble.

## 1. Existant

**Ce que la page `GET /` montre déjà en direct, sans modèle** (rendue à chaque
requête, sans script ni rafraîchissement automatique) :

- **Maintenant** : projet probable, workspace, application active, dernière
  commande, fichiers récents, début de la session active, dernière activité
  utile.
- **Faits de reprise** (`build_resume`) : dernier projet observé, dernier
  signal utile, derniers fichiers, dernier test local, et l'état Git local lu
  sur le disque (dernier commit compris).
- **Aujourd'hui** : compteurs du jour (sessions, événements, commandes, tests,
  Git, erreurs, fichiers modifiés, projets, applications).
- **Sessions d'agent** : les événements `agent_session` de la journée (heure,
  résumé figé : outil et première demande, projet), listés à part des
  sessions de travail.
- Puis chaque session de travail du jour avec sa chronologie, et depuis
  0.8.4.0 les zones `Reprise` et `Résumés` avec leurs faits cités.

**Ce que Core sait d'une session en cours, sans modèle** (`/context`,
`current_session`, `context_snapshot._current_session_view`) : identité,
début, dernière activité, durée, nombre d'activités, projets, workspace, et
les **observations ordonnées** (`project_work_observations`) : chronologie de
faits numérotés oN (commandes avec texte, cwd, code et instantané Git ;
commits avec hash, branche, message entier ; fichiers avec leurs transitions
comptées ; verrouillage et veille), applications, `last_observed` (dernière
commande par clé, dernier fait par fichier, dernier état Git) et la table
`sources` oN → `event_id`. Pour une session close récente, Core calcule déjà
un `headline` : commits, fichiers changés, tests en échec, erreurs.

**Ce que Core ne sait pas** : la sortie des commandes, les fichiers d'un
commit, l'état des PR, l'intention. Et l'état net des commandes
(`resolved` / `superseded` / `unresolved_observed`) est calculé côté
Intelligence (`resumption.py`), pas dans Core.

**Limite structurante.** L'identité d'une session est le hash de ses
`event_id` (`session_identity`) : tant que la session est ouverte, elle
change à chaque événement. Rien de durable ne peut être rattaché à l'id d'une
session en cours.

## 2. Récapitulatif sans modèle

**Calculable depuis les faits**, pour la session ouverte, à chaque rendu :

- commits de la session : heure, branche, première ligne du message (même
  affichage que les faits cités de 0.8.4.0, message complet replié) ;
- fichiers : les plus touchés, avec leurs transitions comptées, regroupés par
  dossier ; fichiers créés ou supprimés à part ;
- tests : dernière commande de test, son code, son heure ; nombre d'échecs de
  test dans la session ;
- commandes en échec : dernier échec par couple (commande, cwd) qu'aucune
  réussite de la même commande n'a suivi ; le reste est replié ;
- sessions d'agent terminées dans la fenêtre de la session : outil, bornes,
  première demande ;
- bornes, durée, pauses (verrouillage, veille), branche courante.

Chaque ligne est un fait oN, donc cliquable et vérifiable comme en 0.8.4.0.

**Ce qu'il ne peut pas dire** : ce que la session cherchait à faire ; ce qui
relie dix fichiers et trois commits ; si un échec compte encore ; ce qui
reste ouvert au sens d'une intention (un commit qui déclare « reste à… »
n'est qu'une ligne parmi d'autres) ; où l'on s'est arrêté, autrement que par
« dernier fait observé ». Il ne hiérarchise pas : sur une session de 150
activités, il liste.

**Ce qu'il a pour lui** : exact par construction, instantané, sans mémoire
occupée, sans dépendance à Intelligence, sans risque de contaminer quoi que
ce soit. Le jour 13 l'a montré : le lecteur ne se souvient pas de ses
sessions et juge sur les faits ; des faits bien rangés sont déjà une reprise.

## 3. Petit modèle

**La tâche minimale qui ajoute quelque chose au point 2** : dire en une ou
deux phrases **le fil** de la session en cours (ce qui relie les faits) et,
au plus, **un point d'attention**, chacun appuyé sur des références oN
obligatoires. Pas de `stopped_at` (le point 2 le donne), pas de
`central_files`, pas de `structured`, pas de `confidence`. Validation
identique à v7 : toute référence doit exister dans l'entrée, sinon la note
est jetée, sans nouvelle tentative. Affichage sous le récapitulatif, marqué
« note du modèle, jetable », références liées par la table de sources de la
note (mécanisme de #103).

**Contraintes.**

- **Mémoire.** M3 Max 36 Go ; le modèle de nuit a un pic mesuré de 23,9 Go et
  une médiane de 43,4 s par session (benchmark du 14, tableau des résultats).
  Il ne peut pas rester chargé pendant le travail, et la Vision l'interdit
  (« maintenir en permanence le plus gros modèle possible en mémoire »). Le
  modèle de jour doit tenir dans 3 à 6 Go, poids et cache compris.
- **Pas de chevauchement avec le lot de nuit.** Le lot de 06:30 charge 24 Go :
  le processus de jour ne doit pas tenir de modèle à ce moment. Deux gardes :
  le verrou d'état qu'Intelligence pose déjà (`state.json.lock`,
  `StateLocked`), partagé par les deux passages ; et la règle que
  `run-benchmark.sh` applique depuis le 15 (ne rien lancer tant que
  `com.pulse.intelligence-run` tourne).
- **Leçon du benchmark à reprendre.** Un candidat plus rapide a été écarté sur
  un défaut de contenu (Gemma 4 26B-A4B : preuve qui ne porte pas le texte ;
  Ministral 3 14B : 10 sorties valides sur 14). « Valide » n'est pas
  « juste » : le validateur vérifie que la preuve existe, pas que le texte la
  décrit. Un modèle plus petit fera pire sur ce point ; la tâche réduite
  (une phrase, peu de références) est la seule parade, et la lecture humaine
  reste le juge.

**Candidats à mesurer plus tard** (rien n'est téléchargé ni lancé ; tailles
lues sur les fiches, à revérifier au téléchargement) :

| Candidat | Disque | Architecture (mlx-lm 0.31.3) | Pourquoi |
| --- | --- | --- | --- |
| `mlx-community/Qwen3.5-4B-MLX-4bit` | ≈ 2,9 Go | `qwen3_5`, hybride 3:1 comme la production (32 couches) | Même famille et même gabarit que le modèle de nuit ; réflexion active par défaut, coupée par `enable_thinking=False`, ce que le provider MLX fait déjà. Converti avec mlx-vlm : chargement par `mlx_lm.load` à vérifier. |
| `mlx-community/Qwen3-4B-Instruct-2507-4bit` | 2,26 Go | `qwen3`, attention pure | Sans réflexion, converti avec mlx-lm ; seul candidat dont le cache se rogne (point 5). Génération plus ancienne (2025). |
| `mlx-community/Qwen3.5-9B-MLX-4bit` | à relever | `qwen3_5`, hybride | Borne haute : ce que coûte le cran au-dessus, si le 4B est trop faible. |

Non retenus pour l'instant : Qwen3.5-2B et 0.8B (la tâche demande de suivre
des références dans 3 000 à 15 000 tokens d'entrée ; à n'essayer que si le 4B
passe largement) ; `gemma-4-e4b-it` 4 bits (≈ 6,3 Go sur disque, et la
famille a été écartée le 15 sur un défaut de contenu).

**Protocole de mesure, plus tard** : celui du 14, inchangé (corpus
`eval/observed`, un modèle en mémoire à la fois, secteur, `caffeinate`, pic
par `/usr/bin/time -l`), avec un prompt de note dédié, et en plus le pic
mémoire **pendant une session de travail réelle**, qui est la contrainte
nouvelle.

## 4. Déclencheur

Core ne pousse rien vers Intelligence (une panne d'Intelligence ne doit pas
toucher la collecte). Le déclencheur est donc **un tick bon marché côté
Intelligence** (launchd, `StartInterval`, de l'ordre de 5 min) qui lit
`/context` et ne génère que si une condition nouvelle est vraie :

- **un commit de plus** dans la session en cours : le meilleur signal, c'est
  une unité de sens déclarée par l'utilisateur ;
- **une session d'agent terminée** (`last_agent_session.event_id` nouveau) ;
- **à défaut, un intervalle** : au moins N faits nouveaux depuis la dernière
  note et au moins 20 à 30 min écoulées. Jamais une note pour une note : la
  Vision écarte « une simple notification générée périodiquement ».

Gardes : **secteur seulement** (`pmset -g batt` ; le benchmark a vu la
batterie se décharger sur secteur avec le 27B, mesure à refaire avec un 4B) ;
pas pendant le lot de nuit (verrou) ; session trop courte ou sans fait
nouveau, rien.

**Identité qui change.** La note ne se rattache pas à l'id de la session
ouverte. Elle porte l'instant de début de session, l'ensemble des `event_id`
de ses sources (la table oN → `event_id`, comme un résumé) et l'instant du
dernier fait lu. À l'affichage : si toutes ses sources appartiennent encore à
la session ouverte, elle est montrée avec « à jour jusqu'à HH:MM » ; sinon
(session fermée, scindée par le seuil avant split, journée changée) elle
n'est plus montrée. À la fermeture de la session, les notes ne servent plus :
le résumé de nuit prend le relais, sans les lire.

## 5. Cache KV : réutilisation d'un préfixe

Lu dans mlx-lm 0.31.3 installé (`models/cache.py`, `generate.py`,
`cache_prompt.py`, `models/qwen3_5.py`), sans exécuter de modèle.

- **Ce que mlx-lm offre.** `generate` et `stream_generate` acceptent
  `prompt_cache` ; `make_prompt_cache`, `save_prompt_cache` et
  `load_prompt_cache` construisent, écrivent et relisent un cache ;
  `mlx_lm.cache_prompt` en fait un fichier, et « the cached prompt is treated
  as a prefix to the supplied prompt » (README de mlx-lm). Le provider MLX de
  Pulse ne passe aucun cache aujourd'hui.
- **Qwen3.8-27B est hybride.** Son `config.json` local donne `model_type`
  `qwen3_5`, 64 couches, `full_attention_interval` 4 : 48 couches
  d'attention linéaire et 16 d'attention complète. `make_cache` rend
  `ArraysCache(size=2)` pour les premières et `KVCache()` pour les secondes.
  `ArraysCache` hérite de `_BaseCache.is_trimmable()`, qui rend `False` ;
  `can_trim_prompt_cache` exige que toutes les couches soient rognables :
  pour ce modèle, il rend toujours `False` et `trim_prompt_cache` ne rogne
  rien. L'état récurrent d'une couche linéaire ne se rembobine pas.
- **Donc : réutiliser un préfixe exact, oui ; revenir en arrière, non.** Un
  cache arrêté exactement à la fin d'un préfixe peut être copié
  (`copy.deepcopy`, comme le fait `LRUPromptCache.fetch_nearest_cache` dans
  ses branches « exact » et « shorter ») puis prolongé par une suite. Un
  cache qui a dépassé le préfixe (une génération a eu lieu) ne peut pas y
  être ramené : la branche « longer », qui rogne, est fermée aux hybrides.
  Il faut garder une copie intacte prise à la frontière. C'est le constat
  public : réutilisation de préfixe inopérante par rognage sur les hybrides
  (issue mlx-lm #980, Qwen 3.5 : aucun gain, le prompt est recalculé) ; la
  parade décrite par LM Studio est un jeu d'instantanés du cache à des
  frontières fixes, qui ne sert que des préfixes exacts.
- **Candidats.** `qwen3_5` (Qwen3.5-4B et 9B) : même régime que la
  production. `qwen3` (Qwen3-4B-Instruct-2507) : pas de `make_cache`, donc
  `KVCache` partout, rognable ; préfixe réutilisable dans les deux sens.
  Gemma (`gemma3_text`, `gemma4_text`) : `RotatingKVCache` sur les couches à
  fenêtre glissante, rognable seulement tant que `offset < max_size`.
- **Ce que ça vaut pour Pulse.** Deux préfixes candidats. (a) Les
  instructions du prompt, identiques à chaque appel : environ 5 Ko pour v7,
  soit une petite part d'une entrée de 3 000 à 15 000 tokens ; gain réel
  mais modeste, et la coupe doit tomber sur une frontière de message du
  gabarit de conversation pour que les tokens du préfixe soient identiques.
  (b) Les faits de la session, qui ne font que s'allonger : c'est là qu'est
  le gain, mais l'entrée actuelle n'est pas en ajout seul (`serialize_input`
  trie les clés, un fait `file` antérieur change quand son compteur monte,
  `last_observed` et `resumption` bougent à chaque fait). Il faudrait une
  entrée de note conçue en ajout seul (faits dans l'ordre, agrégats mobiles à
  la fin) et, pour un hybride, un instantané du cache à chaque note. Coût
  mémoire de l'instantané pour la production, calculé sur sa configuration :
  16 couches × 2 × 4 têtes KV × 256 × 2 octets ≈ 64 Ko par token, soit
  ≈ 0,3 Go pour 5 000 tokens, plus l'état fixe des 48 couches linéaires.
- **Conclusion.** Le cache n'est pas un préalable. À 4B, le prefill d'une
  entrée de quelques milliers de tokens se compte en secondes : mesurer
  d'abord sans cache, n'y revenir que si la latence gêne. Si le cache devient
  un critère, il avantage le candidat à attention pure.

## 6. Contrat

| Surface | Étapes 1 et 2 (sans modèle, dans Core) | Étape 4 (notes du modèle) |
| --- | --- | --- |
| `GET /context`, `/context/sessions` | inchangés : le récapitulatif se calcule au rendu de la page, depuis les mêmes observations | inchangés ; le tick ne fait que les lire |
| Format d'export du journal | inchangé (page HTML seulement, comme 0.8.1.0 et 0.8.4.0) | inchangé si les notes restent hors `trace.db` |
| Identité de session, `reconstruction_version` | inchangées | inchangées ; la note s'en passe (point 4) |
| Version des observations | inchangée | inchangée |
| Schéma de `trace.db` | inchangé | inchangé si les notes restent hors `trace.db`. **Touché** si l'on en fait un type d'événement (`session_note`) : types acceptés à l'ingestion, export, et surtout rétention infinie d'un contenu voulu jetable |
| Entrée du résumé de nuit | inchangée | inchangée, à garantir par un test : aucune note dans `build_model_input` |

Seule l'option « note = événement dans `trace.db` » touche un contrat ; elle
exigerait une note datée, un bump et la mise à jour des consommateurs. Elle
n'est pas recommandée.

## 7. Plan par étapes

1. **Récapitulatif sans modèle de la session en cours, dans la page.** Core
   seul, lecture seule : sous « Maintenant », un bloc « Session en cours »
   qui range les faits de la session ouverte comme au point 2 (commits,
   fichiers, tests, échecs bruts, sessions d'agent),
   chaque ligne ancrée sur son fait comme en 0.8.4.0. Aucun stockage, aucun
   modèle, aucun contrat ; tests de rendu ; bump de version et relance du
   daemon. C'est la plus petite étape utile : elle sert dès le premier jour
   et elle dit, à l'usage, ce qui manque vraiment.
2. **Usage pendant quelques jours** et consignation dans
   `docs/dogfooding.md`, une ligne par jour : « ce qui m'a manqué dans
   Session en cours ». C'est ce relevé qui
   justifie, ou non, l'étape 4.
3. **Mesure des candidats**, protocole du 14 plus le pic mémoire pendant le
   travail ; prompt de note dédié, court ; verdict à la lecture humaine.
   Aucun code de production.
4. **Notes du modèle** : tick launchd côté Intelligence, gardes (secteur,
   verrou du lot, conditions du point 4), notes hors `trace.db`, affichées
   sous le récapitulatif, jetées à la fermeture de la session ; test qui
   garantit qu'aucune note n'atteint l'entrée de nuit.
5. **Cache de préfixe**, seulement si la latence mesurée à l'étape 4 gêne.

## Décisions du 2026-09-17 (utilisateur)

- **L'étape 1 part seule** : bloc `Session en cours`, Core 0.8.5.0.
- **Pas de logique d'état net des commandes dans Core.** Les échecs
  s'affichent bruts, avec leur code et leur heure, sans conclure « résolu ».
  Le déplacement de `resumption.py` dans Core rejoint le TODO
  « Classification des sessions à source unique » (`core/TODOS.md`) : même
  dette, une règle tenue en deux copies entre Core et Intelligence. Le
  point 2 ci-dessus, qui parlait d'« échec qu'aucune réussite n'a suivi »,
  est donc remplacé par : tous les échecs de la session, bruts.
- **Reportés après l'étape 2** : emplacement des notes du modèle, mesure des
  candidats, déclencheur.
- **Étape 2** : une ligne par jour dans `docs/dogfooding.md`, « ce qui m'a
  manqué dans Session en cours ».

Des cinq points ci-dessous, les points 2 et 3 sont tranchés ; les points 1,
4 et 5 attendent la fin de l'étape 2.

## À trancher par l'utilisateur

1. **Où vivent et où s'affichent les notes du modèle** (étape 4). Option
   recommandée : hors `trace.db`, dans un dossier jetable d'Intelligence, que
   la page de Core lit si elle le trouve et ignore sinon (Core reste
   autonome, mais lit un format d'une autre couche). Autres options : une
   page servie par Intelligence (deux pages) ; un type d'événement dans
   `trace.db` (touche le contrat, contredit « jetable »).
2. **L'étape 1 part-elle seule ?** Recommandé : oui, et l'étape 4 n'est
   lancée que si le relevé de l'étape 2 montre un manque que seul un modèle
   comble.
3. **État net des commandes.** Le récapitulatif a besoin de « échec non suivi
   d'une réussite ». Soit une règle minimale dans Core (même commande, même
   cwd), soit le déplacement de `resumption.py` dans Core, ce qui rejoint le
   TODO « Classification des sessions à source unique ». Recommandé pour
   l'étape 1 : la règle minimale, affichée comme telle.
4. **Liste des candidats et moment de la mesure** (téléchargements de 2 à
   6 Go chacun ; secteur ; hors lot).
5. **Cadence et gardes du tick** : 5 min, secteur seulement, seuils de
   l'intervalle ; processus à la demande (le modèle se charge à chaque note)
   ou résident pendant les heures de travail.

## Sources

- Code lu : `core/daemon_v2/renderers/html.py`, `context_snapshot.py`,
  `work_observations.py`, `analysis/timeline.py` ;
  `intelligence/pulse_intelligence/llm/mlx.py`, `resumption.py`,
  `session_input.py` ; mlx-lm 0.31.3 (`models/cache.py`, `generate.py`,
  `cache_prompt.py`, `models/qwen3_5.py`, `qwen3.py`, `gemma3_text.py`,
  `gemma4_text.py`) ; `config.json` local de
  `mlx-community/Qwen3.8-27B-4bit`.
- README de mlx-lm, section sur le cache de prompt :
  <https://github.com/ml-explore/mlx-lm/blob/main/README.md>
- Issue mlx-lm #980, « Prefix cache reuse is broken for all
  hybrid-architecture models » : <https://github.com/ml-explore/mlx-lm/issues/980>
- LM Studio, « Improving LM Studio's MLX Engine for Agentic Workflows »
  (2026-06-05), instantanés du cache pour les hybrides :
  <https://lmstudio.ai/blog/mlx-engine-agentic-workloads>
- Fiches des candidats : <https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit>,
  <https://huggingface.co/Qwen/Qwen3.5-4B>,
  <https://huggingface.co/mlx-community/Qwen3-4B-Instruct-2507-4bit>,
  <https://huggingface.co/mlx-community/Qwen3.5-9B-MLX-4bit>,
  <https://huggingface.co/mlx-community/gemma-4-e4b-it-OptiQ-4bit>
- Limite : les pages web ont été lues par un outil de synthèse, pas
  vérifiées ligne à ligne ; les tailles et l'état de l'issue #980 sont à
  revérifier avant de s'y appuyer. Tout ce qui concerne le cache vient
  d'abord du code installé.
