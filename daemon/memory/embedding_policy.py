from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def embeddings_enabled() -> bool:
    return os.getenv("PULSE_EMBEDDINGS_ENABLED", "").strip().lower() in _TRUE_VALUES


def embeddings_offline_only() -> bool:
    value = os.getenv("PULSE_EMBEDDINGS_OFFLINE_ONLY", "").strip().lower()
    if value in _FALSE_VALUES:
        return False
    return True


def apply_embedding_offline_env() -> None:
    if embeddings_offline_only():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
