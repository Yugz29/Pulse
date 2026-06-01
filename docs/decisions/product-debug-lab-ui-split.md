# Product, Debug, and Lab UI Split

Internal context: UI/Product split

## Statut

- décision documentaire ;
- aucun code dans ce patch ;
- aucun changement daemon ;
- aucun changement route ;
- aucun changement API ;
- aucun changement Swift dans ce patch ;
- prépare un futur patch UI-only.

## Pourquoi

Le dashboard actuel mélange expérience produit, diagnostic debug et surfaces Lab. Cette organisation a été utile pendant la construction de Pulse : elle donne au développeur un cockpit complet pour observer le daemon, les événements, les reconstructions, les probes, la mémoire et les expérimentations.

Comme produit, ce mélange devient confus. Une surface quotidienne ne doit pas exposer au même niveau les diagnostics runtime, les expériences Lab et les informations qui aident réellement à reprendre le fil.

La boucle "Aujourd'hui" donne maintenant une première valeur utilisateur :

- `/today_summary.work_blocks[].top_files` existe ;
- la carte "Aujourd'hui" affiche les derniers blocs ;
- la carte a été compactée et validée visuellement ;
- les sessions terrain montrent que `/today_summary` + `/feed` aident à reprendre le fil.

Il faut donc distinguer ce que l'utilisateur voit au quotidien de ce qui sert au dogfooding, au debug et aux expérimentations internes.

## Décision

Pulse acte trois surfaces UI.

### 1. Encoche

- résumé vivant / glance ;
- ne doit pas devenir un cockpit ;
- affichera à terme le projet, la tâche, le bloc courant, l'état Core.

### 2. Produit

- entrée principale du dashboard ;
- orientée reprise du fil ;
- doit répondre à "Qu'est-ce que j'ai fait aujourd'hui ?" ;
- surfaces initiales :
  - `Aujourd'hui`
  - `Notifications`

### 3. Debug / Lab

- cockpit interne ;
- diagnostic runtime ;
- surfaces expérimentales ;
- surfaces initiales :
  - `Séquences debug`
  - `Observation`
  - `Événements`
  - `MCP`
  - `Système`
  - `Mémoire (Lab)`
  - `DayDream (Lab)`
  - `Contexte (Lab)`

## Règles

- Produit ne doit pas exposer DayDream, facts/profile, VectorStore, LLM summaries, memory candidates ou context probes comme surfaces principales.
- Debug / Lab reste accessible.
- Rien n'est supprimé dans cette phase.
- Aucun backend nouveau n'est requis.
- Aucune route `/today` ne doit être créée pour ce split.
- `/today_summary`, `/feed` et `/state` restent les sources existantes.
- `DashboardViewModel.refresh()` peut continuer à charger les données existantes dans le premier patch.
- L'optimisation réseau est hors scope.

## Premier patch autorisé

Un patch UI-only est autorisé dans `DashboardRootView.swift` :

- ajouter une notion locale de surface :
  - Produit
  - Debug / Lab
- afficher un sélecteur en haut de sidebar ;
- filtrer les sections selon la surface choisie ;
- Produit démarre sur `Aujourd'hui` ;
- Debug / Lab démarre sur `Séquences debug` ;
- garder les vues existantes ;
- ne pas extraire massivement `DashboardRootView.swift`.

## Ce que cette décision interdit

- refonte visuelle complète ;
- redesign de l'encoche dans ce patch ;
- suppression des vues Debug/Lab ;
- changement daemon ;
- changement route/API ;
- changement `/today_summary` ou `/feed` ;
- ajout IA / LLM ;
- ajout ou activation Lab ;
- refactor massif Swift ;
- nouvelle route `/today`.

## Tests attendus dans le futur patch

- Surface Produit démarre sur `Aujourd'hui`.
- Surface Produit contient `Aujourd'hui` et `Notifications`.
- Surface Debug / Lab contient les anciennes sections non produit.
- Changer de surface sélectionne une section valide.
- Les anciennes sections restent accessibles en Debug / Lab.
- Les labels Lab restent explicites.

## Décision finale

La séparation Produit / Debug-Lab devient la prochaine étape UI.

Le premier patch doit être UI-only, minimal et réversible.
