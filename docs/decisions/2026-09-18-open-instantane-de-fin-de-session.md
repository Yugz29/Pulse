# `open` par session reste un instantané de fin de session

**Date :** 2026-09-18
**Statut :** tranchée
**Précise :** [reprise fondée](2026-09-08-reprise-fondee.md) (politique de
`open`), [prompt v7](2026-09-12-prompt-v7.md)
**Ouvre :** un chantier « état ouvert par projet », rattaché au cadrage
[résumés en continu](2026-09-17-resumes-en-continu.md)

## Décision

- Le champ `open` du résumé de session reste en l'état, prompt v7 : il se
  lit comme un **instantané de fin de session** — ce qui était en échec ou
  déclaré non fait au moment où la session s'est close — et pas comme une
  liste de points encore ouverts aujourd'hui.
- **Aucun nouveau réglage** de sélection des points ouverts n'est ajouté :
  ni règle « dernière commande du projet », ni fenêtre de résolution, ni
  fermeture par la session suivante. Les règles rejouées le 18 corrigent des
  fausses alertes et en créent d'autres ; aucune ne vaut le prix d'un
  changement d'entrée du modèle.
- La suite est un **état ouvert par projet**, mis à jour au fil des
  sessions et **fermable** (par un fait observé ou par l'utilisateur), à
  traiter dans le cadrage du mode continu, pas dans le résumé de nuit.

## Constats (rejeu du 2026-09-18 sur les 52 résumés v7 en base)

- 27 résumés ont un `open` non vide : 11 points `command_failure` sur
  6 résumés, 25 points `recorded_statement` sur 21 résumés.
- **Échecs de commande : 11 points, 4 vraies alertes.** Les quatre viennent
  de deux endroits que l'utilisateur a quittés sans y revenir (DevNote le
  17, `git-workflow-demo` le 11). Sur les 7 autres : 3 sont résolus **dans
  la session résumée elle‑même** (une faute de frappe suivie du bon `cd`,
  deux `git commit` repris quatre minutes plus tard), 1 dans la session
  suivante (conflit d'exercice commité), 3 sont les échecs Docker du 18 —
  des refus de port (`exit 125`) alors que le service répondait (`curl`
  200) et que l'exercice a été commité.
- **La règle « la dernière commande observée du projet ce jour‑là a
  échoué », navigation ignorée, ramène les fausses alertes de 7 à 3**, mais
  avec des erreurs qui ne tiennent pas à la règle : l'**attribution** de
  workspace change d'une commande à l'autre dans le même dossier (le `git
  commit` réussi de 10:58 est rattaché à une autre racine que celui qui a
  échoué à 10:57) ; les **commandes longues** en avant‑plan (`docker run`)
  ne rendent jamais 0 pendant la session, si bien qu'un service qui tourne
  se lit comme un échec ; une **faute de frappe** (`Projets/Pulse` tapé
  comme commande) reste ouverte parce que sa correction est de la
  navigation, donc ignorée. Selon qu'on prend la racine ou le dossier, la
  règle se trompe sur deux points différents.
- **Les 25 déclarations enregistrées viennent toutes de messages de
  commit** — des commits de documentation qui consignent un TODO, une
  question ouverte ou un « pas lancé ». Certaines sont **déjà résolues**
  (« Core ne sert sa version sur aucune route » : servie par `/status`
  depuis la 0.8.9.0 ; « la mesure avec le modèle n'a pas été lancée » :
  faite dans la même session, o109) et **aucune n'est jamais refermée** :
  un point déclaré le 15 est encore « ouvert » dans le résumé de sa session,
  quoi qu'il soit devenu.

## Pourquoi

- Le résumé de nuit est daté et figé (identité par session, prompt et
  modèle ; `input_hash`) : c'est sa valeur — on peut le relire et le rejouer.
  Lui demander de dire ce qui est encore ouvert *aujourd'hui* le condamne à
  se tromper dès le lendemain, et le pousse à des règles de fermeture qui
  n'ont pas leur place dans une lecture d'instantané.
- La question « qu'est‑ce qui est encore ouvert dans ce projet ? » est une
  question **par projet et dans le temps**, pas par session : elle se
  répond en croisant les sessions suivantes et les faits qu'elles apportent
  (une commande qui réussit, un commit, une réponse de l'utilisateur), et
  elle doit pouvoir être fermée à la main. C'est un état vivant, et le
  mode continu est le cadre qui en parle déjà (point 3 « état net des
  commandes », point 1 « où vivent les notes »).
- Les limites vues le 18 sont des limites de **source**, pas de prompt :
  attribution du workspace, code de sortie d'une commande longue, commandes
  de l'agent invisibles. Un réglage du résumé ne les lève pas.

## Conséquences

- Lecture des résumés v7 dans le journal et dans `docs/dogfooding.md` : un
  point `open` est jugé **au moment de la fin de session**, pas à la
  lecture ; « résolu plus tard » n'en fait pas une erreur du résumé, sauf
  quand la résolution est **dans la session** (trois cas le 18 : ce motif
  reste compté contre le résumé, comme aux jours 12 et 13).
- Le compteur de l'étape 4 ne change pas.
- Chantier ouvert, non commencé : **état ouvert par projet**, mis à jour à
  chaque session, fermable, sa place (hors `trace.db` ou non) et son
  affichage à décider dans le cadrage du mode continu ; il y est inscrit à
  côté du point « état net des commandes », qu'il remplace comme
  formulation. Les 25 déclarations de commit et les 4 vraies alertes du
  rejeu forment son premier jeu d'essai.
