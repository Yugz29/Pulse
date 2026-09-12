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
- Les faits `window` entrent dans l'entrée du modèle d'Intelligence avec les
  autres observations ; le prompt v6 ne les décrit pas. À évaluer au prochain
  rejeu, pas dans ce chantier.

## Addendum du 2026-09-12 : éligibilité dans l'entrée du modèle

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

## Rejeu et vérification

- Tests : `swift test` dans `core/macos_observer` (réduction d'URL,
  classement d'`AXDocument`, liste ignorée, dédoublonnage) ; `make test`
  dans `core/` (validation et rédaction, projection, reconstruction, rendus).
- Critère d'usage : après une heure de service, le journal HTML montre pour la
  session en cours les titres, documents et URL par fenêtre ; aucun événement
  pour les applications ignorées ; aucune URL avec `?` ou `#` dans
  `trace.db`.
