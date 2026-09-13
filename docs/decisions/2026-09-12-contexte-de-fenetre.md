# Contexte de fenêtre : ce que l'utilisateur regarde, sans le contenu

**Date :** 2026-09-12
**Statut :** tranchée, implémentée (Core 0.7.0.0, observateur version 2)
**Chantier :** `ship/observer-window-context`

## Décision

L'observateur Swift capte la fenêtre au premier plan pour toutes les
applications, via Accessibility, dans un nouveau type d'événement
`window_focused` :

- à chaque activation d'application (`NSWorkspace`, comme aujourd'hui) et à
  chaque changement de fenêtre ou de titre signalé par l'application active
  (`AXObserver` sur `AXFocusedWindowChanged`, `AXMainWindowChanged`,
  `AXTitleChanged`), sans interrogation périodique ;
- détails : `app`, `bundle_id`, `title` (`AXTitle`), `document`
  (`AXDocument` quand l'application l'expose, chemin local) et `url` ;
- l'URL vient de `AXDocument` quand c'est une adresse web, sinon, pour Safari,
  Chrome et les navigateurs Chromium, de l'`AXURL` de la zone web de l'onglet
  actif. Ni AppleScript ni autorisation d'automatisation : une seule
  autorisation, l'Accessibilité, déjà nécessaire pour le titre.

Un seul mécanisme pour toutes les applications ; le cas navigateur ajoute la
lecture de l'URL et rien d'autre.

### Rédaction, non négociable

- Jamais de contenu de fenêtre, jamais de capture d'écran : l'observateur ne
  lit que trois attributs de la fenêtre.
- Les réductions sont faites deux fois : côté observateur avant l'envoi, et
  côté Core à l'ingestion, quel que soit le producteur. C'est Core qui garantit
  ce qui entre en base.
- `title` : une ligne, 300 caractères, passé par `redact_command` (même
  politique que les autres champs libres, décision du 2026-09-06).
- `url` : origine et chemin seulement. Ni identifiants, ni paramètres, ni
  fragment : ce qui suit `?` ou `#` porte des jetons, des recherches et des
  identifiants de session (`reduce_window_url`).
- `document` : même filtre de bruit que les `file_changed`
  (`file_policy.is_noise_path`) ; un fichier de `.venv` ou de `node_modules`
  affiché par une fenêtre n'entre pas en base.
- Applications ignorées : `~/.pulse_v2/ignored_applications`, créée par
  l'installeur avec Messages, Mail, FaceTime, Trousseaux d'accès, Mots de
  passe, les gestionnaires de mots de passe courants (1Password, Bitwarden,
  KeePassXC, Dashlane, LastPass, Enpass, Strongbox, NordPass, Proton Pass) et
  Réglages Système. Un identifiant de bundle ou un nom par ligne ; le fichier
  remplace la liste par défaut. Aucun `window_focused` pour ces applications.

### Contrats

- Nouveau type plutôt que champs additifs sur `app_activated` : un
  `app_activated` par changement d'application est compté (`activations`,
  « Apps actives »). Émettre un événement par fenêtre sous ce type aurait
  changé le sens des comptes existants sans le dire.
- `window_focused` est un contexte faible, comme `app_activated`
  (`WEAK_CONTEXT_TYPES` dans `models.py`) : ne démarre ni ne prolonge une
  session, se rattache entre deux travaux forts, ne prouve aucun workspace,
  ne compte pas dans « Apps actives ».
- Observations : fait `window` (`app`, `title`, `document`, `url`) dans la
  ligne de temps, provenance `sources` comme les autres faits.
  `observation_version` passe de 1 à 2. `GET /context` reste au schéma 3 :
  un genre de fait s'ajoute, aucune clé existante ne change de sens.
- Producteur `pulse-macos-application-observer` version 2. Schéma d'événement
  inchangé (1), schéma de `trace.db` inchangé.
- Journal : une ligne « fenêtre » par fenêtre dans le HTML et le Markdown,
  sans lien cliquable.

## Pourquoi

Le journal savait quelle application était active, pas ce qu'on y faisait.
Pour un navigateur, un éditeur ou un lecteur PDF, le titre, le document et
l'URL sont la différence entre « Safari pendant 40 minutes » et « la PR #89
et la doc d'AXObserver ». La Vision listait le titre de fenêtre via
Accessibility parmi les sources présentes dans Lab et absentes de Core, « à
reconsidérer si un besoin de contexte les réclame » : la reprise fondée le
réclame.

Le rattachement faible est délibéré : regarder une page n'est pas travailler
sur un projet. La preuve de travail reste le terminal, les fichiers et Git.

## Ce qui est écarté

- AppleScript pour l'URL des navigateurs : fiable, mais une autorisation
  d'automatisation par navigateur et un dialogue de plus. L'Accessibilité
  suffit et sert déjà au titre.
