# Pulse

> Couche locale d’observation, de contexte, de mémoire et de contrôle autour des IA sur macOS

---

## Pourquoi Pulse existe

Les outils IA deviennent capables de lire, modifier, exécuter et proposer de plus en plus de choses dans un environnement de travail réel.

Le problème n’est pas seulement la qualité de leurs réponses.  
Le problème est aussi la perte de lisibilité :

- que voit réellement l’IA ?
- sur quoi se base-t-elle ?
- que comprend-elle du contexte ?
- pourquoi propose-t-elle ceci maintenant ?
- à quel moment agit-elle trop tôt ?

Pulse existe pour éviter que cette couche de décision devienne opaque.

L’idée centrale est simple :

> ne pas subir l’IA comme une boîte noire, mais reconstruire une couche locale de contexte, de mémoire et de contrôle autour d’elle.

---

## Ce qu’est Pulse aujourd’hui

Pulse est un système local qui :
- observe l’activité utile sur le poste
- maintient un présent runtime canonique exploitable
- consolide une mémoire locale simple
- intercepte certaines actions d’agents
- produit des propositions explicables
- expose une fenêtre dashboard technique indépendante pour rendre l’état interne visible en temps réel

Concrètement, Pulse repose sur :
- une app macOS Swift autour de l’encoche
- une fenêtre dashboard indépendante côté app pour visualiser session, mémoire, événements, MCP et état système
- un daemon Python local
- une couche LLM optionnelle, utilisée seulement quand le déterministe ne suffit plus

Aujourd’hui, Pulse sait surtout :
- observer
- structurer
- mémoriser
- contrôler
- aider à reprendre le contexte après une pause via des Resume Cards

Il ne sait pas encore :
- modéliser parfaitement la continuité du travail sur plusieurs blocs
- relier systématiquement sessions, commits, journal et reprises de contexte
- proposer de manière vraiment intelligente selon le moment du travail
- agir de manière autonome

---

## Ce que Pulse n’est pas

Pulse n’est pas :
- un agent autonome
- un assistant qui “comprend tout”
- un chatbot généraliste
- un simple wrapper LLM
- une couche magique de productivité

Pulse est une base locale sérieuse pour construire :
- plus de lisibilité
- plus de contexte utile
- plus de contrôle utilisateur

Mais cette base n’est pas encore le système final.

---

## Le problème que Pulse résout

Aujourd’hui, l’usage des IA dans un environnement de travail réel crée plusieurs tensions :

- le contexte est fragile et doit être répété
- les outils IA n’ont qu’une vue partielle du travail en cours
- les propositions arrivent souvent au mauvais moment
- les commandes et actions agents peuvent devenir difficiles à relire
- la mémoire des interactions est pauvre ou inexistante

Pulse tente de résoudre cela localement, en reconstruisant un fil cohérent :

Observation -> structuration -> mémoire -> proposition

Pas pour “remplacer” l’IA, mais pour lui donner un cadre plus lisible et plus contrôlable.

---

## Comment Pulse fonctionne

Pulse fonctionne en trois couches.

### 1. Observation locale

L’app Swift observe le système :
- application active
- fichiers touchés
- clipboard
- lock / unlock écran
- interactions utiles au runtime

Elle n’interprète pas.
Elle remonte des événements.

### 2. Runtime local

Le daemon Python suit aujourd’hui ce pipeline réel :

```text
event
→ SessionFSM
→ SignalScorer
→ RuntimeState.update_present()
→ DecisionEngine
→ SessionMemory
→ projections de travail / journal / Resume Card
```

Les responsabilités nettes sont :
- `PresentState` = vérité canonique du présent
- `SessionFSM` = état de session
- `SignalScorer` = contexte de travail courant
- `RuntimeOrchestrator` = orchestration, déclencheurs proactifs et effets de bord contrôlés
- `CurrentContextBuilder` = rendu pour lecture assistant/UI
- `SessionMemory` = persistance historique

Cette partie est aujourd’hui la fondation la plus solide du projet.

### 3. Mémoire et enrichissement

Pulse produit ensuite une mémoire locale rétrospective :
- résumés de session
- blocs de travail dérivés
- faits utilisateur
- contexte réutilisable dans les échanges assistant
- cartes de reprise courtes pour aider l’utilisateur à revenir dans le fil

