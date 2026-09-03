"""Configuration : ~/.pulse_intelligence/config.toml, défauts et validation (spec v2 §9)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path


DEFAULT_CORE_URL = "http://127.0.0.1:8765"


class ConfigError(ValueError):
    """Configuration absente, mal typée ou incomplète."""


def config_home() -> Path:
    override = os.environ.get("PULSE_INTELLIGENCE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".pulse_intelligence"


@dataclass(frozen=True)
class Config:
    core_url: str = DEFAULT_CORE_URL
    model_id: str = ""
    prompt_version: str = "v1"
    tick_minutes: int = 10
    generation_timeout_s: int = 120
    min_session_minutes: int = 10
    min_session_activities: int = 30
    lookback_days: int = 1

    def require_model(self) -> "Config":
        """Le choix du modèle est une décision écrite, jamais un défaut."""
        if not self.model_id.strip():
            raise ConfigError(
                "model_id est vide : renseigne-le dans config.toml "
                "(le service refuse de démarrer sans modèle choisi)"
            )
        return self


_INT_FIELDS = {
    "tick_minutes",
    "generation_timeout_s",
    "min_session_minutes",
    "min_session_activities",
    "lookback_days",
}


def load_config(path: Path | None = None) -> Config:
    """Charge config.toml s'il existe ; les clés inconnues sont des erreurs."""
    selected = path if path is not None else config_home() / "config.toml"
    config = Config()
    if not selected.exists():
        return config
    try:
        raw = tomllib.loads(selected.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"config illisible ({selected}): {exc}") from exc

    known = {field.name for field in fields(Config)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"clés inconnues dans {selected}: {', '.join(unknown)}")

    values = {}
    for key, value in raw.items():
        if key in _INT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{key} doit être un entier positif")
        elif not isinstance(value, str):
            raise ConfigError(f"{key} doit être une chaîne")
        values[key] = value
    return replace(config, **values)
