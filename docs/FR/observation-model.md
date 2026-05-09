# Pulse — Modèle d'observation (Niveau 1)

Ce document définit le contrat d'observation de Pulse.

Il répond à une question précise :
> Que doit observer Pulse, avec quelle confiance, quelle sensibilité, et ce que chaque source peut ou ne peut pas déclencher seule ?

Il ne décrit pas le pipeline runtime (voir `architecture.md`).
Il ne décrit pas le contrat de mémoire (voir `semantic_contract.md`).
Si le code et ce document divergent, le code a raison.

---

## 0. Principe

Pulse n'observe pas tout ce qu'il pourrait observer.
Pulse observe ce qui aide à comprendre le travail réel, avec minimisation et prudence.

Trois règles de fond :

- **Présence ≠ travail.** Un utilisateur présent devant son Mac ne travaille pas nécessairement. Un outil actif ne signifie pas que l'utilisateur travaille.
- **Observation ≠ certitude.** Une observation, même forte, est une preuve partielle. Une seule observation peut déclencher un signal ou un épisode faible, mais ne doit pas être présentée comme une certitude forte sans corroboration. Plusieurs observations convergentes renforcent la confiance.
- **Sensibilité par défaut.** En cas de doute sur la sensibilité d'une source, elle est traitée comme sensible.

---

## 1. Sources observées

### 1.1 Fichiers

**Type d'events :** `file_created`, `file_modified`, `file_renamed`, `file_deleted`, `file_change`

**Producteur :** client Swift via FSEvents → POST `/event`

**Payload principal :** `path`, projet implicite dérivé du chemin, `_actor`, `_noise_policy`

**Sensibilité :** moyenne. Les chemins peuvent révéler la structure d'un projet privé.

**Persisté :** oui, si l'event passe le filtre `_noise_policy`. Les chemins techniques et certains chemins sensibles connus sont filtrés avant persistance. Les fichiers de credentials explicites (`.env`, `id_rsa`, `credentials.json`, etc.) devraient être traités comme noise/sensitive et ne pas influencer le présent — ce filtre n'est pas encore exhaustif et peut être renforcé.

**Ce que cette source peut faire :**
- ancrer le projet actif
- ancrer le fichier actif
- contribuer à `activity_level` et `probable_task`
- ouvrir un work block si l'actor est `user` ou `unknown`

**Ce que cette source ne peut pas faire seule :**
- prouver que l'utilisateur est actif (un outil peut générer des centaines de file events sans présence utilisateur)
- justifier à elle seule une nouvelle session de travail significative

**Notes :**
- `_actor=tool_assisted` indique que le fichier a été modifié par un outil (Codex, Cursor, etc.). Ces events contribuent au contexte mais ne gonflent pas `edited_file_count_10m`.
- `_actor=system` et les chemins techniques (`.git`, `node_modules`, `DerivedData`, `.venv`, caches, `.wal`, `.db`, logs, `tmp`, chemins `/var`, `/private`, UUID, hash git) sont filtrés avant toute influence sur le présent.
- Un file event `tool_assisted` peut contribuer à un épisode de travail assisté, mais ne doit jamais être compté comme une édition utilisateur directe.

---

### 1.2 Applications et fenêtres

**Type d'events :** `app_activated`, `app_switch`, `window_title_poll`, titres embarqués dans les events app

**Producteur :** client Swift via AXObserver → POST `/event`

**Payload principal :** `app_name`, `window_title`, catégorie d'app

**Sensibilité :** moyenne à élevée. Un titre de fenêtre peut révéler un nom de client, un sujet de conversation, un fichier confidentiel ou un contenu sensible.

**Persisté :** oui. Le titre brut est stocké tel quel dans `payload_json` — il n'existe pas de normalisation dans `_payload_for_storage` pour cette famille d'events. Une minimisation en persistance long-terme est souhaitable mais pas encore implémentée. À traiter comme donnée potentiellement sensible dans tous les chemins de lecture.

