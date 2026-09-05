# Spec — LLMProvider et branchement du vrai modèle — v2

**Date :** 2026-09-05
**Chantier :** étape 3 du §12 de [`2026-09-03-session-summary.md`](2026-09-03-session-summary.md)
**Statut :** validée, à implémenter

> **v2 du 2026-09-05** — réécrite après relecture des étapes 1 et 2 livrées. La
> v1 proposait un second paquet (`intelligence/llm/`, `intelligence/summary/`),
> une abstraction qui doublait le `Summarizer` existant, un schéma de sortie
> incompatible avec `parse_model_output`, un `requirements.txt` qui n'existe
> pas et un corpus dans `bench/`. Rien de tout cela n'est repris : cette
> version se branche sur ce qui tourne.

## 1. Objectif

Rendre le choix du modèle et du runtime d'inférence réversible, **sans toucher
au contrat métier du résumé de session déjà livré**.

On code contre un faux modèle, on compare un modèle local à une référence
distante sur le corpus, et on remplace le local s'il déçoit — en changeant des
lignes de configuration, jamais du code de résumé.

## 2. Ce qui est déjà livré, et qu'on ne touche pas

Les étapes 1 et 2 (PR #33, #34, #36) ont livré tout le tour du modèle. Cette
spec n'ajoute que le modèle lui-même.

| Élément livré | Emplacement | Statut |
| --- | --- | --- |
| `Summarizer` (Protocol : `model_id`, `summarize(str) -> str`) | `pulse_intelligence/summarizer.py` | **inchangé** |
| `SummarizerError` | idem | **inchangé** |
| `FakeSummarizer` | idem | **inchangé** |
| Entrée du modèle (`build_model_input`, `serialize_input`, `input_paths`) | `pulse_intelligence/session_input.py` | **inchangé** |
| Sortie du modèle (`parse_model_output`, `ParsedSummary`) | `pulse_intelligence/session_summary.py` | **inchangé** |
| Émission, idempotence, état local, CLI | `session_summary.py`, `state.py`, `cli.py` | **inchangé** |

Conséquence : le travail de cette spec se réduit à **fournir un `Summarizer`
qui parle à un vrai modèle**. Tout le reste est déjà branché et testé.

## 3. Décisions

- Un seul modèle en mémoire à la fois. Pas de Model Router (« Plus tard » de la
  Vision).
- **Deux couches, pas deux abstractions.** `Summarizer` reste le contrat
  métier ; `LLMProvider` vit dessous et ne transporte que du texte.
- Le contrat de sortie reste celui de la v2 du 2026-09-03 : `reprise` +
  `structured`. Une sortie non conforme est rejetée, jamais réparée.
- Modèle local retenu : **`mlx-community/Qwen3.8-27B-4bit`**, servi par
  `mlx-lm`, thinking désactivé.
- Aucune dépendance à Ollama. `mlx-lm` reste l'extra `mlx` de `pyproject.toml`.
- Le provider distant est **générique et neutre** : n'importe quel endpoint
  compatible OpenAI, configuré par variables d'environnement. Aucun nom de
  service, aucune URL de fournisseur dans le dépôt.

## 4. Architecture — deux couches

```text
summarize_session(session, summarizer=…, …)      ← livré, inchangé
        │
        ▼
Summarizer            model_id : str
  .summarize(model_input: str) -> str            ← contrat métier, livré
        │
        ├── FakeSummarizer                       ← livré, inchangé
        └── ProviderSummarizer  (nouveau)        ← enveloppe le prompt
                    │
                    ▼
            LLMProvider  (nouveau)               ← transporte du texte
              .complete(request) -> result
                    ├── FakeProvider
                    ├── OpenAICompatibleProvider
                    └── MLXProvider
```

Le partage des rôles est strict :

- **`Summarizer`** connaît le prompt et le contrat de sortie. Il reçoit
  l'entrée sérialisée, l'enveloppe dans le prompt versionné, appelle le
  provider, rend le texte brut. Il ne parse rien — `parse_model_output` s'en
  charge en aval, comme aujourd'hui.
- **`LLMProvider`** ne connaît ni Pulse, ni les sessions, ni le format de
  sortie. Il prend un système + un prompt, rend du texte. Aucun parsing, aucun
  retry sur contenu.

Un seul `ProviderSummarizer` suffit pour les trois providers : c'est le
provider qui change, pas l'enveloppe.

### Emplacement

```text
pulse_intelligence/
  llm/
    __init__.py
    provider.py          # LLMProvider, CompletionRequest, CompletionResult, ProviderError
    fake.py              # FakeProvider
    openai_compatible.py # OpenAICompatibleProvider
    mlx.py               # MLXProvider (import de mlx_lm paresseux)
  prompts/
    session_summary_v1.md
  provider_summarizer.py # ProviderSummarizer : Summarizer bâti sur un LLMProvider
```

Sous-module de `pulse_intelligence`, pas un second paquet : `pyproject.toml`
déclare `packages = ["pulse_intelligence"]` et un paquet de premier niveau ne
serait pas installé. Passer à `find` n'est pas nécessaire — les sous-modules
suivent le paquet.

## 5. Interface

```python
# pulse_intelligence/llm/provider.py
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 1024
    temperature: float | None = None   # None = paramètre non envoyé


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str              # "fake" | "openai-compatible" | "mlx"
    model: str                 # identifiant exact du modèle servi
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int


class ProviderError(RuntimeError):
    """Réseau, chargement, timeout. Jamais un problème de contenu."""


class LLMProvider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...
    def healthcheck(self) -> bool: ...
```

Règles :

- `complete` est synchrone et bloquant. Le pas 3 est une CLI batch ; pas
  d'async tant qu'aucun service résident n'existe (étape 5).
- Toute erreur d'infrastructure lève `ProviderError`. `ProviderSummarizer` la
  traduit en `SummarizerError`, que `summarize_session` sait déjà traiter
  (`session_summary.py`, `except (SummarizerError, InvalidModelOutput)`).
- Aucune logique métier dans les providers. Pas de parsing, pas de retry.
- `temperature` par défaut **non envoyée** (`llm_temperature` absente) :
  certains modèles derrière un endpoint compatible refusent le paramètre
  (vu en réel : « `temperature` is deprecated for this model », 400). La
  reproductibilité à `0.0` se demande explicitement en config ; le provider
  négocie en dernier recours si un modèle refuse une valeur pourtant fixée, et
  `CompletionResult.dropped_parameters` en garde trace — à reporter dans le
  `meta.json` d'`eval` (§10), un résumé produit sans `0.0` n'étant pas
  reproductible de la même façon.

## 6. Les trois providers

### 6.1 `FakeProvider`

Rend une sortie fixée, au format `reprise`/`structured` de la section 8, dérivée
de quelques champs du prompt (l'identifiant de session au minimum) pour que les
tests vérifient que le bon contexte a circulé. Options `fail_with` (chemin
d'erreur) et `invalid_output` (rejet d'une sortie non conforme). Aucune
dépendance.

> `FakeSummarizer` reste par ailleurs en place et sert la majorité des tests
> existants : `FakeProvider` teste la couche provider, pas le résumé.

### 6.2 `OpenAICompatibleProvider`

Appel HTTP `POST {base_url}/v1/chat/completions` vers n'importe quel endpoint
compatible, quel qu'en soit l'hébergeur. Configuration **par variables
d'environnement neutres uniquement** :

```
PULSE_LLM_BASE_URL   racine de l'API
PULSE_LLM_API_KEY    jeton — jamais en config, jamais dans le dépôt
PULSE_LLM_MODEL      nom du modèle côté endpoint (défaut : config.model_id)
```

Timeout : `config.generation_timeout_s` (déjà présent, 120 s par défaut) — pas
de nouvelle clé.

Usage prévu : **référence de comparaison** sur le corpus, et dépannage quand le
modèle local n'est pas disponible. Ce n'est pas le provider de production.

### 6.3 `MLXProvider`

- Dépendance : `mlx-lm`, via l'extra `mlx` de `pyproject.toml` (déjà déclaré).
  Import **paresseux**, à l'intérieur de `complete`, pour qu'un environnement
  sans l'extra continue de faire tourner toute la suite.
- Modèle par défaut : `mlx-community/Qwen3.8-27B-4bit`.
- Chargement paresseux au premier `complete`, puis modèle gardé en mémoire pour
  la durée du process : un passage `run` résume plusieurs sessions sans
  recharger.
- Thinking désactivé via le template de chat (`enable_thinking=False` ou
  l'équivalent de la version de `mlx-lm` installée). Vérifié en test : la sortie
  ne contient aucun bloc de réflexion.
- `max_tokens` transmis tel quel, température 0.

> **Point à vérifier au premier chargement.** `Qwen3.8-27B` est un modèle
> **multimodal** (`model_type: qwen3_5`). Avant toute mesure, vérifier que la
> version de `mlx-lm` installée le charge en **texte seul** — que le chemin
> `load()` + `generate()` fonctionne sans entrée image et sans réclamer un
> processeur de vision. Si ce n'est pas le cas, l'alternative est une version
> de `mlx-lm` plus récente ou un modèle texte de la même famille ; la décision
> est écrite dans la note de décision du modèle, pas improvisée dans le code.

## 7. Le pont : `ProviderSummarizer`

```python
@dataclass
class ProviderSummarizer:
    provider: LLMProvider
    model_id: str            # identité du modèle, telle qu'elle entre dans l'event_id
    prompt_path: Path        # prompts/session_summary_v1.md
    max_tokens: int = 1024

    def summarize(self, model_input: str) -> str: ...
```

- Le prompt est un **fichier versionné**, identique pour tous les providers, et
  gelé pendant la comparaison sur le corpus. Sa version est déjà portée par
  `config.prompt_version` (livré, défaut `"v1"`).
- `model_id` est la **seule** identité de modèle. Elle entre déjà dans
  `summary_event_id(session_id, prompt_version, model_id)` : changer de modèle
  ou de prompt produit mécaniquement un autre `event_id`, donc un autre
  événement, sans collision avec les résumés déjà émis. Rien à ajouter.
- `ProviderError` → `SummarizerError`. Le résumé de session décide quoi faire ;
  le provider ne décide rien.

## 8. Contrat de sortie — inchangé

Le format reste celui livré et validé par `parse_model_output`
(`session_summary.py`) :

```json
{
  "reprise":    { "doing": "…", "stopped_at": "…", "open": "…" },
  "structured": {
    "project": "…",
    "intents": ["…"],
    "central_files": ["…"],
    "blockers": ["…"],
    "confidence": "high | medium | low"
  }
}
```

Contraintes déjà en vigueur, reprises telles quelles : JSON nu ou entouré de
```` ``` ```` (`_FENCE`) ; chaînes ≤ 300 caractères ; `intents` ≤ 3,
`central_files` ≤ 5, `blockers` ≤ 3 ; `confidence` dans `{high, medium, low}`.

**Le garde-fou anti-hallucination reste où il est** : un `central_files` absent
de `input_paths(session)` fait rejeter la sortie, dans `parse_model_output`. Il
n'est ni déplacé, ni dupliqué dans un module de validation.

Une sortie rejetée n'est jamais stockée ; l'échec est consigné dans l'état local
avec le modèle et la raison, et le passage continue. Pas de retry automatique :
une seconde tentative est une décision humaine.

## 9. Configuration — clés à plat

`Config` est un dataclass **plat** et `load_config` refuse les clés inconnues :
les tables imbriquées ne se chargeraient pas. Quatre clés ajoutées, dans le
style existant :

| Clé | Type | Défaut | Rôle |
| --- | --- | --- | --- |
| `llm_provider` | str | `""` | `fake` \| `openai-compatible` \| `mlx` ; vide = décision non prise |
| `llm_base_url` | str | `""` | racine de l'endpoint distant ; `PULSE_LLM_BASE_URL` prime |
| `llm_max_tokens` | int | `1024` | plafond de génération |
| `llm_temperature` | float\|null | `null` | absente = non envoyée ; `0.0` pour un résumé reproductible |

`llm_max_tokens` est à ajouter à `_INT_FIELDS`, `llm_temperature` à
`_FLOAT_FIELDS` (`config.py`), sans quoi `load_config` les refuserait comme
non-chaînes.

Champs **réutilisés**, aucun doublon créé : `model_id` (identité du modèle,
déjà obligatoire via `require_model()`), `prompt_version`,
`generation_timeout_s`.

```toml
# ~/.pulse_intelligence/config.toml
model_id = "mlx-community/Qwen3.8-27B-4bit"
llm_provider = "mlx"
llm_max_tokens = 1024
```

Basculer sur la référence distante : `llm_provider = "openai-compatible"`,
`model_id` = le nom côté endpoint, et les deux variables d'environnement. Deux
lignes, zéro modification de code.

## 10. Corpus et comparaison — `intelligence/eval/`

Le corpus reste celui du §11 de la spec du 2026-09-03 : dix sessions réelles
gelées, dans `intelligence/eval/`, avec la commande `pulse-intel eval` déjà
prévue. Pas de `bench/`.

`eval` accepte `--provider` et écrit sous
`eval/out/<provider>-<model_id assaini>/<session_id>.json`, plus un `meta.json`
par passage (durée, tokens quand le provider les rend, pic mémoire via
`resource`). La comparaison local ↔ référence distante se fait à l'œil sur ces
fichiers ; pas de score automatique.

Règle inchangée : tout changement de prompt ou de modèle passe par `eval` avant
d'être activé, et le rapport est joint à la PR.

## 11. Tests

Sans réseau ni modèle, dans la suite par défaut :

- `FakeProvider` — nominal, `ProviderError`, sortie non conforme ;
- `ProviderSummarizer` — le prompt versionné enveloppe bien l'entrée sérialisée,
  `ProviderError` ressort en `SummarizerError`, `model_id` est transmis tel quel ;
- `OpenAICompatibleProvider` — requête construite (URL, en-têtes, corps) et
  réponse décodée contre un faux endpoint local, sur le patron du faux Core
  existant ; jeton absent = `ProviderError`, jamais un appel anonyme silencieux ;
- configuration — les trois nouvelles clés chargent, `llm_max_tokens` refuse une
  valeur non entière, une clé inconnue reste une erreur.

Marqués `slow` et désactivés par défaut : `MLXProvider` charge le modèle, résume
une session du corpus, la sortie passe `parse_model_output` et ne contient aucun
bloc de réflexion.

`intelligence/` continue de n'importer aucun module de Core (critère (c) du
pas 3).

## 12. Hors périmètre

- Model Router, plusieurs modèles en mémoire.
- Service résident et API HTTP d'Intelligence — étape 5, port 8767 réservé, non
  utilisé ici.
- Streaming.
- Toute intégration propre à un runtime au-delà de son endpoint compatible.
- Réparation automatique d'une sortie non conforme.
- Toute modification du contrat d'événement `session_summary` côté Core, gelé.

## 13. Ordre de livraison

1. `llm/provider.py` + `FakeProvider` + `ProviderSummarizer` + prompt v1, avec
   leurs tests. La CLI tourne de bout en bout sur `llm_provider = "fake"`.
2. `OpenAICompatibleProvider` et les clés de configuration. Premier vrai résumé,
   à la main, sur une session réelle.
3. Corpus `eval/` gelé, `pulse-intel eval --provider`, passage de référence
   distante sur les dix sessions.
4. `MLXProvider` : vérification texte-seul du modèle multimodal, chargement,
   mesure mémoire et durée, passage local sur les dix mêmes sessions.
5. Comparaison à l'œil, note de décision sur le modèle avec le rapport `eval` en
   lien, `VISION.md` mis à jour.

## 14. Critères d'acceptation

1. La CLI s'exécute de bout en bout avec `llm_provider = "fake"`, sans réseau.
2. Le même code, sans modification, produit des résumés valides sur les dix
   sessions du corpus avec `llm_provider = "openai-compatible"`.
3. `llm_provider = "mlx"` tient en mémoire sur le M3 Max 36 Go avec la plus
   grosse session du corpus — vérifié avant téléchargement, puis mesuré.
4. Aucun résumé stocké ne contient un chemin absent de son contexte source (déjà
   garanti par `parse_model_output` ; le corpus le confirme sur du réel).
5. Changer de modèle ou de provider = changer des lignes de `config.toml`, zéro
   modification de code.
6. `Summarizer`, `parse_model_output`, l'émission et l'état local sont
   **identiques** à ce qui est livré : la suite d'Intelligence passe sans
   qu'aucun test existant ait été réécrit.
