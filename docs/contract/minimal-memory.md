# Minimal Memory Contract

Etat courant au moment de R5a Core Reset. Ce document decrit le comportement existant. Ce n'est pas une architecture cible et il n'introduit aucun nouveau comportement.

## Perimetre

R5 commence apres les baselines runtime, observation, interpretation et sessions :

```text
EventBus -> SessionMemory SQLite -> SessionSnapshot -> export historique -> journal minimal
```

R5 doit prouver que Pulse peut produire un historique minimal utile, tracable et verifiable. R5 ne couvre pas l'apprentissage, les facts / profils, DayDream, le vector store, les resumes LLM, les propositions, les resume cards LLM/intelligentes, le commit episode linking ou l'adaptation.

## Surfaces principales

| Surface | Role actuel | Core R5 strict |
|---|---|---|
| `SessionMemory` | Persiste sessions et events dans SQLite | oui |
| `SessionSnapshotBuilder` | Construit un snapshot structure depuis session SQLite + events recents | oui |
| `export_session_data()` | Adaptateur legacy depuis `SessionSnapshot` | oui, comme contrat historique minimal actuel |
| `export_memory_payload()` | Payload plus large utilise par le runtime / sync memoire | oui, seulement comme export de session, pas comme memoire intelligente |
| `update_memories_from_session()` | Ecrit projets, journal, facts, LLM repair, embeddings selon conditions | mixte / dangereux |
| Journal Markdown visible | Lecture humaine de sessions | oui seulement comme historique minimal, pas source canonique complete |
| Hidden payload journal | Payload JSON structure dans le Markdown | oui si present, avec prudence |
| `truth_layers` | Classification observed / derived / inferred / narrative | oui comme provenance actuelle |
| `/memory/sessions` | Lecture des journaux Markdown | oui en lecture historique, pas preuve principale |
| `/search` | Recherche dans les events SQLite de `SessionMemory` | oui |
| `MemoryStore` | Memoire structuree a tiers | non pour R5 strict |
| `FactEngine` | Facts / profil / promotion d'observations | non |
| `VectorStore` | Index semantique | non |
| `DayDream` | Synthese narrative nocturne | non |

## Socle Core R5

### `SessionMemory` SQLite

`daemon/memory/session.py` est le socle le plus proche du Core R5.

Il persiste :

- une ligne `sessions` pour la session courante ;
- des lignes `events` rattachees a la session ;
- des timestamps observes ;
- des champs de projection session comme `active_project`, `active_file`, `probable_task`, `activity_level`, `focus_level`, `friction_score` et `session_duration_min`.

Il redige aussi certains payloads avant stockage :

- commandes terminal sensibles ;
- sorties terminal brutes ;
- contexte git contenant `repo_root` ;
- titres de fenetre / contexte libre.

Cette persistance SQLite est plus proche de la source Core que les journaux Markdown.

### `SessionSnapshotBuilder`

`daemon/memory/session_snapshot_builder.py` construit un `SessionSnapshot` depuis :

- la ligne SQLite de session ;
- les events recents ;
- une duree fallback.

Le snapshot extrait aujourd'hui :

- apps recentes ;
- fichiers significatifs non `technical_noise` ;
- nombre de fichiers ;
- top files ;
- friction max ;
- dates et champs session.

Le builder reste volontairement aligne avec `export_session_data()` et ne doit pas devenir un moteur d'apprentissage.

### `export_session_data()`

`SessionMemory.export_session_data()` convertit le snapshot structure en dictionnaire legacy.

Champs actuels importants :

- `session_id`
- `started_at`, `updated_at`, `ended_at`
- `active_project`, `active_file`
- `probable_task`
- `focus_level`
- `duration_min`
- `recent_apps`
- `files_changed`
- `top_files`
- `event_count`
- `max_friction`

Ce payload est un resume derive de la session et de ses events. Il ne doit pas etre lu comme profil utilisateur.

### `export_memory_payload()`

`SessionMemory.export_memory_payload()` produit un payload plus large consomme par le runtime et par les chemins de sync memoire.

Il ajoute notamment :

- `top_file_paths`
- `project_root` derive des events fichiers / racines git locales ;
- `commit_count` depuis les events `COMMIT_EDITMSG` ;
- `work_block_started_at`
- `work_block_commit_count`
- `recent_sessions`
- alias legacy `work_window_*` et `closed_episodes`.

En R5 strict, ce payload reste un export de session. Les alias legacy ne doivent pas etre promus en nouveau modele Core.

## Journal historique minimal

Le journal Markdown est aujourd'hui ecrit par `daemon/memory/extractor.py`, principalement via `update_memories_from_session()` et `_write_journal_document()`.

Il contient deux couches :

- une partie visible Markdown pour lecture humaine ;
- un hidden payload JSON entre `<!-- pulse-journal-data:start` et `pulse-journal-data:end -->`.

La partie visible est utile mais incomplete. Elle peut fusionner, masquer ou reformuler des entrees. Elle ne doit pas etre presentee comme la verite canonique complete.

Le hidden payload est plus structure, mais il reste une representation interne. Il ne doit pas etre expose tel quel comme verite produit brute.

## `truth_layers`

Les entrees de journal peuvent contenir `truth_layers`.

Couches actuelles :

- `observed` : timestamps, commit message, apps recentes, chemins de fichiers quand disponibles ;
- `derived` : duree, nombre de fichiers, top files, scope derive ;
- `inferred` : `probable_task`, `active_project`, `activity_level`, `boundary_reason`, scope et flags d'incertitude ;
- `narrative` : corps du journal ou resume de commit, avec source / statut de resume quand disponibles.

