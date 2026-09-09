# Pulse — cadre de travail

## Mission et autonomie

- La demande de l'utilisateur définit l'objectif et le périmètre du chantier
  en cours. Les consignes de ce fichier et de `docs/VISION.md` restent en
  vigueur pendant le chantier ; si elles sont fausses ou dépassées, on les met
  à jour explicitement plutôt que de les contourner.
- Une autorisation donnée dans la conversation vaut pour le chantier nommé.
  Elle ne s'étend pas d'elle-même au chantier suivant ni à une session
  ultérieure.
- Décider et réaliser les changements réversibles nécessaires à la mission,
  dans `core/`, `intelligence/`, les tests, les scripts et la documentation.
  Aucun répertoire n'est gelé par principe.
- Les responsabilités peuvent évoluer : déplacer, fusionner, renommer ou
  supprimer du code versionné et adapter les contrats internes si cela
  simplifie le système. Préserver le travail local préexistant de l'utilisateur.
- Rester dans l'objectif demandé. Ne pas transformer un correctif en chantier
  général ni ajouter une fonctionnalité sans rapport avec la mission.
- Résoudre les choix techniques ordinaires sans validation fichier par fichier.
  Poser une question seulement si une information ou une autorisation manque
  réellement : données menacées, rupture externe, nouvelle destination de
  données, action irréversible, ou choix produit non couvert par la demande.

## Propriétés à préserver

- Core observe et conserve les faits sans dépendre d'Intelligence ni d'un modèle.
  Une panne ou une lenteur de l'IA ne doit pas empêcher la collecte.
- Préserver les événements historiques, leur provenance et les mécanismes
  de livraison et de rattrapage. Une compatibilité de lecture peut remplacer
  un ancien mécanisme d'écriture devenu inutile.
- Préserver le masquage, les permissions, les protections des archives et
  le fonctionnement local. Ne pas introduire de transmission de données
  vers un nouveau destinataire sans autorisation couvrant cette transmission.
- Vérifier les consommateurs avant de qualifier un contrat d'externe.
  Faire évoluer les interfaces internes avec leurs appelants ; préparer une
  transition explicite pour un contrat réellement consommé à l'extérieur.
- Une suppression de code versionné n'est pas une suppression de données
  utilisateur. Les données, archives et changements locaux non sauvegardés
  demandent une protection adaptée ; ne pas les écraser pour simplifier le code.

## Contrats de Core

Le gel fonctionnel de Core est levé (décision du 2026-09-09). À sa place,
une règle de contrat :

- Un changement de Core qui touche un contrat consommé — `GET /context` et
  `/context/sessions`, format d'export du journal, identité de session,
  `reconstruction_version`, version des observations, schéma de `trace.db` —
  exige une note datée dans `docs/decisions/`, un bump de la version
  concernée et la mise à jour des consommateurs dans le même chantier.
- Les correctifs, le ménage interne, les tests et les scripts ne demandent
  rien de plus que les tests verts.
- Les versions et les schémas existants restent lisibles : une base, un
  export ou un résumé anciens se relisent sans modèle et sans migration
  destructive.

## Méthode et validation

- Lire le code concerné et vérifier ses consommateurs avant de le modifier.
  Choisir les moyens adaptés : recherche textuelle, analyse statique, tests,
  GitNexus. Aucun outil particulier n'est un passage obligé.
- Utiliser les skills pertinents lorsqu'ils apportent une aide concrète et
  sont disponibles. Pas de routage automatique ni de chaîne de revues imposée.
  Leurs procédures ne créent pas d'autorisation supplémentaire à demander
  lorsque la mission couvre déjà l'action.
- Un graphe incomplet ou sans résultat ne prouve pas l'absence d'impact.
  Compléter par le code et les tests ; signaler les limites restantes sans
  répéter indéfiniment une analyse qui ne peut pas les lever.
- Si GitNexus est réindexé, utiliser `analyze --index-only` : `analyze` seul
  régénère les blocs de consignes dans ce fichier et dans `CLAUDE.md`. Un bloc
  généré ne remplace pas ce cadre.
- Adapter les tests aux propriétés et comportements voulus. Exécuter les
  vérifications pertinentes pour le changement ; élargir selon les risques.
  Pour Core, lancer les tests depuis `core/` avec `make test` ou
  `.venv/bin/python -m pytest tests_v2`.
- Expliquer le résultat, les validations réellement exécutées et les limites.
  Signaler les conséquences concrètes d'un risque, pas seulement un score d'outil.

## Documentation et actions externes

- `docs/VISION.md` est le document canonique de direction ; en cas de
  contradiction avec un autre document du dépôt, il prime. Quand un chantier
  le rend faux, le mettre à jour dans le même chantier. Une ancienne limite
  de chantier consignée dans une décision n'est pas une interdiction
  permanente : c'est la Vision qui dit ce qui est en vigueur.
- Mettre à jour les documents rendus faux par le changement. Une note de
  décision sert aux choix durables qui méritent une justification, pas à
  chaque détail.
- Conserver les spécifications et décisions historiques en indiquant ce qui
  les remplace.
- Un audit ou une évaluation aboutit à une note de décision ou à une entrée
  de `docs/dogfooding.md`, avec verdict et paramètres de rejeu. Ses données
  de travail (prompts archivés, taxonomies, revues, rejeux, sorties de modèle,
  logs) vont dans `corpus/`, hors dépôt. Un dossier sous `docs/audits/` ne
  sert qu'à ce qui attend une réponse de l'utilisateur ; il est retiré une
  fois la réponse consignée.
- Le code versionné devenu inutile peut être supprimé ; Git en garde
  l'historique. L'archivage hors dépôt reste réservé à ce que l'utilisateur
  désigne (Lab, traces, corpus), pas au code mort ordinaire.
- Push, publication, déploiement, rupture externe ou action irréversible :
  vérifier que l'autorisation existante couvre l'action. Si elle manque,
  préparer le résultat révisable puis poser une question précise ; continuer
  les travaux indépendants. Ne pas redemander une autorisation déjà donnée
  pour la même action dans le même chantier.
