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

### Suite

Jour 2 : lecture des 6 autres reprises, `run --once` sur les sessions du jour.
