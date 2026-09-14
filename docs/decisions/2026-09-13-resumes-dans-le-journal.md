# Les résumés de session dans le journal HTML de Core

**Date :** 2026-09-13
**Statut :** tranchée, implémentée (Core 0.8.1.0, PR 1 du chantier interface) ;
addendum du 2026-09-14 (Core 0.8.2.0) : ordre de la zone Reprise et sessions
en alerte
**Chantier :** `core-html-resumes`
**Remplace :** le premier point du §13 de la
[spec session-summary](../specs/2026-09-03-session-summary.md) (affichage des
résumés hors périmètre) et le non-objectif « pas d'interface » de son §2.

## Décision

La page d'accueil `GET /` gagne deux zones en tête, avant « Maintenant » :

1. **Reprise.** Le résumé que `GET /context` expose comme
   `last_session_summary`, par la même requête et le même ordre : fin de
   session la plus récente avant maintenant, puis génération la plus récente.
   `doing`, `stopped_at` et `open` en clair, nature des points ouverts quand
   l'événement la porte, fichiers centraux. Session, bornes, `prompt_version`,
   `model_id`, date de génération et confiance en ligne de pied, marquées
   « interprétation du modèle ».
   - Au-delà de **24 h** depuis la fin de la session résumée, un bandeau le dit.
   - ~~Au-dessus, la liste de **toutes les sessions de travail closes
     d'aujourd'hui et d'hier qu'aucun résumé ne couvre**~~ Remplacé par
     l'addendum du 2026-09-14 : sous la carte, la liste des seules sessions
     éligibles d'hier qu'aucun résumé ne couvre, qu'elles précèdent
     ou suivent le résumé affiché. Une session refusée à 10 h reste visible
     quand celle de 15 h, le même jour, a été résumée. Couverte veut dire
     qu'un résumé porte son identifiant, ou que ses bornes chevauchent celles
     d'un résumé (identité changée par une reconstruction ultérieure).
2. **Résumés.** Tous les résumés stockés, par jour de session puis par
   session, du plus récent au plus ancien, repliés, sans pagination. Chaque
   session dépliée montre toutes ses versions coexistantes, la plus
   récemment générée en premier ; chaque fiche porte sa `prompt_version` en
   clair. Aucune version ne fait foi dans la page : la préséance entre
   versions n'est pas tranchée.

La section déterministe qui s'appelait « Reprise » (dernier test, dernière
erreur, git local) devient **« Faits de reprise »**, ancre `#faits-de-reprise`.
L'ancre `#reprise` désigne désormais la zone 1. Aucun lien du dépôt ne visait
l'ancienne ancre, seuls les tests la citaient. L'export Markdown garde son
titre `## Reprise` : il n'est pas modifié par ce chantier.

## Pourquoi

Au 2026-09-13, 51 résumés sont stockés dans `trace.db` et aucun n'est rendu :
la timeline exclut `session_summary`, `/context` n'expose que le dernier, et
`pulse-intel show` exige un identifiant. L'utilisateur juge les sorties dans
un terminal et ne se sert pas de Pulse. Le silence sur une session refusée
par Intelligence a coûté deux fausses pistes dans la semaine : le lot du
2026-09-13 a refusé la session de 126 min du 12 au plafond de tokens, et rien
ne le montrait hors du journal d'Intelligence.

## Ce qui ne change pas

- Lecture seule : aucune écriture, aucun appel de modèle depuis la page.
- Aucun contrat consommé : `GET /context`, `/context/sessions`, export du
  journal, identité de session, `reconstruction_version`, version des
  observations et schéma de `trace.db` sont inchangés. Une méthode de lecture
  s'ajoute au stockage (`activities_of_type`), sans index nouveau.
- La timeline continue d'exclure `session_summary` : un résumé n'est pas une
  activité observée.
- `/day/<date>` n'affiche pas les zones, et `/days` n'est pas sollicité.

## Limites connues

- Core ne lit pas l'état local d'Intelligence. La page sait qu'aucun résumé
  ne couvre une session, pas pourquoi : refus, ~~seuils de candidature~~ ou
  lot pas encore passé. ~~Les sessions de 0 minute y figurent donc aussi.~~
  Remplacé par l'addendum du 2026-09-14 : Core applique les seuils de
  candidature de la spec, les sessions qu'ils écartent sont seulement
  comptées.
