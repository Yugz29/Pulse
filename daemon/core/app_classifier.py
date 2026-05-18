from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from daemon.core.bootstrap_heuristics import (
    BOOTSTRAP_AI_APPS,
    BOOTSTRAP_APP_BUNDLE_ROLES,
    BOOTSTRAP_BROWSER_APPS,
    BOOTSTRAP_DEV_APPS,
    BOOTSTRAP_SELF_APPS,
    BOOTSTRAP_TERMINAL_APPS,
    BOOTSTRAP_WRITING_APPS,
)


AppRole = Literal[
    "dev_tool",
    "ai_assistant",
    "browser",
    "terminal",
    "writing",
    "self_app",
    "unknown",
]
AppRoleSource = Literal[
    "bootstrap_bundle",
    "bootstrap_name",
    "unknown",
]


@dataclass(frozen=True)
class AppClassification:
    app_name: str
    bundle_id: str | None
    role: AppRole
    role_source: AppRoleSource
    confidence: float


def classify_app(
    app_name: str | None,
    *,
    bundle_id: str | None = None,
) -> AppClassification:
    normalized_name = app_name or ""
    normalized_bundle = bundle_id or None

    if normalized_bundle in BOOTSTRAP_APP_BUNDLE_ROLES:
        return AppClassification(
            app_name=normalized_name,
            bundle_id=normalized_bundle,
            role=cast(AppRole, BOOTSTRAP_APP_BUNDLE_ROLES[normalized_bundle]),
            role_source="bootstrap_bundle",
            confidence=0.95,
        )

    role: AppRole = "unknown"
    if normalized_name in BOOTSTRAP_DEV_APPS:
        role = "dev_tool"
    elif normalized_name in BOOTSTRAP_AI_APPS:
        role = "ai_assistant"
    elif normalized_name in BOOTSTRAP_BROWSER_APPS:
        role = "browser"
    elif normalized_name in BOOTSTRAP_TERMINAL_APPS:
        role = "terminal"
    elif normalized_name in BOOTSTRAP_WRITING_APPS:
        role = "writing"
    elif normalized_name in BOOTSTRAP_SELF_APPS:
        role = "self_app"

    if role != "unknown":
        return AppClassification(
            app_name=normalized_name,
            bundle_id=normalized_bundle,
            role=role,
            role_source="bootstrap_name",
            confidence=0.80,
        )

    return AppClassification(
        app_name=normalized_name,
        bundle_id=normalized_bundle,
        role="unknown",
        role_source="unknown",
        confidence=0.0,
    )
