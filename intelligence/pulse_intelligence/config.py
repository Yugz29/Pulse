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
    # Couche modèle (spec 2026-09-05-llm-provider v2). Clés à plat : `Config`
    # est un dataclass simple et `load_config` refuse les clés inconnues, donc
    # une table `[llm]` ne se chargerait pas.
    # Vide par défaut : le choix du provider est une décision écrite, au
    # même titre que `model_id` (voir `require_model`). Aucun modèle ne se
    # branche par inadvertance.
    llm_provider: str = ""
    llm_base_url: str = ""
    # 2048 et non 1024 : le passage de référence du corpus (PR 3) a tronqué 3
    # sessions réelles sur 10 à 1024 tokens de complétion — la fence JSON de
    # clôture n'était jamais atteinte, la sortie était rejetée à tort. Un
    # défaut qui échoue 30 % du temps sur du réel n'est pas un défaut.
    llm_max_tokens: int = 2048
    # Plafond de tokens d'ENTRÉE pour le provider local : au-delà, MLX plante
    # en OOM Metal (spike B). Refusé proprement avant le prefill.
    llm_max_input_tokens: int = 30_000
    # Absente = non envoyée. Certains modèles derrière un endpoint compatible
    # refusent le paramètre ; la reproductibilité à 0.0 se demande, elle ne
    # s'impose pas. La négociation du provider reste le filet si un modèle
    # refuse une valeur pourtant configurée.
    llm_temperature: float | None = None

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
    "llm_max_tokens",
    "llm_max_input_tokens",
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
        elif key in _FLOAT_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ConfigError(f"{key} doit être un nombre positif")
            value = float(value)
        elif not isinstance(value, str):
            raise ConfigError(f"{key} doit être une chaîne")
        values[key] = value
    return replace(config, **values)


_FLOAT_FIELDS = {"llm_temperature"}