R5 doit preserver cette distinction. Un champ `probable_task` dans un journal est une inference, pas un fait observe. Un corps de journal est une narration, meme quand il est deterministe.

## Routes memoire

### `/memory/sessions`

`/memory/sessions` lit les fichiers Markdown sous `~/.pulse/memory/sessions`.

Comportement actuel :

- retourne `{"sessions": []}` si le dossier n'existe pas ;
- masque le hidden payload par defaut ;
- expose `has_hidden_payload` ;
- peut inclure le payload brut avec `include_hidden=true` ;
- marque la surface comme `product_memory_sessions` ou `product_memory_sessions_raw`.

Cette route est une lecture historique. Elle n'est pas la preuve principale Core R5.

### `/search`

`/search` delegue a `SessionMemory.search_events()`.

Cette route est Core-compatible si elle reste une recherche dans les events SQLite observes / stockes. Elle ne doit pas devenir une recherche vectorielle ou semantique pendant R5.

### `/memory/write` et `/memory/remove`

Ces routes utilisent `MemoryStore.write()` et `MemoryStore.remove()`.

Elles restent Lab en Core :

- en mode Core, elles repondent via `lab_surface_disabled_response()`;
- elles ne doivent pas devenir une surface Core R5 ;
- les tiers `habit`, `preference`, `persistent` ne doivent pas etre traites comme une memoire fiable pendant R5.

## Surfaces mixtes / dangereuses

### `extractor.py`

`daemon/memory/extractor.py` est mixte.

Il contient des parties utiles a R5 :

- rendu du journal ;
- hidden payload ;
- `truth_layers` ;
- fallback deterministe ;
- redaction de texte libre ;
- chargement des anciennes entrees de journal.

Il contient aussi des chemins hors Core R5 :

- `get_fact_engine().observe_session()` ;
- `projects.md` ;
- correction de tache depuis commit ;
- commit recovery / commit summaries ;
- enrichissement LLM ;
- repair de resumes en arriere-plan ;
- embeddings et vectorisation ;
- logique de consolidation riche.

Conclusion : `update_memories_from_session()` n'est pas Core-safe comme fonction isolee. Elle peut ecrire un journal minimal, mais elle peut aussi toucher facts, projects, LLM repair et embeddings selon le contexte et la configuration.

### Facts / profile legacy

Les anciens semantic contracts decrivaient le moteur de facts comme un pipeline heuristique : observations extraites des sessions, repetition, promotion mecanique en facts, decay, archivage et rendu contextuel pour certains chemins Lab.

Ce comportement reste hors Core R5. Il ne doit pas etre lu comme memoire minimale, profil utilisateur fiable ou apprentissage.

Limites conservees :

- la promotion par seuil compte la repetition d'une observation, pas sa verite ;
- `_promote_pending()` ne revalide pas la qualite semantique de la cle au moment de promouvoir ;
- `render_for_context()` filtre des facts par confiance, mais ne prouve ni validation utilisateur ni pertinence pour la tache courante ;
- `autonomy_level` peut exister comme donnee persistante Lab, mais ne gouverne pas le comportement Core ;
- absence de contradiction ne vaut pas confirmation.

### Runtime Core

Le runtime Core ne doit pas appeler automatiquement `update_memories_from_session()`.

Etat actuel important :

- `_sync_memory_background()` retourne immediatement en mode Core ;
- en mode Lab, il peut appeler `update_memories_from_session()` ;
- `freeze_memory()` produit une snapshot Core minimale quand Lab est desactive ;
- les objets avancés peuvent exister, mais ne doivent pas etre requis par `/ping`, `/state`, `/feed`, sessions ou le journal minimal Core.

## Hors R5 strict

Ces surfaces appartiennent a Lab ou a une phase ulterieure :

- facts / profile ;
- `MemoryStore` comme memoire durable produit ;
- vector store ;
- embeddings ;
- DayDream ;
- summaries LLM ;
- `work_episode_builder`;
- `journal_candidate_builder`;
- `commit_episode_linker`;
- debug memory views ;
- resume cards LLM/intelligentes ;
- apprentissage utilisateur / projet ;
- adaptation.

## Limites explicites R5a

- `extractor.py` est actuellement trop large pour etre considere comme fondation Core propre.
- `update_memories_from_session()` n'est pas Core-safe comme fonction isolee.
- `projects.md` est un artefact de synthese projet, pas un profil projet fiable pendant R5.
- Le Markdown visible n'est pas la verite canonique complete.
- Le hidden payload est structure mais ne doit pas etre expose brut comme verite produit.
- `truth_layers` ameliore la provenance, mais ne remplace pas une preuve canonique reliee directement a chaque event.
- `MemoryStore` et ses tiers `habit`, `preference`, `persistent` restent Lab.
- `/memory/write` et `/memory/remove` restent Lab en Core.
- `/memory/sessions` est une lecture historique, pas la source principale de session Core.
- La recherche `/search` est acceptable seulement tant qu'elle reste basee sur les events SQLite.

## Garde-fous R5

Ne pas utiliser R5 pour ajouter facts, profils, vector search, DayDream, resumes LLM, resume cards LLM/intelligentes, commit episode linking, apprentissage ou adaptation. R5 doit seulement prouver un historique minimal, qualifie et verifiable depuis les sessions et events deja observes.
