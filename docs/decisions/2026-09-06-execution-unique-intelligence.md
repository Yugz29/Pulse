# Exécution unique d'un passage Intelligence

**Date :** 2026-09-06
**Statut :** tranchée
**Source :** audit externe du 6 septembre, défaut 2 (P1) ; branche
`fix/intelligence-single-execution`

## Décision

Un seul passage Intelligence à la fois sur un même état local. `run` et
`summarize` prennent un verrou exclusif `flock` sur
`~/.pulse_intelligence/state.json.lock` **avant** de charger `state.json`
et le gardent jusqu'à la fin de la commande, génération et émission
comprises. Le verrou n'est jamais attendu : si un autre passage le tient,
la commande sort sur-le-champ avec le code de sortie dédié `5`, sans
lire ni écrire l'état. `list` et `show` lisent l'état sans verrou.

`save` écrit sous un nom temporaire unique (`mkstemp` dans le dossier de
l'état, mode `0600`) puis `os.replace`. Le format de `state.json` ne
change pas.

## Pourquoi

`load` lit tout le fichier, `save` le réécrit en entier sans relire le
disque. Deux processus ayant chargé le même état se réécrivent l'un
l'autre : une commande manuelle qui chevauche le job launchd, ou un `run`
long gardant un état ancien, efface des entrées `pending` ou `emitted`.
Deux passages simultanés chargent aussi deux fois le modèle local. Un
verrou sur `save` seul ne suffirait pas : la perte vient du couple
lecture-puis-réécriture, pas de l'écriture. Le nom temporaire fixe
`state.json.tmp` ajoutait une seconde course entre deux sauvegardes
réellement simultanées.

Sortir immédiatement plutôt qu'attendre : un passage peut durer vingt
minutes avec le modèle local, et le passage suivant reverra de toute façon
les mêmes candidates. Une file transactionnelle avec attribution exclusive
des travaux aurait le même effet au prix d'un second format d'état ; elle
n'est pas nécessaire tant qu'un seul poste produit les résumés.

## Limites connues

- `flock` est local au système de fichiers : deux postes partageant un état
  par réseau ne sont pas protégés. Hors périmètre, un seul poste.
- Le verrou est libéré à la mort du processus : un passage tué en cours ne
  laisse pas de verrou orphelin, mais peut laisser un `pending` qui sera
  rejoué au passage suivant, comme avant.
- Le test de régression est en threads (`flock` est par descripteur
  ouvert) ; le scénario réel est inter-processus via le wrapper launchd et
  n'est pas couvert par un test automatisé.
- Le verrou supprime la concurrence entre processus. Il ne règle pas la
  récupération après perte d'état face au vrai Core (défaut 3 de l'audit),
  traitée séparément dans le même lot.

## Réexamen

Si plusieurs producteurs de résumés doivent coexister (plusieurs modèles
en parallèle, plusieurs postes), passer à une file avec attribution
exclusive des travaux. Pas avant.
