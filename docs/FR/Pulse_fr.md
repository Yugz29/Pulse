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
- structure un contexte courant exploitable
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

Il ne sait pas encore :
- comprendre finement la continuité du travail
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

### 2. Structuration locale

Le daemon Python transforme ces événements en couches plus utiles :
- signaux de travail
- contexte courant
- cycle de session
- projection de session
- propositions locales

Cette partie est aujourd’hui la fondation la plus solide du projet.

Elle repose notamment sur :
- `CurrentContext`
- `SessionSnapshot`
- `ProposalCandidate`
- `SessionFSM`

### 3. Mémoire et enrichissement

Pulse produit ensuite une mémoire locale rétrospective :
- résumés de session
- faits utilisateur
- contexte réutilisable dans les échanges assistant

Cette mémoire existe déjà, mais elle reste encore :
- principalement session-centrique
- heuristique
- imparfaite

Le LLM intervient seulement quand nécessaire :
- résumé de commit
- enrichissement limité
- questions explicites

### Routes aujourd’hui exposées

- `/state`
- `/insights`
- `/facts`
- `/facts/stats`
- `/facts/profile`
- `/memory`
- `/memory/sessions`
- `/mcp/pending`
- `/mcp/decision`

---

## Ce qui est solide aujourd’hui

La fondation du système est maintenant en place.

Cela veut dire que Pulse possède déjà :
- un runtime structuré
- un cycle de session unifié
- un contexte courant cohérent
- une projection de session propre
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
- de mémoire structurée par épisodes
- de moteur de proposition vraiment contextuel
- d’agentique contrôlée

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
- le lifecycle sessionnel est unifié
- le système est assez stable pour être observé sérieusement

La prochaine étape logique n'est plus d'introduire les épisodes eux-mêmes.

Le système possède déjà :
- des épisodes temporels persistés
- un épisode courant exposé dans le runtime
- une sémantique figée sur les épisodes clos

Ce qui reste à rendre plus fort :
- la mémoire structurée autour des épisodes
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
- un cadre de contrôle utilisateur autour des IA

Et c’est précisément ce qui le rend crédible à ce stade.
