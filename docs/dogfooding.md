# Dogfooding — résumé de session (pas 3)

Journal du dogfooding du modèle local (`Qwen3.8-27B-4bit`, décision
[2026-09-06](decisions/2026-09-06-modele-local-qwen.md)). Un jour par entrée :
les reprises lues et jugées, les défauts trouvés. Critère de sortie (spec du
2026-09-03, §12) : au terme de cinq jours, **quatre reprises sur cinq jugées
justes et utiles** → service résident (étape 5) ; sinon on itère le prompt ou le
modèle sur le corpus `eval/`, et le service attend.

## Jour 1 — 2026-09-06

**`pulse-intel run --once` sur la trace réelle : 7 candidates, 7/7 créées.**
Sessions du 2026-09-05 20:09 au 2026-09-06 00:39.

### Reprises jugées

| session | durée | jugement |
| --- | --- | --- |
| `1e420dda8b6eee77` (work-26) | 88 min | **juste** — `doing`, `stopped_at` et `intents` collent à la session |
| les 6 autres | — | à lire jour 2 |

### Défauts trouvés

**D1 — `open` recopié du résumé précédent, périmé.** Sur `1e420dda`, le `open`
de Qwen reprend celui du `previous_summary` (« PR #28 et migration restent à
vérifier ») au lieu de le réévaluer à la fin de *cette* session — un point clos
depuis des heures. **Cause : le prompt v1.** L'entrée annexe `previous_summary`
(sa `reprise`), mais le prompt v1 ne dit nulle part comment s'en servir ; le
modèle recopie son `open` faute de consigne. → candidat pour la **v2 du prompt**
(voir plus bas), à mesurer sur le corpus avec la consigne sur les sessions sans
fichier, avant activation.

**D2 — `central_files` vide alors que la session a écrit du code.** `1e420dda`
a modifié `provider.py`, `fake.py`, `provider_summarizer.py`… mais la vue de
session ne les portait pas, donc le modèle a rendu `central_files: []` — correct
au vu de son entrée. **Cause en amont : le watcher.** `watched_workspaces` ne
couvrait que `Pulse/core`, pas la racine du repo unique ; les écritures sous
`intelligence/` étaient invisibles. Corrigé à la main (racine ajoutée +
`launchctl kickstart -k`, journal OK, pas de bruit constaté). Ce n'est pas un
défaut du modèle : entrée incomplète, sortie honnête.

### Angle mort du filtre d'ignore (suite de D2)

La racine du repo étant désormais observée, le filtre d'ignore du watcher
(`IGNORED_DIRECTORY_NAMES`) doit couvrir les dossiers d'outillage sous la racine.
Vérifié :

| dossier | couvert ? | par |
| --- | --- | --- |
| `intelligence/.venv` | oui | `.venv` |
| `core/macos_observer/.build` | oui | `.build` |
| `intelligence/eval/out` | **non** | `out` absent du filtre |

`eval/out/` est ignoré par git mais **pas** par le watcher : un futur
`pulse-intel eval` (qui écrit sous `intelligence/eval/out/`, dans l'arbre
observé) générerait du `file_changed` parasite dans la trace — le même symptôme
que `.gitnexus` avant qu'il ne soit ignoré. Sans impact sur le dogfooding, qui
n'utilise que `run`. À traiter : soit ajouter `out` au filtre (changement de
Core, gelé — justification à peser, `out` est un nom générique), soit faire
écrire `eval` hors de l'arbre observé par défaut. Décision reportée, hors lot.

### Mesure du jour 1 — prompt v2 sur le corpus

La v2 ajoute deux consignes à la v1 : `open` réévalué sur la session courante,
jamais recopié de `previous_summary` (D1) ; session sans fichier →
`central_files: []`, avec un exemple à zéro fichier (réserve n°1 de la décision
Qwen). Passage `eval` sur les dix sessions gelées, les deux providers, avant
activation. `fich.` = fichiers modifiés dans la vue ; `cf` = taille de
`central_files` ; `—` = rejeté par le garde-fou.

**Qwen local `Qwen3.8-27B-4bit` — v1 → v2**

| session | fich. | v1 | v2 | cf v1 | cf v2 | note |
| --- | --- | --- | --- | --- | --- | --- |
| `071bbd62` | 2 | ok | ok | 2 | 2 | |
| `247f2062` | 60 | ok | ok | 5 | 5 | confidence medium → high |
| `2ce34456` | 0 | **rejeté** | **ok** | — | 0 | #8 ambiguë → `[]` |
| `3cabaefb` | 60 | ok | ok | 5 | 5 | |
| `6a416635` | 0 | **rejeté** | **ok** | — | 0 | #6 → `[]`, plus de `vite.config.js` inventé |
| `7bbaca78` | 1 | ok | ok | 1 | 1 | |
| `8faf4569` | 25 | ok | ok | 5 | 5 | |
| `cda6ccce` | 29 | ok | ok | 5 | 5 | |
| `d047b37b` | 33 | ok | ok | 5 | 5 | |
| `eb652ce9` | 38 | ok | ok | 5 | 5 | |

Valides **8/10 → 10/10**, aucune perte ; les huit sessions à fichiers gardent
le même compte (moyenne 4,1 → 4,1), 3 à 5 chemins sur 5 identiques entre v1 et
v2, les substitutions restant des fichiers présents dans l'entrée.

**Référence `claude-sonnet-5` — v1 → v2**

| session | fich. | v1 | v2 | cf v1 | cf v2 | note |
| --- | --- | --- | --- | --- | --- | --- |
| `071bbd62` | 2 | ok | ok | 2 | 2 | |
| `247f2062` | 60 | ok | ok | 5 | 5 | confidence medium → high |
| `2ce34456` | 0 | **rejeté** | **ok** | — | 0 | #8 → `[]` |
| `3cabaefb` | 60 | ok | ok | 5 | 5 | |
| `6a416635` | 0 | ok | ok | 0 | 0 | #6 → `[]`, confidence medium → low |
| `7bbaca78` | 1 | ok | ok | 1 | 1 | |
| `8faf4569` | 25 | ok | ok | 5 | 5 | |
| `cda6ccce` | 29 | ok | ok | 5 | 4 | seul cran perdu |
| `d047b37b` | 33 | ok | ok | 5 | 5 | |
| `eb652ce9` | 38 | ok | ok | 5 | 5 | |

Valides **9/10 → 10/10**, aucune perte, moyenne 4,1 → 4,0 — pas de frilosité.

**D1 non mesurable sur le corpus** : aucune des dix sessions gelées ne porte
d'annexe `previous_summary`. Le corpus prouve que la consigne ne dégrade rien ;
elle se juge au jour 2 sur les sessions enchaînées de la journée. Une session
réelle à `previous_summary` est à ajouter au corpus, hors gel
(`intelligence/TODOS.md`).

**Décision : v2 adoptée**, `prompt_version = "v2"` dans la config de dogfooding
à partir du jour 2. Les résumés du jour 1 restent des résumés v1.

### Suite

Jour 2 : lecture des 6 autres reprises, `run --once` sur les sessions du jour
avec la v2 — premier jugement de D1 sur des sessions enchaînées.