**Ce que cette source peut faire :**
- enrichir le contexte courant
- servir de fallback pour `active_file` si aucun fichier actif n'est disponible (ex. titre VSCode contenant le nom du fichier)
- contribuer à la classification YouTube / navigation / lecture pour filtrage de sessions non-travail

**Ce que cette source ne peut pas faire seule :**
- ancrer un projet de façon fiable
- créer un épisode de travail
- prouver qu'un utilisateur travaille

**Notes :**
- un titre de fenêtre est un support, jamais une source forte.
- les titres peuvent être trompeurs : ancien onglet, fenêtre inactive, titre générique.
- "YouTube" dans un titre de fenêtre est un signal de non-travail explicite, même si l'app active est un navigateur.

---

### 1.3 Terminal

**Type d'events :** `terminal_command_started`, `terminal_command_finished`

**Producteur :** client Swift via observation shell → POST `/event`

**Payload principal :** commande normalisée, `cwd`, `exit_code`, `terminal_action_category`, `summary`

**Sensibilité :** élevée. La commande complète peut contenir des credentials, des tokens, des arguments privés.

**Persisté :** oui, redacté. La commande complète n'est jamais stockée en clair en persistance durable. Les champs utiles (`terminal_action_category`, `summary`, `exit_code`, `cwd`) sont conservés. Tout champ de commande persistant est redacté via `redact_sensitive_command()`.

**Ce que cette source peut faire :**
- ancrer le projet actif via `cwd`
- influencer `activity_level` (ex. `testing`, `building`, `executing`)
- influencer `probable_task`
- contribuer à un work block via sa catégorie

**Ce que cette source ne peut pas faire seule :**
- prouver que l'utilisateur est l'auteur de la commande (un outil peut exécuter des commandes)
- justifier à elle seule une nouvelle session de travail significative

**Notes :**
- les commandes read-only (`ls`, `cat`, `grep`, `git log`, `git diff`, etc.) sont des signaux faibles. Elles n'indiquent pas d'activité de production.
- les commandes à effet (`git commit`, `npm run build`, `pytest`, `xcodebuild`) sont des signaux forts.
- `terminal_action_category` est la granularité correcte pour le long-terme : `testing`, `building`, `vcs`, `execution`, `inspection`, `navigation`.

---

### 1.4 MCP / outils IA

**Type d'events :** `mcp_command_received`, `mcp_decision`

**Producteur :** routes `/mcp/intercept`, `/mcp/decision`

**Payload principal :** `command`, `tool_use_id`, catégorie, `read_only`, `decision`

**Sensibilité :** élevée. Les commandes MCP peuvent contenir des instructions complètes, des contenus de fichiers, des credentials.

**Persisté :** oui, redacté. Les champs `command` de `mcp_command_received` et `mcp_decision` sont redactés via `redact_sensitive_command()` avant toute persistance durable — jamais stockés en clair. Les champs structurés (`category`, `tool_use_id`, `read_only`, `decision`) sont les champs de référence pour l'interprétation long-terme. À terme, `command` ne devrait pas être conservé durablement si `category`, `summary`, `tool_use_id` et `decision` suffisent.

**Ce que cette source peut faire :**
- enrichir le contexte outil/assisté
- contribuer au marquage `tool_assisted` sur les events associés
- indiquer qu'une action a été proposée ou exécutée par un outil

**Ce que cette source ne peut pas faire seule :**
- représenter du travail utilisateur
- ancrer un projet sans corroboration d'un file event

**Notes :**
- les events MCP sont toujours marqués comme outil/assisté, jamais comme activité utilisateur directe.
- `mcp_decision` avec `decision=rejected` est un signal important : l'utilisateur a refusé une action proposée. Ce signal mérite d'être conservé.
- MCP bypass actuellement `EventMeaningPolicy` en passant directement sur le bus — point à surveiller.

---

### 1.5 Clipboard

