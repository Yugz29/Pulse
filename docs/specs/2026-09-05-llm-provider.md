# Spec — LLMProvider et contrat de sortie du résumé de session

Date : 2026-09-05
Chantier : pas 3 de la roadmap V3 (première boucle IA, résumé de session)
Emplacement cible : `docs/specs/2026-09-05-llm-provider.md`
Statut : validée, à implémenter

## 1. Objectif

Rendre le paquet `intelligence/` indépendant du modèle et du runtime d'inférence.
Le résumé de session (spec `2026-09-03-session-summary.md` v2) consomme une
interface `LLMProvider` ; le modèle derrière est un détail de configuration,
interchangeable sans toucher au code du résumé.

Conséquence voulue : le choix du modèle local devient une décision réversible.
On code avec un faux modèle et un endpoint distant compatible OpenAI, on
branche le modèle local ensuite, on le remplace si le corpus de 10 sessions
montre qu'il déçoit.

## 2. Décisions

- Un seul modèle local en mémoire à la fois. Pas de Model Router.
- Modèle local retenu pour démarrer : **Qwen3.8-27B, MLX 4-bit**, thinking désactivé.
- Trois implémentations livrées dans cet ordre : `FakeProvider`,
  `OpenAICompatibleProvider`, `MLXProvider`.
- Le contrat de sortie (format du résumé) vit côté Pulse, jamais dans des
  astuces propres à un modèle. Toute sortie non conforme est rejetée, pas réparée.
- Pas de dépendance à Ollama. `mlx-lm` est importé directement dans la venv
  `intelligence/`.

## 3. Interface

```python
# intelligence/llm/provider.py
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    prompt: str
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    provider: str          # "fake" | "openai-compatible" | "mlx"
    model: str             # identifiant exact du modèle utilisé
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int


class LLMProvider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...
    def healthcheck(self) -> bool: ...
```

Règles :

- `complete` est synchrone et bloquant. Le pas 3 est un CLI batch ; pas
  d'async tant qu'aucun service résident n'existe.
- `complete` lève `ProviderError` (exception dédiée) sur toute erreur réseau,
  chargement ou timeout. Le résumé de session décide quoi faire, pas le provider.
- Aucune logique métier dans les providers : pas de parsing du résumé, pas de
  retry sur contenu. Ils transportent du texte.
- `temperature=0.0` par défaut : on veut un résumé reproductible.

## 4. Implémentations

### 4.1 FakeProvider

