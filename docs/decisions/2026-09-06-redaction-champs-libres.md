# Rédaction des champs libres : une copie de référence, tous les champs

**Date :** 2026-09-06
**Statut :** tranchée
**Source :** audit externe du 6 septembre, défaut 9 (P2), marqueurs
synthétiques uniquement ; prolonge la récupération depuis Core de #61

## Décision

La copie de référence d'un résumé est l'événement **accepté par Core**,
après normalisation. Intelligence ne conserve plus la sortie du modèle
avant normalisation dans `state.json` : après un `201`, elle enregistre
l'événement tel que Core le renvoie, ou le relit via
`GET /activities/<event_id>`. Les entrées `emitted` n'ont plus qu'une
forme, celle que #61 a introduite avec `origin: "core"`.

Côté Core, la rédaction (`redact_command`) s'applique à **tout** champ
texte libre d'un `session_summary`, dans `reprise` et dans `structured`,
`project` compris. La liste des champs libres est définie une fois dans
le schéma, et un test l'énumère : un champ ajouté sans politique de
rédaction fait échouer la suite.

## Pourquoi

Deux affichages du même résumé différaient : `show <id>` relisait la
copie locale pré-normalisation, `show latest` interrogeait Core.
`structured.project`, texte libre accepté par le parseur, était recopié
sans passer par la rédaction alors que les listes voisines y passaient.
La garantie commentée « un texte libre n'entre jamais en base sans
rédaction » était plus large que le code.

Garder deux copies, c'est garantir qu'elles divergent un jour. La bonne
copie est celle que Core a acceptée : c'est celle que tous les
consommateurs lisent.

## Ce qui est écarté

Rédiger aussi côté Intelligence avant émission, pour que la copie locale
soit propre. Cela dupliquerait la politique à deux endroits, avec le
même risque de divergence que celui qu'on corrige. Une seule rédaction,
là où l'événement est accepté.

## Limites connues

- Les entrées `emitted` existantes sans `origin` conservent leur forme
  ancienne, non rédigée. `show <id>` sur ces entrées peut encore
  afficher un texte que Core a rédigé. Pas de migration : ces entrées
  sont locales, protégées par les permissions, et s'éteignent avec le
  temps. Une commande de nettoyage peut venir si le besoin apparaît.
- La rédaction porte sur des motifs connus (`redact_command`). Elle ne
  garantit pas l'absence de tout secret, seulement que le même filtre
  s'applique partout.

## Réexamen

Une rédaction côté Intelligence si un consommateur doit lire la sortie
du modèle avant Core. Aucun ne le fait aujourd'hui.