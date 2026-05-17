from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}

HEAVY_LLM_PATHS = {
    "chat",
    "chat_tools",
    "daydream",
    "mcp_translation",
    "debug_resume_card_llm",
    "legacy_journal_repair",
}

LIGHTWEIGHT_LLM_PATHS = {
    "journal_commit_summary",
}


def is_heavy_llm_autowarm_enabled() -> bool:
    return os.getenv("PULSE_HEAVY_LLM_AUTOWARM", "").strip().lower() in _TRUE_VALUES


def is_legacy_journal_repair_enabled() -> bool:
    return os.getenv("PULSE_LEGACY_JOURNAL_REPAIR", "").strip().lower() in _TRUE_VALUES


def classify_llm_path(path: str) -> str:
    normalized = str(path or "").strip()
    if normalized in HEAVY_LLM_PATHS:
        return "ollama_heavy"
    if normalized in LIGHTWEIGHT_LLM_PATHS:
        return "apple_lightweight"
    return "no_llm"
