# Fuseau de reconstruction explicite

**Date :** 2026-09-06
**Statut :** tranchée
**Source :** audit externe du 6 septembre, défaut 7 (P2), reproduit en
heure d'été sur des événements de janvier

## Décision

La reconstruction journalière utilise un fuseau explicite, porteur de
ses règles calendaires : `ZoneInfo(PULSE_RECONSTRUCTION_TZ)`, avec
`Europe/Paris` par défaut. `context_snapshot` et `daily_trace` ne lisent
plus `datetime.now().astimezone().tzinfo`.

Le fuseau utilisé est inscrit dans le `meta` de chaque trace produite,
pour que la provenance d'une journée soit lisible sans deviner.

Un changement de `PULSE_RECONSTRUCTION_TZ` est un changement de
reconstruction : il modifie potentiellement les bornes des journées, la
composition des sessions proches de minuit et leurs identifiants. Il se
fait en connaissance de cause, avec `RECONSTRUCTION_VERSION` incrémenté.

## Pourquoi

`datetime.now().astimezone().tzinfo` renvoie un décalage fixe, celui du
moment de l'exécution, pas un fuseau. En été, c'est `+02:00` ; appliqué
à une journée de janvier, il place une activité de 23 h locales dans le
jour suivant. La même journée relue en hiver donne un autre découpage.
Le déterminisme du replay, promis à `generated_at` près, ne tenait donc
pas sur toute l'année.

## Ce qui est écarté

Un fuseau stocké par journée reconstruite, au moment de sa production.
Plus juste pour un poste qui voyage, mais ce cas n'existe pas, et cela
changerait le format des traces pour porter une information qu'une
constante explicite suffit à rendre lisible.

## Limites connues

- Un historique produit avant cette décision a pu être découpé avec un
  décalage fixe. Il n'est pas migré : il est rejoué avec le fuseau
  configuré, et ses identifiants de sessions proches de minuit peuvent
  changer au premier replay. C'est la variation autorisée par la
  version de reconstruction.
- Les journées de changement d'heure (23 ou 25 heures) sont couvertes
  par les règles du fuseau, pas par un traitement particulier.

## Réexamen

Un fuseau par journée si un usage multi-postes ou nomade apparaît. Pas
avant.