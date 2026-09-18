# Compteur de l'étape 4 : la veille du Mac ne sort pas un lot du compteur

**Date :** 2026-09-15
**Statut :** tranchée
**Précise :** [prompt v7 activé](2026-09-12-prompt-v7.md), clause « Mac éveillé »
du compteur de l'étape 4

## Décision

- « Mac éveillé » disqualifie la mesure de durée, pas le jugement de reprise.
  Un lot qui tourne Mac en veille compte ; son `generation_ms` est marqué non
  significatif.
- Un lot ne sort du compteur que s'il est incomplet ou interrompu, comme celui
  du 2026-09-08 (jour 4), interrompu par un timeout Core après deux créations.

## Pourquoi

- Le critère de l'étape 4 porte sur la qualité des reprises : quatre sur cinq
  jugées justes et utiles (spec du 2026-09-03, §12).
- La veille de la machine ne change ni l'entrée lue par le modèle ni sa
  sortie. La vue est prise à l'heure de référence du lot et tracée par
  `input_hash` ; le décodage est déterministe (argmax le 14, température 0.0
  le 15). Le 2026-09-15, l'entrée des six résumés des lots du 14 et du 15,
  reconstruite depuis Core, redonne leurs six `input_hash`.
- La lecture stricte rendait le critère inatteignable pour une raison sans
  rapport avec le produit : le lot launchd de 06:30 tourne Mac en veille (lots
  des 10, 11, 12, 14 et 15 septembre).

## Conséquences

- Les lots du 2026-09-14 et du 2026-09-15 comptent : jours 10 et 11 du
  journal. `generation_ms` est non significatif pour les deux (lot du 14 :
  06:32 → 14:24 sans réveil complet du Mac ; lot du 15 : 3 h 15 de veille sur
  3 h 18).
- Leurs verdicts attendent la lecture de l'utilisateur ; rien n'est consigné
  dans `docs/dogfooding.md` avant.
- Hors du champ de cette précision : un lot complet sans aucun résumé, comme
  celui du 2026-09-13 (jour 9, entrée refusée au plafond avant génération),
  que le journal tient pour non jugeable.

## Précision du 2026-09-18 : le lot du jour est le passage planifié, jamais une relance

Le lot du jour est le passage déclenché par la planification de 06:30, même
s'il démarre plus tard au réveil du Mac, et lui seul. Une relance manuelle
ne compte pas comme lot du jour, qu'elle vienne le jour même ou plus tard ;
ses résumés sont jugés hors compteur, comme `0ababe11` le 13. Un passage
interrompu reste « interrompu » au compteur même si le passage suivant
rattrape ses sessions : le
[rattrapage](2026-09-18-rattrapage-des-jours-non-resumes.md) efface la perte
de sessions, pas l'absence du lot. Le 18 : « interrompu, sessions
rattrapées » (16 résumés par relance manuelle à 10:38, hors compteur).
