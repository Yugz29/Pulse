# Proposition de vérité terrain — aucun format migré

Statut : **draft-1**, à discuter après vos réponses. `eval/observed`, `eval/expected` et leurs anciens scores restent intacts. Les fiches et `adjudications-a-completer.json` sont des dossiers en attente, pas des exemples de vérité terrain remplis par l’IA.

## Unité : une information utile à retrouver, pas une phrase dans open

L’unité est un élément de reprise identifiable : résultat, décision, limite, intention, ancre de fichier/commit, question encore inconnue ou piste inférée. Il peut être situé dans doing, stopped_at, intents, central_files, blockers ou open. Son importance et sa vérité sont deux dimensions distinctes.

Un correctif terminé peut être essentiel. Un incident toujours sans résolution observée peut être sans importance. Une intention explicitement déclarée peut avoir été abandonnée avant la reprise. L’utilité ne se déduit pas du statut ouvert/fermé.

## Champs proposés pour un élément adjudiqué

| Champ | Valeurs / rôle |
| --- | --- |
| `item_id`, `session_id` | Identités stables de l’annotation et de la session, sans changer celle du produit |
| `content` | Formulation approuvée par l’utilisateur ; pas nécessairement identique à la sortie du modèle |
| `role` | `state`, `intention`, `decision`, `navigation_anchor`, `likely_resume`, `recommendation` |
| `work_status` | `explicitly_open`, `explicitly_done`, `unknown`, `not_applicable` |
| `knowledge_basis` | `core_observation`, `actor_statement`, `previous_model_interpretation`, `inference`, `user_recollection` ; sources multiples possibles |
| `source_refs` | Chemin de source, SHA-256, pointeur JSON et éventuellement ref oN ; pas une simple référence sans document/version |
| `known_at` | Instant de l’information et distinction session / reprise ; `null` si inconnu |
| `availability_to_model` | `current_input`, `archived_agent_only_verified`, `outside_capture`, `unverified` |
| `importance` | `essential`, `useful`, `irrelevant`, `harmful`, `unknown` — décidée par l’utilisateur |
| `allowed_assertion` | `observed_at_time`, `attributed_statement`, `explicit_hypothesis`, `do_not_assert` |
| `relation` | Élément éventuellement résolu/remplacé, avec preuve et portée ; absent si non établi |
| `answer_sources` | Références aux réponses A–E et à toute précision ultérieure |
| `review` | Auteur, date, statut `pending` / `confirmed` / `disputed` / `cannot_recall` et assurance du souvenir |

`source_refs` peut rester vide pour une information nouvelle rappelée par vous. Dans ce cas elle est une **vérité utilisateur hors capture**, pas une observation Core rétroactivement créée. L’impossibilité de la retrouver avec l’entrée actuelle doit rester mesurable.

Les six catégories demandées deviennent des vues de ces dimensions :

- **explicitement ouvert** : statut ouvert, source positive attribuée et borne temporelle ;
- **explicitement terminé** : accomplissement déclaré/observé, sans extrapoler au présent ;
- **état inconnu** : statut inconnu, éventuellement utile à afficher ;
- **reprise utile mais inférée** : rôle likely_resume, base inference, importance utile/essentielle confirmée ;
- **recommandation** : rôle recommendation, même si raisonnable ; elle n’est pas un fait de session ;
- **sans importance** : importance irrelevant, indépendamment du caractère exact ou ouvert.

Ces catégories ne forment pas une enum exclusive : un fait exact et terminé peut être sans importance ; une inconnue peut être essentielle. Cela évite de transformer un conflit entre confiance et utilité en bricolage de labels.

## Exemple de structure vide, pas de réponse simulée

```json
{
  "annotation_version": "draft-1",
  "session_id": "1e420dda8b6eee77",
  "status": "pending",
  "resume_horizon_hours": null,
  "reviewer": null,
  "recall_confidence": null,
  "answers": {"A": null, "B": null, "C": null, "D": null, "E": null},
  "adjudicated_items": null,
  "cannot_know_from_capture": null
}
```

`null` signifie **pas encore répondu**, pas liste vide. `adjudicated_items: []` ne sera permis qu’après confirmation explicite qu’aucune information n’était utile pour cette session. Une note d’analyste ou une case non cochée ne vaut jamais confirmation.

## Procédure d’adjudication proposée

1. Répondre A/B de mémoire, avant d’ouvrir la sortie et les anciens critères. Noter les souvenirs incertains ; ne pas consulter l’état Git actuel pour reconstruire artificiellement l’état passé.
2. Lire les faits, puis juger la fiche entière, C/D/E et les propositions manquantes. Un rappel proposé ne doit pas créer un besoin qu’on attribuerait ensuite à la vérité terrain.
3. Transformer les réponses en éléments atomiques, sans confondre souvenir réel, valeur souhaitée et disponibilité pour le modèle. Toute synthèse faite par l’assistant reste `pending` tant que vous ne l’avez pas confirmée.
4. Résoudre les contradictions ou les garder `disputed`. En particulier, ne pas imposer le report llm_max_tokens parce qu’un ancien test l’exige.
5. Versionner une nouvelle série d’annotations **à côté** de la série historique uniquement après validation du format. Conserver les réponses originales et un historique des corrections.
6. Conserver en parallèle les scores historiques et les nouveaux scores. Les 14 sessions déjà lues sont un pilote connu, pas un test aveugle de généralisation. Réserver des sessions ultérieures pour une validation externe à ce pilote.

## Contrôles du futur format

Chaque élément confirmé doit avoir une origine, un instant ou une incertitude explicite, une importance décidée par l’utilisateur et un lien vers sa réponse. Chaque source citée doit exister dans la capture indiquée. Une inférence utile doit rester identifiée comme inférence. Une connaissance hors capture ne peut pas être comptée comme échec de raisonnement du modèle à entrée constante. Les réponses manquantes ne sont jamais comptées comme succès, échec, tâche terminée ou absence de besoin.

Aucun parseur, importeur ou validateur de production n’est ajouté dans cette mission.

## Arguments consignés pour la décision de format

- **2026-09-13, fiche 14 (`eef4956b`).** L'attente historique d'`eval/expected`
  exige le report `carried_over` llm_max_tokens / passage de référence, que la
  réponse C4 juge nuisible et que git montre réglé au début de la session
  (détail et preuves dans la [fiche 14](fiches/14-eef4956b36dd37ce.md)). Tant
  que la décision n°4 du 2026-09-11 tient, l'attente n'est pas corrigée et
  `eval` compte la session non conforme sous tout prompt v5+, à cause du seul
  point attendu faux. Sur `v7-corpus`, o19, jugé juste et utile par la
  décision v7, n'est reconnu par aucune attente et rangé « en plus » (signalé,
  sans effet sur la conformité) : eval échoue la session sur un point faux et
  ne crédite pas le point correct. Le format retenu devra dire
  comment une réponse de vérité terrain remplace ou marque `disputed` une
  attente historique, sans effacer la série d'origine (procédure, point 4
  et 5).
