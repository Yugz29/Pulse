"""Le pont entre le contrat métier et la couche modèle.

`Summarizer` (livré, inchangé) connaît le prompt et le format attendu ;
`LLMProvider` ne transporte que du texte. `ProviderSummarizer` est le seul
point où les deux se rencontrent — un seul, pas un par provider : le prompt
est le même pour tous, et le dupliquer fausserait la comparaison du corpus,
qui suppose qu'une seule variable change à la fois.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .llm.provider import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderInputRefused,
    ProviderUnavailable,
)
from .summarizer import SummarizerError, SummarizerInputRefused, SummarizerUnavailable


PROMPTS_DIR = Path(__file__).parent / "prompts"
DEFAULT_MAX_TOKENS = 1024


def prompt_path_for(prompt_version: str) -> Path:
    """`config.prompt_version` désigne le fichier, sans autre indirection."""
    return PROMPTS_DIR / f"session_summary_{prompt_version}.md"


@dataclass
class ProviderSummarizer:
    """Enveloppe l'entrée sérialisée dans le prompt versionné, appelle le modèle.

    Ne parse rien : `summarize_session` passe la sortie à `parse_model_output`,
    comme avec n'importe quel `Summarizer`.
    """

    provider: LLMProvider
    model_id: str
    prompt_path: Path
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float | None = None
    system: str = field(init=False)

    def __post_init__(self) -> None:
        # Un prompt manquant est une erreur d'installation, pas une panne de
        # modèle : elle doit sortir à la construction, pas au milieu d'un
        # passage sur vingt sessions.
        try:
            self.system = self.prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SummarizerError(
                f"prompt introuvable ou illisible : {self.prompt_path} ({exc})"
            ) from exc
        if not self.system.strip():
            raise SummarizerError(f"prompt vide : {self.prompt_path}")

    def complete(self, model_input: str) -> CompletionResult:
        """Le résultat complet du modèle, métadonnées comprises.

        `summarize_session` n'a besoin que du texte ; `eval` veut aussi les
        tokens, la durée et `dropped_parameters` pour son rapport. Un seul
        chemin d'appel, deux profondeurs de retour.
        """
        request = CompletionRequest(
            system=self.system,
            prompt=model_input,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        try:
            return self.provider.complete(request)
        except ProviderUnavailable as exc:
            raise SummarizerUnavailable(f"{self.provider.name}: {exc}") from exc
        except ProviderInputRefused as exc:
            raise SummarizerInputRefused(f"{self.provider.name}: {exc}") from exc
        except ProviderError as exc:
            # Le résumé de session sait déjà traiter SummarizerError ; il n'a
            # pas à connaître les pannes propres à un runtime d'inférence.
            raise SummarizerError(f"{self.provider.name}: {exc}") from exc

    def summarize(self, model_input: str) -> str:
        return self.complete(model_input).text
