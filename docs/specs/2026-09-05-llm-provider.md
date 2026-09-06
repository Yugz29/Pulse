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
    session_summary_v1.md  # conservé : rejoue les passages de référence de l'étape 3
    session_summary_v2.md  # courant depuis le 2026-09-06
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
    dropped_parameters: tuple[str, ...] = ()   # paramètres retirés à la négociation


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
- `max_tokens` transmis tel quel, température selon la config.
- **Plafond d'entrée `llm_max_input_tokens` (défaut 30 000).** Au-delà, le
  provider **refuse avant le prefill** avec un `ProviderError` explicite. Mesuré
  au spike B : sur un M3 Max 36 Go, une entrée de 60k tokens fait planter Metal
  en OOM (pic ~28 Go), quand la plus grosse session réelle (20 901 tokens réels) tient
  à 19,77 Go. Un OOM Metal n'est pas une erreur propre ; le refus en amont l'est.

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
    prompt_path: Path        # prompts/session_summary_<prompt_version>.md
    max_tokens: int = 1024

    def summarize(self, model_input: str) -> str: ...
```

- Le prompt est un **fichier versionné**, identique pour tous les providers, et
  gelé pendant la comparaison sur le corpus. Sa version est déjà portée par
  `config.prompt_version` (livré ; défaut `"v2"` depuis le 2026-09-06). **Version courante : `v2`**
  (2026-09-06, activée dans la config de dogfooding après mesure sur le corpus,
  voir §10). `v1` est conservée telle quelle : elle rejoue les passages de
  référence de l'étape 3 et reste la version des résumés déjà émis.
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
| `llm_max_tokens` | int | `2048` | plafond de génération (voir ci-dessous) |
| `llm_temperature` | float\|null | `null` | absente = non envoyée ; `0.0` pour un résumé reproductible |

`llm_max_tokens` vaut **2048 et non 1024** : au passage de référence (PR 3),
1024 tronquait 3 des 10 sessions réelles — la complétion s'arrêtait avant la
fence JSON de clôture (`completion_tokens = 1024` pile), et `parse_model_output`
rejetait une sortie pourtant valide. Un défaut qui échoue sur 30 % du corpus
réel est un mauvais défaut.

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
llm_max_tokens = 2048
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
par passage (durée, tokens quand le provider les rend, et **`dropped_parameters`
par session** — un résumé produit sans `temperature = 0.0` n'est pas
reproductible de la même façon). La comparaison local ↔ référence distante se
fait à l'œil sur ces fichiers ; pas de score automatique.

**Taille réelle des sessions.** Le corpus gelé plafonne à **20 901 tokens
d'entrée** (la plus grosse, `3cabaefb`, `prompt_tokens` compté par le tokenizer,
dans `meta.json` — même compte pour Qwen3.8-27B et Qwen3.5-9B). Les premiers
passages annonçaient « ~6 500 » : c'était une estimation `len/4` du JSON
sérialisé, qui sous-compte ×3,3 ; elle n'est plus affichée nulle part, le seul
compte de référence est `prompt_tokens` quand le provider le rend. Sur 90 jours
de trace, aucune session réelle n'approche les 60k tokens que le critère n°3
anticipe — mais la plus grosse est à 21k sur un plafond de 30k
(`llm_max_input_tokens`), soit 1,4× de marge, pas dix. Ce critère ne s'éprouve
donc **pas** sur le corpus réel — il s'éprouve sur une
entrée **synthétique** dans `eval/stress/synthetic-114k.json` (nommée
`synthetic-60k.json` jusqu'au 2026-09-07 ; 113 928 tokens réels),
clairement étiquetée `_synthetic`, hors du corpus et hors de tout jugement de
qualité, exécutée par le seul spike B (mémoire du `MLXProvider`).

Règle inchangée : tout changement de prompt ou de modèle passe par `eval` avant
d'être activé, et le rapport est joint à la PR.

### Prompt v2 — première itération mesurée (2026-09-06)

Deux consignes ajoutées à `v1`, motivées par le jour 1 du dogfooding
([`../dogfooding.md`](../dogfooding.md)) et par la réserve n°1 de la
[décision Qwen](../decisions/2026-09-06-modele-local-qwen.md) :

1. **`previous_summary`** : l'annexe sert à la continuité, mais `open` se
   réévalue sur les faits de *cette* session — jamais recopié (défaut D1).
2. **Session sans fichier → `central_files: []`**, même si un chemin paraît
   évident ; le second exemple du prompt est désormais un cas à zéro fichier
   (réserve n°1 : Qwen inventait `vite.config.js` sur `6a416635`).

Mesure sur les dix sessions gelées, mêmes réglages qu'à l'étape 3 :

```
                       référence v1 → v2   Qwen local v1 → v2
valides                    9/10 → 10/10        8/10 → 10/10
sessions à fichiers
  dont central_files → 0        aucune              aucune
central_files moyen           4,1 → 4,0           4,1 → 4,1
```

Les deux rejets du garde-fou en v1 (`6a416635`, `2ce34456`, 0 fichier)
passent avec `central_files: []` pour les deux modèles, sans que les sessions
riches en fichiers perdent leurs chemins — pas de frilosité induite. La
consigne n°1 **n'est pas mesurable sur ce corpus** : aucune des dix sessions
gelées ne porte de `previous_summary` (voir `intelligence/TODOS.md`) ; elle se
juge sur le dogfooding, sessions enchaînées d'une même journée.

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
