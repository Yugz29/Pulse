# Assouplissement des consignes et levée du gel de Core

Décision du 2026-09-09. L'analyse de Codex et les versions proposées puis
amendées (`AGENTS.amended.md`, adoptée) ont été retirées du dépôt le jour
même ; elles sont dans l'historique Git et localement dans
`corpus/docs/audits-retired/2026-09-09-assouplissement-instructions/`.

## Constat

Les consignes racine (`AGENTS.md`, `CLAUDE.md`) se contredisaient sur ce
qu'un agent pouvait modifier dans Core, décrivaient deux états différents de
l'index GitNexus, imposaient une analyse de graphe avant toute édition et un
routage systématique vers des workflows de skills externes. Le gel
fonctionnel de Core, décidé le 2026-09-02 pour stabiliser `/context`, a été
suspendu trois fois le 2026-09-08 pour des chantiers nécessaires : il ne
décrivait plus la réalité et coûtait une négociation à chaque fois.

## Décision

1. **Une seule source de consignes.** `AGENTS.md` porte le cadre de travail ;
   `CLAUDE.md` l'importe (`@AGENTS.md`) sans le dupliquer.
2. **Gel de Core levé**, remplacé par une règle de contrat : un changement
   qui touche un contrat consommé (`/context`, export du journal, identité
   de session, `reconstruction_version`, version des observations, schéma
   de `trace.db`) exige une note datée, un bump de version et la mise à jour
   des consommateurs dans le même chantier. Correctifs et ménage interne ne
   demandent que les tests verts. L'invariant reste : Core collecte sans
   dépendre d'un modèle.
3. **Autonomie technique bornée au chantier.** Les choix réversibles se
   décident sans validation fichier par fichier ; une autorisation donnée
   vaut pour le chantier nommé, pas au-delà. On demande quand une information
   ou une autorisation manque réellement (données menacées, rupture externe,
   nouvelle destination de données, action irréversible, choix produit).
4. **GitNexus et skills facultatifs.** Aucun outil n'est un passage obligé ;
   comprendre l'impact reste exigé. Réindexation en `analyze --index-only`
   pour ne pas régénérer les blocs de consignes.
5. **La Vision reste canonique.** Quand un chantier la rend fausse, on la met
   à jour dans le même chantier ; elle n'est pas rétrogradée derrière la
   conversation.
6. **Suppression de code versionné autorisée** ; l'archivage hors dépôt reste
   réservé à ce que l'utilisateur désigne (Lab, traces, corpus).

## Ce qui ne change pas

Collecte indépendante de l'IA, provenance, masquage, permissions, archives,
hooks Git et Claude (collecte, contrôle avant push), CI, corpus gelés
d'évaluation. Pas de push ni de publication sans autorisation. Les anciennes
décisions gardent leurs limites comme périmètres historiques de leurs lots ;
la liste « Plus tard » de la Vision reste une priorité produit, révisable par
demande, pas une interdiction technique.

## Écarts par rapport à la proposition initiale

La proposition de Codex faisait primer la demande courante sur les consignes
du dépôt et la Vision, et étendait les autorisations passées de la
conversation. Ces trois points sont retenus dans le sens inverse : le
document tient sur la durée, la conversation le met à jour explicitement.

## Fichiers touchés

`AGENTS.md`, `CLAUDE.md`, `README.md`, `core/README.md`, `docs/VISION.md`,
`core/TODOS.md`, `intelligence/TODOS.md`, cette note ; dans
`.claude/skills/`, `gitnexus-guide` (portée facultative à la place de
« Always Start Here ») et `gitnexus-cli` (`--index-only` obligatoire). Les
quatre autres skills GitNexus gardent leur texte générique ; le guide précise
qu'il ne fait pas règle. Aucun code, hook ni configuration modifié.