- Retourne une sortie fixée, conforme au schéma de la section 5, construite
  à partir de quelques champs du prompt (ex. l'identifiant de session) pour
  que les tests vérifient que le bon contexte a été transmis.
- Option `fail_with: ProviderError | None` pour tester les chemins d'erreur.
- Option `invalid_output: bool` pour tester le rejet d'une sortie non conforme.
- Aucune dépendance.

### 4.2 OpenAICompatibleProvider

- Appel HTTP vers n'importe quel endpoint compatible OpenAI
  (`/v1/chat/completions`) : gateway distante, LM Studio, Ollama, etc.
  Base URL, clé et nom de modèle lus depuis l'environnement
  (`PULSE_LLM_BASE_URL`, `PULSE_LLM_API_KEY`, `PULSE_LLM_MODEL`).
  Jamais en dur, jamais dans le repo.
- Timeout explicite (défaut 120 s).
- Usage prévu : brancher un modèle distant de bonne qualité comme
  **référence** pour comparer le modèle local sur le corpus, ou dépanner
  quand le local n'est pas disponible. Ce n'est pas le provider de
  production de Pulse.

### 4.3 MLXProvider

- Dépendance : `mlx-lm` (épinglée dans `intelligence/requirements.txt`).
- Modèle par défaut : la conversion MLX 4-bit de Qwen3.8-27B publiée sur
  Hugging Face (identifiant exact à figer dans la config au moment de
  l'installation, après vérification qu'elle existe).
- Chargement paresseux au premier `complete`, puis modèle gardé en mémoire
  pour la durée du process. Pas de rechargement entre deux sessions d'un
  même batch.
- Thinking désactivé via le template de chat du modèle (`enable_thinking=False`
  ou équivalent selon la version de `mlx-lm`). À vérifier en test : la sortie
  ne doit contenir aucun bloc de réflexion.
- `max_tokens` transmis tel quel. Température 0.

## 5. Contrat de sortie du résumé

Le provider retourne du texte ; le résumé de session exige que ce texte soit
un objet JSON unique respectant ce schéma (version 1) :

```json
{
  "schema_version": 1,
  "session_id": "<hash fourni dans le prompt, recopié tel quel>",
  "one_liner": "Une phrase, ce qui a été fait.",
  "done": ["fait 1", "fait 2"],
  "open": ["point resté ouvert 1"],
  "next": ["prochaine action suggérée 1"],
  "files_touched": ["chemin/relatif/1", "chemin/relatif/2"],
  "confidence": "high | medium | low"
}
```

Règles de validation (dans `intelligence/summary/validate.py`, pas dans les providers) :

- Extraction : on accepte le JSON nu ou entouré de ``` ; tout autre texte
  autour est une non-conformité.
- `session_id` doit être strictement égal à celui du prompt. Un modèle qui
  invente ou modifie l'identifiant est rejeté.
- `files_touched` doit être un sous-ensemble des chemins présents dans le
  contexte fourni. Un chemin absent du contexte est une hallucination :
  rejet. C'est le garde-fou direct contre les assertions invérifiables.
- Listes : maximum 10 entrées chacune, chaînes non vides.
- Une sortie rejetée n'est jamais stockée. Le CLI enregistre l'échec
  (provider, modèle, raison) et passe à la session suivante.
- Pas de retry automatique en v1. Une seconde tentative est une décision
  humaine.

Le prompt de résumé est un fichier versionné (`intelligence/summary/prompt.md`),
identique pour tous les providers. Il est gelé pendant la comparaison sur le
corpus.

## 6. Configuration

`intelligence/config.toml` (ou variables d'environnement équivalentes) :

```toml
[llm]
provider = "mlx"          # fake | openai-compatible | mlx
max_tokens = 1024

[llm.mlx]
model = "<id Hugging Face de la conversion MLX 4-bit de Qwen3.8-27B>"

[llm.openai-compatible]
timeout_s = 120
```

Une seule ligne à changer pour basculer de provider ou de modèle.

## 7. Tests

- Unitaires, sans réseau ni modèle : `FakeProvider` sur les chemins nominal,
  erreur et sortie invalide ; validation du contrat sur des cas conformes,
  JSON malformé, `session_id` altéré, chemin inventé.
- Intégration, marquée `slow`, désactivée par défaut : `MLXProvider` charge le
  modèle, résume une session du corpus, la sortie passe la validation et ne
  contient pas de bloc de réflexion.
- Corpus : le CLI batch accepte `--provider` et écrit ses sorties dans
  `intelligence/bench/out/<provider>-<modèle>/<session_id>.json` avec un
  `meta.json` (durée, tokens, pic mémoire via `resource`). La comparaison
  local vs référence distante se fait à la main sur ces fichiers.

## 8. Hors périmètre

- Model Router, plusieurs modèles simultanés.
- Service résident, API HTTP d'Intelligence (port 8767 réservé, non utilisé ici).
- Streaming.
- Toute intégration spécifique à un runtime (Ollama, LM Studio) au-delà de
  leur endpoint compatible OpenAI.
- Réparation automatique d'une sortie non conforme.

## 9. Critères d'acceptation

1. Le pas 3 s'exécute de bout en bout avec `provider = "fake"` sans réseau.
2. Le même code s'exécute avec `provider = "openai-compatible"` sur un
   endpoint distant et produit des résumés valides sur les 10 sessions du corpus.
3. `provider = "mlx"` tient en mémoire sur le M3 Max 36 Go avec une session
   de 60k tokens (vérifié au calculateur apxml avant téléchargement, puis mesuré).
4. Aucun résumé stocké ne contient de chemin absent du contexte source.
5. Changer de modèle = changer une ligne de config, zéro modification de code.
