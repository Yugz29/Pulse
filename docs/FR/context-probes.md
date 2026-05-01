

# Context Probes — Politique de sécurité et flux d'approbation

## Objectif

Les _context probes_ permettent à Pulse de demander ponctuellement plus de contexte sur la situation courante, sans transformer l'application en système de capture permanent.

Le principe est simple :

```text
Pulse veut lire du contexte
→ Pulse crée une demande explicite
→ Pulse explique pourquoi
→ l'utilisateur approuve ou refuse
→ seule une demande approuvée peut passer le gate d'exécution
→ l'exécution est tracée sans valeurs brutes
```

Cette phase prépare le futur enrichissement contextuel de Pulse, mais elle reste volontairement prudente.

Aujourd'hui, deux probes sont réellement exécutables : `app_context` et `window_title`. `window_title` ne retourne jamais le titre brut : il passe obligatoirement par la couche de redaction avant toute sortie. Les probes plus sensibles (`selected_text`, `clipboard_sample`, `screen_snapshot`) sont modélisés, mais non exécutés.

---

## Ce que cette phase apporte

Pulse dispose maintenant d'un pipeline complet, mais limité :

```text
Policy
→ Request
→ Debug summary
→ Store mémoire
→ Approval routes
→ Execution gate
→ Runner autorisé
→ Redaction layer si nécessaire
→ Audit event
```

Ce pipeline permet de représenter une intention de lecture de contexte, de l'expliquer, de la faire approuver, puis d'exécuter uniquement ce qui est autorisé.

---

## Fichiers principaux

```text
daemon/core/context_probe_policy.py
```

Définit les types de probes, les niveaux de consentement, la sensibilité et la rétention par défaut.

```text
daemon/core/context_probe_request.py
```

Définit une demande de probe et son cycle de vie : `pending`, `approved`, `refused`, `expired`, `executed`, `cancelled`.

```text
daemon/core/context_probe_debug.py
```

Produit une vue lisible pour une future UI de validation, sans exposer les valeurs brutes des metadata.

```text
daemon/core/context_probe_store.py
```

Stocke les demandes en mémoire uniquement. Aucun stockage disque.

```text
daemon/core/context_probe_executor.py
```

Centralise la barrière d'exécution. Une demande ne peut être exécutée que si elle est approuvée, non expirée et compatible avec sa policy.

```text
daemon/core/context_probe_runner.py
```

Contient les runners actuellement autorisés : `app_context` et `window_title`.

---

## Types de probes

| Probe | Statut actuel | Consentement | Sensibilité | Rétention | Exécution |
|---|---:|---|---|---|---|
| `app_context` | actif | implicite session | `public` | `session` | oui |
| `window_title` | actif redacted | implicite session | `path_sensitive` | `session` | oui |
| `selected_text` | modélisé | explicite à chaque fois | `content_sensitive` | `ephemeral` | non |
| `clipboard_sample` | modélisé | explicite à chaque fois | `content_sensitive` | `ephemeral` | non |
| `screen_snapshot` | modélisé | explicite à chaque fois | `content_sensitive` | `ephemeral` | non |
| `unknown` | bloqué | bloqué | `unknown` | `debug_only` | non |

---

## Règles de sécurité

### 1. Pas de lecture sensible sans demande

Pulse ne doit pas lire un contexte sensible directement.

Toute lecture future doit passer par :

```text
ContextProbeRequest
→ approval/refusal
→ execution gate
→ runner autorisé
```

---

### 2. Pas d'exécution sans approbation

Une demande doit avoir le statut :

```text
approved
```

Sinon le gate bloque l'exécution avec un `blocked_reason` :

```text
request_not_approved:pending
request_not_approved:refused
request_not_approved:expired
request_expired
policy_blocked
unsupported_probe_kind
```

---

### 3. Pas de stockage persistant par défaut

Par défaut :

```text
allow_persistent_storage = false
```

Le store actuel est uniquement en RAM.

Il ne survit pas au redémarrage du daemon, ce qui est volontaire à ce stade.

---

### 4. Pas de valeurs brutes dans les vues debug

Les vues debug exposent :

```text
metadata_keys
```

mais jamais :

```text
metadata values
```

Exemple autorisé :

```json
{
  "metadata_keys": ["raw_selection", "source"]
}
```

Exemple interdit :

```json
{
  "raw_selection": "contenu sélectionné sensible"
}
```

---

### 5. Pas de fuite dans l'audit event

Quand un probe `app_context` est exécuté, Pulse publie un event :

```text
context_probe_executed
```

Le payload contient uniquement des informations structurelles :