**Type d'events :** `clipboard_updated`

**Producteur :** client Swift → POST `/event`

**Payload principal :** `content_kind`, `char_count`. Le contenu brut est explicitement supprimé avant publication sur le bus.

**Sensibilité :** très élevée. Le clipboard peut contenir des mots de passe, des tokens, des données personnelles, des contenus confidentiels.

**Persisté :** oui, sans contenu. Seuls `content_kind` et `char_count` sont persistés. Le contenu brut n'atteint jamais le bus.

**Ce que cette source peut faire :**
- enrichir le contexte de debug si `content_kind=stacktrace`
- indiquer un type d'activité (copie de code, de texte, de donnée structurée)

**Ce que cette source ne peut pas faire seule :**
- inférer le projet actif
- créer un work block
- indiquer que l'utilisateur travaille

**Règle absolue :** le contenu brut du clipboard n'est jamais persisté, jamais injecté dans un contexte LLM.

---

### 1.6 Écran — lock / unlock

**Type d'events :** `screen_locked`, `screen_unlocked`

**Producteur :** client Swift → POST `/event`

**Payload principal :** timestamp

**Sensibilité :** faible. Ces events sont des signaux de lifecycle purs.

**Persisté :** oui.

**Ce que cette source peut faire :**
- déclencher une frontière de session (`screen_locked` long → clôture de session)
- inhiber toute observation pendant le lock (règle de priorité absolue)
- déclencher la préparation de la ResumeCard au lock
- déclencher la consommation de la ResumeCard au unlock

**Ce que cette source ne peut pas faire seule :**
- prouver que l'utilisateur travaille au unlock
- ancrer un projet

**Notes :**
- pendant `screen_locked`, tous les events sauf `screen_locked`/`screen_unlocked` sont bloqués à l'ingress HTTP et ignorés à l'orchestrateur.
- un verrou court ne crée pas de nouvelle session (règle `SessionFSM`).

---

### 1.7 Présence utilisateur — IOKit

**Type d'events :** `user_presence` avec `source=iokit`, `user_idle`, `user_active`

**Producteur :** `IdlePresenceHeartbeat` via `macos_iokit_idle` → EventBus

**Payload principal :** `presence_state` (`active`/`idle`), `idle_seconds`, `source`

**Sensibilité :** faible à moyenne.

**Persisté :** oui, si le runtime n'est pas locked.

**Ce que cette source peut faire :**
- distinguer présence active et présence idle
- réduire les faux positifs d'attribution de travail (présence idle ≠ travail actif)
- contribuer à `activity_level` comme signal de support

**Ce que cette source ne peut pas faire seule :**
- ancrer un projet
- créer un work block
- prouver que l'utilisateur travaille (présence active ≠ travail)

**Notes :**
- IOKit est la source de présence la plus fiable disponible sur macOS.
- `is_locked` est vérifié avant toute publication : le heartbeat ne publie rien pendant un lock écran.
- fail-closed : si `is_locked` lève une exception, le heartbeat se traite comme si le Mac était locked.
- IOKit est macOS-only. Sur d'autres plateformes, la présence reste non détectée.

---

### 1.8 Commits git

**Type d'events :** dérivé de `COMMIT_EDITMSG`, `HEAD`, diff — via commit watcher

**Producteur :** file event sur chemins git + commit watcher

**Payload principal :** message de commit, fichiers du diff, projet

**Sensibilité :** moyenne à élevée. Les messages de commit peuvent être explicites sur le travail en cours. Les messages sont redactés avant écriture durable dans le journal, le hidden JSON et les prompts LLM.

**Persisté :** oui, en session et en journal. Les messages sont conservés sous forme redactée. Les diffs sont résumés, pas stockés bruts.

**Ce que cette source peut faire :**
- ancrer un project de façon forte
- marquer une frontière de work block
- enrichir le journal de session avec le travail livré
- confirmer une activité de développement

