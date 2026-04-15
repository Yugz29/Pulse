class UnavailableLLMRouter:
    """
    Routeur de secours sans dépendance externe.

    Permet d'importer le daemon et d'exécuter les tests non-LLM même si
    la pile LLM est absente ou cassée dans l'environnement courant.
    """

    def __init__(self, reason: str = ""):
        self.reason = str(reason).strip()
        self.default = None
        self._model = ""

    def complete(self, *args, **kwargs) -> str:
        message = "LLM unavailable"
        if self.reason:
            message = f"{message}: {self.reason}"
        raise RuntimeError(message)

    def list_models(self) -> list:
        return []

    def get_model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model