- Un `app_activated` par fenêtre : voir « Contrats ».
- Ignorer aussi les `app_activated` des applications de la liste : le nom
  d'une application n'est pas un contenu, et les comptes existants en
  dépendent. La liste protège ce qui est nouveau.
- L'interrogation périodique de la fenêtre : `AXTitleChanged` suffit pour
  les changements d'onglet et de document ; les notifications rapprochées
  (chargement d'une page) sont regroupées sur 350 ms avant une seule lecture.

## Limites connues

- Sans autorisation Accessibilité pour `~/.pulse_v2/bin/PulseApplicationObserver`,
  aucun `window_focused` ; l'observateur le journalise une fois et continue.
  Un binaire reconstruit peut demander une nouvelle autorisation.
- Un changement d'URL sans changement de titre dans le même onglet n'est pas
  observé.
- Une application qui n'expose pas `AXDocument` (Electron, la plupart des
  éditeurs) ne donne que son titre ; le document n'est alors pas un chemin.
- Chrome n'expose sa zone web qu'après avoir activé son arbre
  d'accessibilité, ce que la première lecture déclenche ; la toute première
  fenêtre après un lancement peut donc n'avoir que son titre.
- ~~Les faits `window` entrent dans l'entrée du modèle d'Intelligence avec les
  autres observations ; le prompt v6 ne les décrit pas. À évaluer au prochain
  rejeu, pas dans ce chantier.~~ Remplacé par l'addendum du 2026-09-13 : les
  faits `window` restent dans la vue de Core mais sont retirés de l'entrée du
  modèle.

## Addendum du 2026-09-12 (soir) : titres à répétition et messagerie web

Vérification d'une heure : Terminal a produit 2 032 `window_focused` pour
sept titres réels. Le titre de la fenêtre porte le spinner de Claude Code
(`◐`/`◑` alternés chaque seconde), chaque alternance est un `AXTitleChanged`
et un contexte différent du précédent. Deux correctifs côté observateur,
aucun au rendu :

- **Normalisation avant comparaison** (`WindowContext.key`) : les glyphes
  de progression et symboles décoratifs (motifs braille, formes
  géométriques, dingbats, symboles divers, point médian, puce, catégorie
  Unicode « autre symbole ») sont retirés du titre pour le dédoublonnage.
  Le titre stocké reste le titre affiché.
- **Filet d'intervalle, 30 secondes par application**
  (`WindowEventRecorder.defaultMinimumInterval`) : un contexte arrivé moins
  de 30 s après le dernier événement de la même application est retenu, pas
  perdu ; le dernier état retenu est émis à l'échéance, ou dès que
  l'application quitte le premier plan. Choix du seuil sur l'heure réelle :
  la normalisation seule laisse 36 vrais changements de sous-commande, 30 s
  les ramène à 26 et 60 s à 20 ; 30 s est le plus petit filet sous le
  critère de 30 par heure, et un onglet tenu 30 secondes est toujours
  enregistré. Un test rejoue les 30 instants réels de changement de la
  première heure.

Messagerie web : deux titres Safari portaient l'adresse du compte
(`… - <adresse du compte> - Gmail`), hors de portée de la liste
d'applications. **Liste de domaines ignorés** `~/.pulse_v2/ignored_domains`
(créée par l'installeur : `mail.google.com`, `outlook.office.com`,
`outlook.live.com`, `mail.proton.me` ; un hôte couvre ses sous-domaines ;
le fichier remplace la liste par défaut, relu quand il change), appliquée
**à l'ingestion** dans Core comme le reste de la rédaction
(`daemon_v2/window_policy.py`) : un `window_focused` dont l'URL réduite est
sur un domaine ignoré est refusé en 204, ni titre ni URL n'entrent en base ;
l'`app_activated` du navigateur reste. Limite : un onglet de messagerie sans
URL capturée (titre seul) n'est pas reconnu.

## Addendum du 2026-09-12 : éligibilité dans l'entrée du modèle

> **Remplacé par l'addendum du 2026-09-13** (ci-dessous) : les faits `window`
> ne sont plus dans l'entrée du modèle. La conclusion « jamais un appui
> d'`open` » tient toujours, par absence plutôt que par refus du validateur ;
> le verrou est devenu `test_window_facts_are_kept_out_of_model_input`.

Question posée : les faits `window` sont-ils une preuve admissible pour
`open` dans Intelligence ? Réponse : non, par construction, et c'est
désormais verrouillé.

- `evidence_eligible: False` n'est pas un attribut des faits : c'est le
  marqueur des deux annexes (`previous_summary`, `agent_session`) dans
  `session_input.py`. Les faits de la ligne de temps n'en portent pas.
- `input_references` (`session_input.py`) rend chaque `ref` de la ligne de
  temps citable, faits `window` compris ; le modèle peut donc écrire `o7`.