**Ce que cette source ne peut pas faire seule :**
- prouver que c'est l'utilisateur qui a commité (Codex/CI peuvent commiter en arrière-plan)
- justifier à elle seule une nouvelle session de travail significative

**Notes :**
- un commit pendant `activity_level=idle` est marqué `async_commit` (flag d'incertitude). C'est le cas typique des commits Codex nocturnes.
- `files_changed` est dérivé du diff du commit, pas du comptage général d'events file.

---

## 2. Niveaux d'influence

Chaque famille d'observation peut agir à différents niveaux. Ce tableau définit ce qu'une source est autorisée à influencer.

| Source | `can_persist` | `can_anchor_project` | `can_anchor_file` | `can_start_work_block` | `can_influence_activity` | `can_enter_journal` | `requires_redaction` |
|---|---|---|---|---|---|---|---|
| File meaningful (user/unknown) | oui | oui | oui | oui | oui | oui | non |
| File tool_assisted | oui | oui | oui | assisté seulement | oui | oui | non |
| File noise / system | non | non | non | non | non | non | — |
| App / fenêtre | oui (brut, à minimiser) | non | fallback | non | partiel | non | à faire |
| Terminal à effet | oui | via cwd | non | oui | oui | oui | oui |
| Terminal read-only | oui | via cwd | non | non | partiel | non | oui |
| MCP command | oui (redacté) | non | non | non | partiel | non | oui |
| MCP decision | oui (redacté) | non | non | non | non | partiel | oui |
| Clipboard | oui (kind/size) | non | non | non | non | non | contenu supprimé |
| Screen lock/unlock | oui | non | non | non | non | oui | non |
| Présence / IOKit | oui si non locked | non | non | non | support | non | non |
| Commit git | oui | oui | non | frontière | oui | oui | oui (message) |

---

## 3. Classification des observations

### Strong evidence

Ces observations disent quelque chose de fiable sur le travail réel. Elles peuvent influencer le présent, les work blocks et les sessions.

- **File events meaningful, actor=user ou unknown** — la source la plus directe d'activité utilisateur sur un projet.
- **Commandes terminal à effet** (`git commit`, `npm run`, `pytest`, `xcodebuild`) — signal d'exécution réelle.
- **Commit git confirmé** — preuve de livraison. Fort pour la mémoire, modéré pour le présent immédiat.
- **Screen locked / unlocked** — signal de lifecycle fiable et prioritaire.

### Contextual evidence

Ces observations enrichissent le contexte mais ne suffisent pas seules à établir une vérité de travail.

- **App active et catégorie** (dev, browser, writing, communication)
- **Window title** — fallback pour `active_file`, support pour classification non-travail
- **Clipboard kind** — indice d'activité (debug, copy/paste de code), jamais de contenu
- **User presence / idle** (IOKit) — support de présence, pas de travail
- **Terminal cwd** — ancrage projet secondaire si pas de file actif
- **Terminal commands read-only** — indice d'inspection, faible
- **MCP read_only** — contexte outil, pas activité utilisateur

### Sensitive evidence

Ces observations nécessitent une redaction avant persistance et ne doivent jamais être injectées en clair dans un contexte LLM.

- **Terminal command complète** — redactée avant persistance, disponible court-terme sur le bus
- **MCP command** (`mcp_command_received.command`, `mcp_decision.command`) — redactée avant persistance `SessionMemory`
- **Window title** — stockée brute actuellement ; minimisation en persistance long-terme à implémenter
- **Chemins de fichiers** — filtrés si sensibles (credentials, config privée, paths système)

### Noise / ignored

Ces observations sont filtrées avant d'atteindre le présent ou la mémoire.

- **Chemins système et techniques** : `.git`, `node_modules`, `.venv`, `DerivedData`, `__pycache__`, `.DS_Store`, caches, logs, `.wal`, `.db`, `tmp`, `/var`, `/private`, UUID, hash git
- **File events actor=system** sur chemins non-significatifs
- **Events pendant screen_locked** (sauf lock/unlock eux-mêmes)
- **Screenshots** (`observe_only`, pas d'influence sur le présent)
- **File events tool_assisted sur chemins techniques** — ignorés pour `edited_file_count`

---

## 4. Règles de priorité

Quand plusieurs sources sont actives simultanément, les règles suivantes s'appliquent.

**1. `screen_locked` domine tout.**
Pendant un lock, aucune source ne peut influencer le présent. L'ingress HTTP bloque tout sauf lock/unlock. L'orchestrateur ignore tout sauf lock/unlock.

**2. IOKit est la source de présence locale préférée quand disponible.**
Les events `user_presence` client sont acceptés comme compléments mais ne doivent pas contredire `screen_locked`. Il n'existe pas encore de résolution de priorité stricte entre les deux sources au niveau du bus.

**3. File meaningful > window title pour `active_file` et `active_project`.**
Le titre de fenêtre n'est utilisé que si aucun file event récent n'ancre un fichier actif.

**4. Terminal récent peut ancrer le projet via `cwd` si aucun fichier actif n'est disponible.**
C'est un fallback, pas une source primaire.

**5. Terminal et MCP influencent `activity_level` avant l'app seule.**
`inspection` (terminal read-only ou MCP read_only) précède `reading`.
`executing` ou `testing` (terminal à effet) précède toute inférence depuis l'app.

**6. `actor=tool_assisted` n'est jamais promu en activité utilisateur.**
Ces events contribuent au contexte et à l'actor attribution, mais ne gonflent pas les compteurs d'activité utilisateur.

**7. `user_presence=idle` rétrograde la confiance des signaux de travail.**
Un file event pendant une longue période d'idle IOKit est suspect. Il peut indiquer une activité outil plutôt qu'utilisateur.

---

## 5. Ce qu'une source seule ne peut jamais déclencher

Ces règles sont absolues. Elles ne peuvent pas être contournées par un cas particulier.

- **Présence utilisateur seule** (IOKit ou `user_active`) → ne peut pas créer un work block ni justifier à elle seule une nouvelle session de travail significative.
- **App active seule** → ne peut pas ancrer un projet, créer un épisode ou une session.
- **Window title seule** → ne peut pas ancrer un projet ni créer de vérité de travail.
- **File event `tool_assisted` seul** → peut contribuer à un épisode assisté, mais jamais à un épisode attribué comme travail utilisateur direct.
- **File event `actor=system` seul** → ne peut rien déclencher.
- **Clipboard seul** → ne peut pas inférer le projet ni créer un work block.
- **MCP read_only seul** → ne peut pas représenter du travail utilisateur.
- **`screen_unlocked` seul** → ne rouvre pas automatiquement un work block.

---

## 6. Règles de persistance

| Famille | Durée de vie runtime | Persisté en SessionMemory | Persisté en journal |
|---|---|---|---|
| File events meaningful | bus circulaire (500 events) | oui, filtré | oui, agrégé |
| File events noise | filtrés avant bus | non | non |
| App / window title | bus circulaire | oui, brut (à minimiser) | non |
| Terminal command brute | bus circulaire | redactée | non |
| Terminal category / summary | bus circulaire | oui | oui |
| MCP command brute | bus circulaire | redactée | non |
| MCP category / decision | bus circulaire | oui | oui |
| Clipboard content | supprimé avant bus | non | non |
| Clipboard kind / size | bus circulaire | oui | non |
| Screen lock events | bus circulaire | oui | oui |
| User presence / IOKit | bus circulaire | oui si non locked | non |
| Commit message | persistant | oui | oui |
| Commit diff files | persistant | oui (résumé) | oui |

**Règle générale :** plus une donnée est sensible, plus sa durée de vie est courte et sa forme persistée est réduite.

---

## 7. Angles morts

### Utiles maintenant

**Résultats de tests structurés.**
Pulse voit `terminal_action_category=testing` et `exit_code`, mais pas le détail stable : combien de tests ont passé, combien ont échoué, quel fichier a planté. Un résumé minimal (`tests_passed`, `tests_failed`, `test_file`, `failure_summary`) sans stdout brut rendrait le niveau 1 significativement plus fiable pour les sessions de développement intensif.

**Branche git courante.**
Pulse connaît le projet depuis les chemins de fichiers et le `cwd` terminal, mais pas la branche active. Une branche peut indiquer le contexte de travail (feature, fix, expérimentation) de façon plus fiable que le titre de fenêtre ou la sémantique déduite du fichier actif.

**Fichier / document actif dans l'éditeur (fiable).**
Le parsing du titre de fenêtre VSCode ou Xcode est fragile. L'API Accessibility (AX) peut lire directement le document actif dans ces éditeurs sans FSEvents. C'est plus précis et ne dépend pas du format du titre.

### Plus tard

**Contexte process/task.**
Savoir quel outil écrit vraiment les fichiers (Codex, un script, l'utilisateur) nécessiterait d'inspecter les process actifs. Utile pour l'actor attribution, mais complexe et potentiellement intrusif.

**Idle multi-plateforme.**
IOKit résout le problème sur macOS. Une solution portable n'est pas prioritaire tant que Pulse est un outil macOS.

**Résultats de build détaillés.**
Similaire aux test results, mais le format varie encore plus selon l'environnement (Xcode, npm, cargo, make). À envisager après les test results.

**Intention confirmée par l'utilisateur.**
Ce n'est plus du niveau observation pur — cela touche au niveau 2 (qualification) et à l'agentique future.

---

## 8. Ce qui n'est pas dans ce document

Ce document ne couvre pas :

- le pipeline runtime et ses couches (`architecture.md`)
- le contrat de la mémoire et des faits (`semantic_contract.md`)
- la qualification des observations en vérité de travail (niveau 2)
- la construction du présent canonique (`PresentState`, `SignalScorer`)
- les sessions, work blocks et continuité temporelle (niveau 4)
- les proposals, actions ou DayDream

---

## 9. Contrats à tester

Ces assertions doivent rester vraies. Elles servent de base pour des tests de non-régression sur le comportement d'observation.

- Un event `user_presence` seul ne crée jamais de work block.
- Un event `mcp_command_received.command` est redacté avant persistance `SessionMemory`.
- Un event `mcp_decision.command` est redacté de la même façon que `mcp_command_received.command`.
- Un event `file_modified` avec `_actor=system` ne crée pas d'épisode et n'influence pas `active_project`.
- Un event `file_modified` avec `_actor=tool_assisted` peut créer un épisode assisté mais ne monte pas `edited_file_count_10m`.
- Un titre de fenêtre seul ne peut pas ancrer `active_project`.
- Pendant `screen_locked`, aucun event IOKit n'est publié sur le bus.
- Pendant `screen_locked`, les events entrants (hors lock/unlock) sont bloqués à l'ingress HTTP.
- Le contenu brut du clipboard n'atteint jamais le bus ni la persistance.
- Un commit avec `activity_level=idle` est marqué `async_commit` dans le payload persisté.

---

## Résumé opérationnel

Pulse observe des fichiers, des apps, du terminal, du MCP, du clipboard, des événements écran, la présence IOKit et des commits.

Les fichiers meaningful (user/unknown) et les commandes terminal à effet sont les sources les plus fiables du travail réel.

Les apps, fenêtres, terminal read-only et présence IOKit enrichissent le contexte mais ne créent jamais de vérité de travail seuls.

Le clipboard, les commandes MCP et les commandes terminal brutes sont sensibles — redactés avant persistance, jamais injectés en clair.

Toute observation, même forte, reste une preuve partielle. Plusieurs observations convergentes construisent la confiance. Une seule ne suffit jamais à établir une certitude de travail.