Cette mémoire existe déjà, mais elle reste encore :
- principalement session-centrique
- heuristique
- imparfaite

Le LLM intervient seulement quand nécessaire :
- résumé de commit
- enrichissement limité
- Resume Card LLM avec fallback déterministe
- questions explicites

### Surfaces locales exposées

Pulse expose des routes locales pour :
- l’état runtime et le contexte courant
- les insights, faits et profils locaux
- la mémoire et les sessions récentes
- les propositions MCP et décisions associées
- les context probes soumises à validation
- certains chemins debug, notamment les Resume Cards déterministes et LLM

Ces routes sont des surfaces de lecture, de contrôle ou de debug local. Elles ne doivent pas devenir une nouvelle source de vérité parallèle.

---

## Ce qui est solide aujourd’hui

La fondation du système est maintenant en place.

Cela veut dire que Pulse possède déjà :
- un runtime structuré
- un présent canonique unique via `PresentState`
- un cycle de session unifié via `SessionFSM`
- un contexte de travail cohérent via `SignalScorer`
- un snapshot runtime atomique pour les lectures
- une compat legacy verrouillée sur les sorties critiques

Ce n’est pas encore une intelligence aboutie.

Mais c’est une base crédible pour observer le système réel avant d’aller plus loin.

---

## Ce qui reste à construire

La partie la plus difficile n’est pas l’observation brute.

La partie la plus difficile est encore devant :
- distinguer correctement les phases de travail
- éviter les mauvaises inférences
- produire de meilleures propositions
- enrichir la mémoire sans raconter des histoires

En particulier, Pulse n’a pas encore :
- une modélisation parfaite des blocs de travail sur la durée
- une corrélation totalement fiable entre sessions, commits, journal et reprises de contexte
- un moteur de proposition vraiment contextuel
- une agentique contrôlée

Autrement dit :
- la fondation est faite
- l’intelligence reste à construire

---

## Différence avec une approche purement agentique

Beaucoup de systèmes partent directement de l’action :
- l’agent voit quelque chose
- l’agent décide
- l’agent agit

Pulse part d’un ordre différent :
- observer d’abord
- structurer ensuite
- mémoriser ce qui mérite de durer
- proposer avant d’agir

Cette différence est importante.

Pulse cherche à construire une IA que l’on peut relire, comprendre et corriger.
Pas une IA qui agit plus vite que la capacité de l’utilisateur à suivre.

---

## Où en est le projet

Pulse n’est plus seulement une idée ou un prototype flou.

Le projet a franchi une première étape importante :
- la fondation runtime est terminée
- les contrats centraux existent
- le lifecycle sessionnel est unifié via `SessionFSM`
- `PresentState` porte la vérité canonique du présent
- `current_context`, `recent_sessions` et `work_blocks` remplacent l’ancienne piste `EpisodeFSM`
- le système est assez stable pour être observé sérieusement

La prochaine étape logique n’est pas de réintroduire les épisodes.

Le système possède déjà :
- un présent runtime canonique
- des sessions récentes exploitables
- des projections de travail via `work_blocks` / `work_block_*`
- un journal local consolidé
- des Resume Cards, dont une version LLM avec fallback déterministe

Mais ces éléments restent encore perfectibles :
- les blocs de travail sont encore des projections dérivées
- la continuité entre longue session, commit final, journal et reprise de contexte doit encore être validée terrain
- les propositions ne sont pas encore réellement pilotées par une compréhension stable du moment de travail

Ce qui reste à rendre plus fort :
- la corrélation des blocs de travail dans le temps
- la mémoire structurée autour des sessions, work blocks et commits
- les propositions réellement contextualisées par continuité de travail

---

## Ce que Pulse cherche à devenir

À terme, Pulse vise un système local capable de :
- mieux reconnaître le travail réel en cours
- mieux relier le présent, l’historique récent et la mémoire
- mieux proposer au bon moment
- ouvrir éventuellement des formes d’action contrôlée

Mais cette cible n’est pas le présent.

Aujourd’hui, Pulse est surtout :
- une couche locale d’observation
- une structure de contexte
- une mémoire simple mais utile
- un système de reprise de contexte encore jeune
- un cadre de contrôle utilisateur autour des IA

Et c’est précisément ce qui le rend crédible à ce stade.