- Le validateur du contrat courant, `_resumption_items`
  (`session_summary.py`), n'accepte qu'un appui par point et seulement deux
  genres : `command_failure` exige un fait `command` qui soit le dernier
  échec sans résolution observée ; `recorded_statement` exige un fait
  `commit` et une citation littérale de son message. Un fait `window` est
  rejeté dans les deux cas. `input_paths` ne retient que les faits `file` :
  le `document` d'une fenêtre n'est pas citable dans `central_files`.
- Les faits `window` restent dans la ligne de temps de l'entrée, donc
  utilisables pour `doing`.

Verrou : `test_window_facts_are_visible_but_never_evidence_for_open`
(`intelligence/tests/test_resumption.py`) et un commentaire dans
`_resumption_items`. À rouvrir seulement avec une version de prompt qui
décrit les faits `window` et dit ce qu'ils peuvent étayer.

## Addendum du 2026-09-13 : faits `window` hors de l'entrée du modèle

**Décision.** Intelligence retire les faits `window` de la ligne de temps
qu'elle envoie au modèle (`FACT_KINDS_HIDDEN_FROM_MODEL` dans
`intelligence/pulse_intelligence/session_input.py`), pour toutes les versions
de prompt, et leurs références de la provenance du résumé
(`observation_sources`, `input_provenance`). Core ne change pas : les faits
restent dans `trace.db`, dans les observations de `/context` et
`/context/sessions` (`observation_version` 2) et dans le journal. Les autres
faits gardent leur `ref` d'origine, sans renumérotation. Les faits `window`
reviendront dans l'entrée avec une version de prompt qui les décrit et dit ce
qu'ils peuvent étayer.

**Pourquoi.** Le lot du 2026-09-13 a refusé la seule grosse session du 12
(`0ababe11`, 126 min) au plafond du modèle local : 174 548 tokens pour
30 000. Sa ligne de temps porte 2 212 faits `window` sur 2 451, dont 2 095
titres de Terminal qui n'alternent que par le spinner de Claude Code,
enregistrés avant la normalisation du titre (addendum du soir). Aucune version
de prompt ne décrivait ces faits, aucun rejeu ne les avait évalués, le
validateur les refusait déjà comme appui d'`open`. Mesure, tokenizer du
modèle, entrée seule (le prompt et le gabarit ajoutent 1 126 tokens) :

| Entrée de `0ababe11` | Faits `window` | Tokens |
| --- | --- | --- |
| Vue complète | 2 212 | 173 422 |
| Dédoublonnage des faits consécutifs, titre normalisé | 123 | 32 306 |
| Un fait par contexte distinct | 36 | 27 288 |
| Retrait (retenu) | 0 | 25 310 |

Même avec la normalisation en production, une session de 12 min du 13 porte
13 faits `window` pour 800 tokens sur 2 404.

**Écarté.**

- Filtrer dans Core : les observations sont un contrat consommé
  (`observation_version`, note et consommateurs à mettre à jour), alors que
  Core observe juste ; c'est Intelligence qui choisit ce qu'elle envoie.
- Dédoublonner les faits consécutifs : reste au-dessus du plafond.
- Un fait par contexte distinct : passe sous le plafond, mais casse l'ordre
  chronologique et envoie des faits qu'aucun prompt ne décrit.

**Conséquences.** `input_version` reste 3 (la forme de l'entrée ne change pas)
et aucune version de prompt n'est ajoutée : aucun résumé v7 n'existait en
production, et le corpus `eval/observed` ne contient aucun fait `window`, donc
les mesures v3 à v7 restent valables. L'identité d'un résumé ne dépend pas de
l'entrée.

**Limite connue, hors périmètre.** Sans faits `window`, `0ababe11` pèse
environ 26 400 tokens sur 30 000 : une session plus longue ou plus chargée
en faits `file` peut encore dépasser le plafond.

**Vérification.** `test_window_facts_are_kept_out_of_model_input` et
`test_session_of_window_facts_only_gives_an_empty_timeline`
(`intelligence/tests/test_resumption.py`). Rejeu de la mesure depuis
`intelligence/` : `.venv/bin/python ../corpus/docs/audits/2026-09-13-lot-jour-9/breakdown.py
<date>` (hors dépôt), qui donne la vue complète, la vue sans `window` et
l'entrée construite par le code courant.

## Rejeu et vérification

- Tests : `swift test` dans `core/macos_observer` (réduction d'URL,
  classement d'`AXDocument`, liste ignorée, dédoublonnage) ; `make test`
  dans `core/` (validation et rédaction, projection, reconstruction, rendus).
- Critère d'usage : après une heure de service, le journal HTML montre pour la
  session en cours les titres, documents et URL par fenêtre ; aucun événement
  pour les applications ignorées ; aucune URL avec `?` ou `#` dans
  `trace.db`.
