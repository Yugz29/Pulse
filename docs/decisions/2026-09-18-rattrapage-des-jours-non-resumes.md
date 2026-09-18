# Rattrapage des jours non résumés depuis le dernier passage complet

**Date :** 2026-09-18
**Statut :** tranchée
**Remplace :** la fenêtre `lookback_days = 1` de la
[spec résumé de session](../specs/2026-09-03-session-summary.md) §7

## Décision

- La fenêtre de sélection de `run` va d'aujourd'hui au jour du dernier
  passage complet, plafonnée à sept jours en arrière : huit jours listés au
  plus, aujourd'hui compris. `list` et `summarize <id>` lisent la même
  fenêtre.
- Le repère est `last_complete_pass` dans `state.json` : l'instant de
  **début** d'un passage qui a lu toute sa fenêtre et traité chaque
  candidate. Un `failed` ou un `given_up` par session ne le retient pas ;
  un passage interrompu (Core ou modèle injoignable) ne l'avance pas.
  Sans repère, la fenêtre est pleine.
- La clé `lookback_days` disparaît de la configuration ; un `config.toml`
  qui la porte encore est refusé comme clé inconnue.
- On accepte la régénération après un changement de `prompt_version` ou de
  `model_id` sur toute la fenêtre : deux jours en régime quotidien, huit au
  pire. Elle n'est pas bornée autrement.

## Pourquoi

- Une fenêtre d'un jour perd définitivement les sessions d'un lot manqué :
  le 2026-09-18, le lot de 06:30 est tombé deux fois sur un Core lent
  (PR #110) ; sans relance manuelle le même jour, les 16 sessions du 17
  n'auraient jamais été résumées, le lot du 19 ne couvrant que le 18 et le
  19. Une session de 126 min avait déjà été perdue ainsi au lot du 14
  (`docs/dogfooding.md`, jour 10). Le manque était inscrit à l'inventaire
  du 2026-09-12 (S3, « politique de curseur non livrée »).
- Le repère est pris au début du passage, pas à la fin : une session close
  pendant le passage appartient à un jour que le suivant relit encore.
- Sept jours : un GET `/context/sessions` par jour, entre 0,07 s et 9 s en
  production selon la charge de la journée, sous les 60 s du client dans
  tous les cas. Au-delà d'une semaine d'absence, on tient les sessions pour
  perdues plutôt que de relire un mois à chaque passage.
- La régénération après un bump est assumée parce qu'elle est bornée par
  la même fenêtre et que l'identité (session, prompt, modèle) la rend
  visible : le lot qui suit un bump refait au plus huit jours, et un jour
  chargé comme le 17 se regénère en treize minutes.

## Conséquences

- Le lot du lendemain d'un lot manqué relit deux journées de plus et
  résume ce qui manque ; l'identité par `event_id` et le champ `summaries`
  de Core empêchent tout doublon.
- Le compteur de l'étape 4 doit dire comment on juge un lot qui rattrape
  plusieurs jours : formulation à consigner dans la décision du
  2026-09-15 une fois arrêtée.
- Le passage n'écrit `last_complete_pass` qu'à la fin : `state.json`
  garde ses quatre clés existantes, un état ancien se relit sans migration.