- 12 des 40 sessions résumées au 2026-09-13 n'existent plus sous leur
  identifiant dans la reconstruction 4. Le saut vers la tranche de timeline
  (PR 2) devra se replier sur les bornes.

## Mesures et rejeu

Sur une copie de `trace.db` du 2026-09-13 à 14:37 (51 résumés) :

| Mesure | Valeur |
| --- | --- |
| Lecture des 51 résumés | 6 ms |
| Reconstruction de la veille, 2 791 événements | 21 ms |
| Zones 1 et 2 complètes, jour courant fourni | 26 ms |
| `GET /` servi par un Core jetable | 0,07 s, 83 Ko |

Rejeu : copier `~/.pulse_v2/trace.db`, lancer
`PULSE_V2_DB_PATH=<copie> PULSE_CORE_PORT=8799 .venv/bin/python -m daemon_v2.main`
depuis `core/`, ouvrir `http://127.0.0.1:8799/`, arrêter le processus par son
PID. Tests : `core/tests_v2/test_session_summaries.py`.

## Addendum du 2026-09-14 : la reprise d'abord, les seules anomalies en alerte

**Constat.** Le 2026-09-14, la zone s'ouvrait sur un bloc rouge « 5 session(s)
close(s) sans résumé », avant « En cours ». Les cinq sessions, du 13,
duraient de 0 à 4 minutes pour 4 à 19 activités : toutes sous les deux seuils
de candidature d'Intelligence, donc jamais résumées. Le bloc signalait chaque
jour une anomalie qui n'en était pas une, au-dessus de la reprise.

**Décision.**

- **Ordre.** La carte d'abord : `doing`, `stopped_at`, `open`, précédés du
  bandeau de 24 h quand il s'affiche, puisqu'il date la reprise. Les signaux
  de santé ensuite, dans la même zone.
- **Seuils.** Core applique ceux du §7 de la spec session-summary : une
  session close est candidate si `duration_minutes >= 10` ou
  `activity_count >= 30`, écartée seulement sous les deux (constantes
  `CANDIDATE_MIN_MINUTES` et `CANDIDATE_MIN_ACTIVITIES` de
  `core/daemon_v2/session_summaries.py`). Durée et nombre d'activités sont
  calculés comme dans `/context/sessions`, la vue qu'Intelligence classe, et
  un test le vérifie. Les seuils ne sont pas exposés : il faudrait que Core
  lise la configuration d'Intelligence, ou que l'événement `session_summary`
  change de contrat. La configuration du poste ne les surcharge pas.
- **Jour.** Le lot launchd de 06:30 résume la veille. Une session éligible
  d'aujourd'hui sans résumé attend ce lot : ce n'est pas une anomalie.
- **Rendu.** Sous la carte, le bloc rouge liste les seules sessions éligibles
  d'hier sans résumé. Une ligne grise compte ensuite les éligibles
  d'aujourd'hui et les sessions sous les seuils, seuils affichés. Aucune
  route ni aucun contrat consommé ne change.

**Limites.**

- Core ne sait pas quand le lot est passé : entre minuit et la fin du lot du
  matin, les sessions éligibles de la veille sont en rouge.
- Une session d'aujourd'hui refusée par un passage du jour (lancement à la
  main, ou session close avant 06:30) reste en gris jusqu'au lendemain.
- Des seuils changés dans `~/.pulse_intelligence/config.toml` ne sont pas
  suivis ; la ligne grise affiche ceux que la page applique.
- Si Intelligence passe à un service résident (§8 de la spec), la règle du
  jour est à revoir.

**Vérification.** Sur une copie de `trace.db` du 2026-09-14 à 23:20 : aucun
bloc rouge ; ligne grise « 1 session(s) éligible(s) d’aujourd’hui, pas encore
résumée(s). 5 session(s) close(s) sous les seuils de candidature (moins de
10 min et moins de 30 activités), sans résumé prévu. » Au même moment,
`pulse-intel list` classe les mêmes sessions de la même façon : les cinq du 13
« trop courte », `work-1` du 14 (10 min, 19 activités) `candidate`. Tests :
`core/tests_v2/test_session_summaries.py`.