```json
{
  "request_id": "...",
  "kind": "app_context",
  "captured": true,
  "privacy": "public",
  "retention": "session",
  "data_keys": [
    "active_app",
    "active_project",
    "activity_level",
    "probable_task"
  ]
}
```

Les valeurs ne sont pas publiées dans l'EventBus.

---

### 6. Redaction obligatoire pour les valeurs textuelles sensibles

Avant qu'une valeur textuelle sensible puisse sortir d'un runner, elle doit passer par :

```text
redact_context_probe_value()
```

La redaction masque notamment :

```text
emails
URLs
chemins /Users/<user>
tokens évidents
secrets d'environnement
clés privées SSH / PKCS#8
```

Le résultat expose uniquement :

```json
{
  "redacted_value": "...",
  "redaction_flags": ["email", "url", "home_path"],
  "original_length": 91,
  "redacted_length": 89,
  "was_redacted": true
}
```

Le titre brut, le texte brut ou le clipboard brut ne doivent pas être publiés dans les vues debug ou dans l'EventBus.

---

## Probe `app_context`

Le probe le moins sensible actuellement exécutable est :

```text
app_context
```

Il retourne uniquement :

```json
{
  "active_app": "Code",
  "active_project": "Pulse",
  "activity_level": "editing",
  "probable_task": "coding"
}
```

Il ne retourne pas :

```text
active_file
window content
clipboard content
selected text
screen content
```

Même si `active_file` est disponible ailleurs dans le runtime, il est volontairement exclu du résultat du probe.

---

## Probe `window_title`

Le probe `window_title` est maintenant exécutable, mais uniquement en sortie redacted.

Il réutilise une donnée déjà observée par Pulse :

```text
SystemObserver.swift
→ app_activated.window_title / window_title_poll.title
→ EventBus
→ SignalScorer
→ Signals.window_title
→ run_window_title_probe()
→ redact_context_probe_value()
```

Il ne crée aucune nouvelle capture macOS.

Il retourne une structure de ce type :

```json
{
  "redacted_value": "Pulse notes for [REDACTED_EMAIL] — [REDACTED_URL] — /Users/[REDACTED_USER]/Projects/Pulse",
  "redaction_flags": ["email", "url", "home_path"],
  "original_length": 91,
  "redacted_length": 89,
  "was_redacted": true
}
```

Il ne retourne pas :

```text
titre brut
contenu de fenêtre
texte sélectionné
clipboard
capture écran
active_file
```

Si aucun `Signals.window_title` n'est disponible, l'exécution est bloquée avec :

```text
missing_window_title
```

---

## Routes backend

### Schéma des probes

```http
GET /context-probes/schema
```

Retourne :

```text
probe_kinds
consent_levels
default_policies
unknown_policy
```

Cette route sert au futur Dashboard pour afficher clairement ce que Pulse peut demander et avec quel niveau de risque.

---

### Preview non persistée

```http
POST /context-probes/request-preview
```

Crée une demande temporaire, non stockée.

Utilisation prévue : prévisualiser ce que l'utilisateur verrait avant de créer une vraie demande.

---

### Création d'une demande

```http
POST /context-probes/requests
```

Crée une demande stockée en RAM avec le statut :

```text
pending
```

---

### Liste des demandes

```http
GET /context-probes/requests
```

Filtres disponibles :

```text
status=pending|approved|refused|expired|executed|cancelled
include_terminal=true|false
```

---

### Approbation

```http
POST /context-probes/requests/<request_id>/approve
```

Passe une demande `pending` à :

```text
approved
```

---

### Refus

```http
POST /context-probes/requests/<request_id>/refuse
```

Passe une demande `pending` à :

```text
refused
```

---

### Exécution

```http
POST /context-probes/requests/<request_id>/execute
```

Exécute uniquement les demandes approuvées compatibles avec un runner autorisé.

Aujourd'hui :

```text
app_context
window_title redacted
```

Si le probe est bloqué, la route retourne :

```json
{
  "error": "probe_blocked",
  "blocked_reason": "..."
}
```

---

## Ce qui n'est pas encore fait

Pulse ne fait pas encore :

```text
- capture écran
- OCR
- lecture de texte sélectionné
- lecture de clipboard brut
- stockage persistant des demandes
- exécution de selected_text
- exécution de clipboard_sample
- exécution de screen_snapshot
```

Ces points doivent rester hors scope tant que leurs règles d'approbation, de redaction, d'audit et d'affichage utilisateur ne sont pas définies.


---

## Principe à conserver

Pulse ne doit pas devenir un aspirateur à données.

Le bon modèle est :

```text
observer suffisamment
expliquer clairement
demander avant de lire
exécuter seulement si approuvé
redacter avant de sortir
tracer sans exposer
```