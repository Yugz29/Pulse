"""Format commun d'une session d'agent vivante : qui, état, actions.

Ce module ne connaît aucun agent en particulier — ni son format de journal,
ni le nom de ses outils. C'est le contrat que doit produire tout adaptateur
(aujourd'hui : ``agent_transcript``, pour Claude Code) et que ``agent_live``
et le rendu (``renderers/live``) se contentent de porter.

Une session vivante porte trois familles de faits :

- **qui** : un identifiant d'agent (``agent``), un nom affiché
  (``agent_label``), une session (``session_id``), un dossier (``cwd``) et un
  projet (``project``) ;
- un **état** : ``state`` et son libellé ``state_label`` ; un état non
  reconnu ou absent vaut ``STATE_UNKNOWN``, jamais une valeur inventée ;
- ses **actions**, ou ``None`` si elles ne sont pas observables (transcript
  introuvable ou illisible) : ``commands`` (chacune avec ``description``,
  ``command`` déjà masqué, ``outcome`` — ``OK``/``FAILED``/``INTERRUPTED`` —,
  ``at`` et ``test_command``), ``files`` modifiés (chemin, décompte des
  changements, dernière heure), et les tests (``last_test``, ``test_count``,
  ``failed_test_count``).

``MAX_COMMANDS``, ``MAX_FAILURES`` et ``MAX_FILES`` bornent ce que le format
retient de chaque liste ; le rendu ne doit jamais en afficher plus qu'un
adaptateur n'en garde.
"""

from __future__ import annotations

STATE_UNKNOWN = "inconnu"

OK = "ok"
FAILED = "échec"
INTERRUPTED = "interrompue"

MAX_COMMANDS = 10
MAX_FAILURES = 8
MAX_FILES = 8
