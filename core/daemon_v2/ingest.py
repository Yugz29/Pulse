"""Validation and normalization for locally observed activity."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis.terminal import (
    is_pasted_prompt_command,
    pasted_prompt_placeholder,
)
from .models import (
    Activity,
    CanonicalEvent,
    IngestedEvent,
    SUPPORTED_ACTIVITY_TYPES,
    SYSTEM_ACTIVITY_TYPES,
    canonical_event_fingerprint,
)


# A secret value may be a quoted span (spaces included) or a bare token.
# Capturing the whole quoted span prevents partial redaction like
# `TOKEN=[REDACTED] bravo charlie"` on `TOKEN="alpha bravo charlie"`.
_SECRET_VALUE = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
# OpenSSL-style non-secret sentinels for -passin/-passout: never redact them.
_PASS_SENTINEL = r"(?:stdin|env:\S+|file:\S+|fd:\d+)(?=\s|$)"
# Shell line continuations hide option/value pairs from single-line patterns
# (`--password \<newline> secret`), so they are folded before matching.
# \r? : a CRLF continuation would otherwise leave the secret unfolded on the
# next line while the lone backslash gets masked — partial redaction.
_LINE_CONTINUATION = re.compile(r"\\\r?\n[ \t]*")

_SENSITIVE_OPTION = re.compile(
    r"(?i)(--?(?:pass(?:word|wd|in|out|phrase)?|token|secret|api[-_]?key|apikey"
    r"|auth[-_]?token|access[-_]?token|private[-_]?key))(?:=|\s+)"
    r"(?!" + _PASS_SENTINEL + r")(" + _SECRET_VALUE + r")"
)
_ENV_SECRET = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|API_KEY|ACCESS_KEY"
    r"|CREDENTIALS)[A-Z0-9_]*)=(" + _SECRET_VALUE + r")"
)
# Credentials embedded in URLs. Greedy up to the LAST @ before the host, so a
# password containing @ is fully masked (user:p@ss@host, not just p).
_URL_USERINFO = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):([^\s/]+)@"
)
# HTTP auth header values, anchored to an explicit header name so that prose
# like "add basic logging" is never touched.
_AUTH_HEADER_VALUE = re.compile(
    r"(?i)\b((?:authorization|x-api-key)\s*:\s*(?:(?:bearer|basic|token)\s+)?)"
    r"(?!(?:bearer|basic|token)\b)[A-Za-z0-9._~+/=-]{6,}"
)
# Bare bearer/basic outside a header: only when the value looks like a token
# (contains a digit or token punctuation), so "basic logging" stays intact.
_BARE_BEARER_TOKEN = re.compile(
    r"(?i)\b((?:bearer|basic)\s+)"
    r"(?=[A-Za-z0-9._~+/=-]*[0-9=+/_-])[A-Za-z0-9._~+/=-]{6,}\b"
)
# -u/--user credentials, anchored to credential-taking commands so that
# `rsync -u host:path`, `docker run -u 1000:1000` or `sudo -u www:x` are
# never rewritten. The whole user:password value is masked.
_USER_COLON_PASSWORD = re.compile(
    r"(?m)((?:^|\s)(?:\S*/)?(?:curl|wget|httpie|http|ftp)\b[^\n]*?"
    r"\s(?:-u|--user)(?:=|\s+))"
    r"(\"[^\"]*:[^\"]*\"|'[^']*:[^']*'|[^:\s]+:\S+)"
)
# MySQL-family glued short option: mysql -psecret (but not bare -p prompt).
# Case-SENSITIVE on purpose: mysql -P3306 is the port, not a password.
# (^|\s) anchor so wrapped invocations (docker exec … mysql -pX) match too.
_DB_SHORT_PASSWORD = re.compile(
    r"(?m)((?:^|\s)(?:\S*/)?(?:mysql|mysqladmin|mysqldump|mariadb)\b[^\n]*?\s-p)"
    r"([^\s-]\S*)"
)
# sshpass positional password
_SSHPASS_PASSWORD = re.compile(
    r"(?m)((?:^|\s)sshpass\s+-p\s*)(" + _SECRET_VALUE + r")"
)
# AWS CLI credential writes, anchored to `aws … configure set` so that e.g.
# `grep aws_secret_access_key ~/.aws/credentials` keeps its filename.
_AWS_POSITIONAL = re.compile(
    r"(?i)\b(aws\b[^\n]*?\bconfigure\s+set\s+"
    r"aws_(?:secret_access_key|session_token|access_key_id)\s+)(\S+)"
)
# Well-known credential prefixes, wherever they appear
_KNOWN_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}"
    r"|glpat-[A-Za-z0-9_-]{20,})\b"
)
# Identité stable d'une session de travail (Core 0.5.0) : sha256 tronqué à
# 16 hex des event_id sources. Un résumé ne s'attache jamais à un ordinal.
_SESSION_IDENTITY = re.compile(r"[0-9a-f]{16}")
_IGNORED_TERMINAL_COMMANDS = {
    "clear",
    "source ~/.zshrc",
}


class InvalidActivity(ValueError):
    """Raised when an activity payload cannot be normalized."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class IgnoredActivity(ValueError):
    """Raised when a valid but intentionally noisy activity should not be stored."""


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidActivity(
            f"{key} must be a non-empty string",
            field=key,
        )
    return value.strip()


def _parse_occurred_at(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str):
        raise InvalidActivity(
            "occurred_at must be an ISO 8601 string",
            field="occurred_at",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidActivity(
            "occurred_at must be a valid ISO 8601 string",
            field="occurred_at",
        ) from exc
    if parsed.tzinfo is None:
        raise InvalidActivity(
            "occurred_at must include a timezone",
            field="occurred_at",
        )
    return parsed


def _copy_persisted_context(
    payload: dict[str, Any],
    details: dict[str, Any],
) -> None:
    """Preserve producer-resolved context without recalculating it in Core."""
    workspace = payload.get("workspace")
    if isinstance(workspace, str) and workspace.strip():
        details["workspace"] = workspace
    elif isinstance(workspace, dict):
        details["workspace"] = dict(workspace)

    git = payload.get("git")
    if isinstance(git, dict):
        details["git"] = dict(git)
    git_root = payload.get("git_root")
    if isinstance(git_root, str) and git_root.strip():
        details["git_root"] = git_root.strip()


def command_has_secret(command: str) -> bool:
    """True si la rédaction masquerait une valeur.

    Le simple repli des continuations ``\\``+retour-ligne est une
    normalisation, pas un secret : un texte historique qui ne diffère que
    par ce repli est propre. Source de vérité unique pour l'audit.
    """
    return redact_command(command) != _LINE_CONTINUATION.sub(" ", command)


def redact_command(command: str) -> str:
    # Folding backslash-newline continuations is a deliberate normalization:
    # the stored command loses its continuation layout, but a secret split
    # across continued lines can no longer escape the patterns below.
    redacted = _LINE_CONTINUATION.sub(" ", command)
    redacted = _KNOWN_TOKEN.sub("[REDACTED]", redacted)
    redacted = _URL_USERINFO.sub(r"\1:[REDACTED]@", redacted)
    redacted = _AUTH_HEADER_VALUE.sub(r"\1[REDACTED]", redacted)
    redacted = _BARE_BEARER_TOKEN.sub(r"\1[REDACTED]", redacted)
    redacted = _USER_COLON_PASSWORD.sub(r"\1[REDACTED]", redacted)
    redacted = _DB_SHORT_PASSWORD.sub(r"\1[REDACTED]", redacted)
    redacted = _SSHPASS_PASSWORD.sub(r"\1[REDACTED]", redacted)
    redacted = _AWS_POSITIONAL.sub(r"\1[REDACTED]", redacted)
    redacted = _SENSITIVE_OPTION.sub(r"\1=[REDACTED]", redacted)
    return _ENV_SECRET.sub(r"\1=[REDACTED]", redacted)


# Exact /activities path (never /activities/123 or /activities-export) and
# only on Pulse's own ports: the configured one, the 8765 default, and the
# historical 5000 — a dev testing their own localhost:3000/activities API
# must keep that command in their trace.
_INTERNAL_PULSE_CURL_URL = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost):(\d+)/activities(?=$|[\s\"'?])"
)


def _pulse_ports() -> set[int]:
    from .runtime_config import DEFAULT_CORE_PORT, core_port

    ports = {5000, DEFAULT_CORE_PORT}
    try:
        ports.add(core_port())
    except ValueError:
        pass
    return ports


def _is_internal_pulse_curl(command: str) -> bool:
    if not command.startswith("curl "):
        return False
    match = _INTERNAL_PULSE_CURL_URL.search(command)
    return match is not None and int(match.group(1)) in _pulse_ports()


def filter_terminal_command(command: str) -> str | None:
    useful_lines = []
    ignoring_internal_curl = False
    for line in command.splitlines():
        stripped_line = line.strip()
        normalized_line = " ".join(stripped_line.split())
        if ignoring_internal_curl:
            continue
        if _is_internal_pulse_curl(normalized_line):
            # Remaining lines may be curl options or a multiline JSON body.
            ignoring_internal_curl = True
            continue
        if normalized_line and normalized_line not in _IGNORED_TERMINAL_COMMANDS:
            useful_lines.append(stripped_line)
    return "\n".join(useful_lines) or None


def normalize_activity(payload: Any) -> Activity:
    """Normalize a historical flat activity payload.

    Kept as the compatibility-facing semantic normalizer. Canonical ingestion
    uses :func:`normalize_event`, which passes only the canonical ``details``
    object into this function.
    """
    if not isinstance(payload, dict):
        raise InvalidActivity(
            "request body must be a JSON object",
            field="request",
        )

    activity_type = _required_string(payload, "type")
    if activity_type not in SUPPORTED_ACTIVITY_TYPES:
        raise InvalidActivity(
            f"type must be one of: {', '.join(sorted(SUPPORTED_ACTIVITY_TYPES))}",
            field="type",
        )

    terminal_command = None
    if activity_type == "terminal_finished":
        raw_command = payload.get("command")
        if not isinstance(raw_command, str):
            raise InvalidActivity(
                "command must be a non-empty string",
                field="details.command",
            )
        terminal_command = filter_terminal_command(raw_command)
        if terminal_command is None:
            raise IgnoredActivity("terminal command is intentionally ignored")

    occurred_at = _parse_occurred_at(payload.get("occurred_at"))
    details: dict[str, Any]

    if activity_type == "file_changed":
        path = _required_string(payload, "path")
        event = payload.get("event", payload.get("change", "modified"))
        if event not in {"created", "modified", "deleted"}:
            raise InvalidActivity(
                "event must be created, modified, or deleted",
                field="details.event",
            )
        normalized_path = str(Path(path).expanduser().absolute())
        details = {"path": normalized_path, "event": event}
        _copy_persisted_context(payload, details)
        if isinstance(details.get("workspace"), str):
            details["workspace"] = str(
                Path(details["workspace"]).expanduser().absolute()
            )
        source = "filesystem"
        summary = f"{event.capitalize()} {normalized_path}"
    elif activity_type == "terminal_finished":
        assert terminal_command is not None
        command = redact_command(terminal_command)
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise InvalidActivity(
                "exit_code must be an integer",
                field="details.exit_code",
            )
        # Storage policy (decided 2026-08-30): a prompt-shaped paste is never
        # rendered, so only its occurrence is kept, not its text. Gated on a
        # failed exit so a successful prompt-shaped command (e.g. a heredoc)
        # keeps its full text — a real mis-paste at the shell prompt fails.
        if exit_code != 0 and is_pasted_prompt_command(command):
            command = pasted_prompt_placeholder(command)
        cwd = _required_string(payload, "cwd")
        details = {"command": command, "exit_code": exit_code, "cwd": str(Path(cwd).expanduser())}
        for key in ("started_at", "finished_at"):
            if key in payload:
                details[key] = _parse_occurred_at(payload[key]).isoformat()
        _copy_persisted_context(payload, details)
        source = "terminal"
        status = "succeeded" if exit_code == 0 else f"failed ({exit_code})"
        summary = f"Command {status}: {command}"
    elif activity_type == "git_commit":
        commit_hash = _required_string(payload, "commit_hash")
        repository = _required_string(payload, "repository")
        git_root = _required_string(payload, "git_root")
        branch = _required_string(payload, "branch")
        # Commit messages carry the same secret shapes as commands
        # ("rotate key: old was AKIA…") and end up in summary + renderings.
        message = redact_command(_required_string(payload, "message"))
        details = {
            "commit_hash": commit_hash,
            "repository": repository,
            "git_root": str(Path(git_root).expanduser()),
            "branch": branch,
            "message": message,
        }
        for key in ("files_changed", "insertions", "deletions"):
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidActivity(
                    f"{key} must be a non-negative integer when provided",
                    field=f"details.{key}",
                )
            details[key] = value
        source = "git"
        first_line = message.splitlines()[0]
        summary = f"Commit {commit_hash[:7]} on {branch}: {first_line}"
    elif activity_type == "agent_session":
        # Dérivé d'un transcript d'agent (décision rétention 2026-08-30) :
        # seul le résumé versionné entre en base, jamais le brut.
        source_tool = _required_string(payload, "source_tool")
        session_id = _required_string(payload, "session_id")
        transcript_path = _required_string(payload, "transcript_path")
        summary_version = payload.get("summary_version")
        if (
            isinstance(summary_version, bool)
            or not isinstance(summary_version, int)
            or summary_version < 1
        ):
            raise InvalidActivity(
                "summary_version must be a positive integer",
                field="details.summary_version",
            )
        details = {
            "source_tool": source_tool,
            "session_id": session_id,
            "transcript_path": transcript_path,
            "summary_version": summary_version,
        }
        for key in ("started_at", "ended_at"):
            if key in payload:
                details[key] = _parse_occurred_at(payload[key]).isoformat()
        for key in ("user_messages", "assistant_messages"):
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidActivity(
                    f"{key} must be a non-negative integer when provided",
                    field=f"details.{key}",
                )
            details[key] = value
        for key in ("archive_hint", "git_branch", "tool_version"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                details[key] = value.strip()
        first_prompt = payload.get("first_prompt")
        if isinstance(first_prompt, str) and first_prompt.strip():
            # Défense en profondeur : le producteur rédige déjà, l'ingestion
            # re-rédige comme pour les commandes et messages de commit.
            details["first_prompt"] = redact_command(first_prompt.strip())
        _copy_persisted_context(payload, details)
        source = "agent"
        headline = details.get("first_prompt")
        summary = (
            f"Agent session ({source_tool}): {headline}"
            if headline
            else f"Agent session ({source_tool})"
        )
    elif activity_type == "session_summary":
        # Résumé de session produit par la couche Intelligence (spec du
        # 2026-09-03, §6). Core valide le contrat de données minimal et passe
        # le reste tel quel : il ne connaît ni le modèle ni le prompt.
        session_id = _required_string(payload, "session_id")
        if not _SESSION_IDENTITY.fullmatch(session_id):
            raise InvalidActivity(
                "session_id must be the 16-hex stable session identity",
                field="details.session_id",
            )
        source_hash = _required_string(payload, "source_event_ids_hash")
        if source_hash != session_id:
            raise InvalidActivity(
                "source_event_ids_hash must equal session_id",
                field="details.source_event_ids_hash",
            )
        session_label = payload.get("session_label")
        if session_label is not None and (
            not isinstance(session_label, str) or not session_label.strip()
        ):
            raise InvalidActivity(
                "session_label must be a non-empty string when provided",
                field="details.session_label",
            )
        prompt_version = _required_string(payload, "prompt_version")
        model_id = _required_string(payload, "model_id")
        reprise = payload.get("reprise")
        if not isinstance(reprise, dict):
            raise InvalidActivity(
                "reprise must be an object",
                field="details.reprise",
            )
        normalized_reprise = {}
        for key in ("doing", "stopped_at", "open"):
            value = reprise.get(key)
            if not isinstance(value, str) or not value.strip():
                raise InvalidActivity(
                    f"reprise.{key} must be a non-empty string",
                    field=f"details.reprise.{key}",
                )
            # Défense en profondeur, comme first_prompt et les messages de
            # commit : un texte libre n'entre jamais en base sans rédaction.
            normalized_reprise[key] = redact_command(value.strip())
        structured = payload.get("structured")
        if not isinstance(structured, dict):
            raise InvalidActivity(
                "structured must be an object",
                field="details.structured",
            )
        project = structured.get("project")
        if project is not None and not isinstance(project, str):
            raise InvalidActivity(
                "structured.project must be a string or null",
                field="details.structured.project",
            )
        if structured.get("confidence") not in {"high", "medium", "low"}:
            raise InvalidActivity(
                "structured.confidence must be high, medium or low",
                field="details.structured.confidence",
            )
        details = {
            key: value
            for key, value in payload.items()
            if key not in {"type", "occurred_at", "timestamp", "workspace", "git", "git_root"}
        }
        details.update(
            {
                "session_id": session_id,
                "source_event_ids_hash": source_hash,
                "prompt_version": prompt_version,
                "model_id": model_id,
                "reprise": {**reprise, **normalized_reprise},
                "structured": dict(structured),
            }
        )
        _copy_persisted_context(payload, details)
        source = "intelligence"
        summary = normalized_reprise["doing"].splitlines()[0]
    elif activity_type == "app_activated":
        app = _required_string(payload, "app")
        details = {"app": app}
        bundle_id = payload.get("bundle_id")
        if isinstance(bundle_id, str) and bundle_id.strip():
            details["bundle_id"] = bundle_id.strip()
        if "title" in payload:
            details["title"] = _required_string(payload, "title")
        source = "application"
        summary = f"Activated {app}"
    else:
        assert activity_type in SYSTEM_ACTIVITY_TYPES
        details = {}
        source = "system"
        summary = activity_type

    return Activity(
        activity_type=activity_type,
        occurred_at=occurred_at,
        source=source,
        summary=summary,
        details=details,
    )


_CANONICAL_MARKERS = {"event_id", "schema_version", "producer", "details"}
_LEGACY_PRODUCER = "pulse-legacy"


def normalize_event(payload: Any) -> IngestedEvent:
    """Validate canonical input or explicitly adapt a legacy flat payload."""
    if not isinstance(payload, dict):
        raise InvalidActivity(
            "request body must be a JSON object",
            field="request",
        )
    if _CANONICAL_MARKERS.intersection(payload):
        return _normalize_canonical_event(payload)
    return adapt_legacy_payload(payload)


def _normalize_canonical_event(payload: dict[str, Any]) -> IngestedEvent:
    event_id = _canonical_required_string(payload, "event_id")

    schema_version = payload.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version <= 0
    ):
        raise InvalidActivity(
            "schema_version must be a strictly positive integer",
            field="schema_version",
        )

    event_type = _canonical_required_string(payload, "type")
    producer = payload.get("producer")
    if not isinstance(producer, dict):
        raise InvalidActivity(
            "producer must be an object",
            field="producer",
        )
    producer_name = _canonical_required_string(producer, "name", prefix="producer")
    producer_version = _canonical_optional_string(
        producer,
        "version",
        prefix="producer",
    )
    producer_instance_id = _canonical_optional_string(
        producer,
        "instance_id",
        prefix="producer",
    )

    if "occurred_at" not in payload:
        raise InvalidActivity(
            "occurred_at is required",
            field="occurred_at",
        )
    occurred_at = _parse_occurred_at(payload["occurred_at"])

    details = payload.get("details")
    if not isinstance(details, dict):
        raise InvalidActivity(
            "details must be a JSON object",
            field="details",
        )

    event = CanonicalEvent(
        event_id=event_id,
        schema_version=schema_version,
        event_type=event_type,
        producer_name=producer_name,
        producer_version=producer_version,
        producer_instance_id=producer_instance_id,
        occurred_at=occurred_at,
        details=dict(details),
    )
    activity = _activity_from_event(event)
    return IngestedEvent(
        event=event,
        activity=activity,
        fingerprint=_validated_event_fingerprint(event),
    )


def adapt_legacy_payload(payload: dict[str, Any]) -> IngestedEvent:
    """Temporary adapter for the existing flat Core producers.

    A fresh server-side event_id is generated for every request. Consequently,
    two identical legacy requests are intentionally *not* idempotent. This
    adapter is isolated so it can be removed once all producers send the
    versioned contract.
    """
    event_type = _required_string(payload, "type")
    raw_occurred_at = payload.get("timestamp", payload.get("occurred_at"))
    occurred_at = _parse_occurred_at(raw_occurred_at)
    legacy_details = {
        key: value
        for key, value in payload.items()
        if key not in {"type", "timestamp", "occurred_at"}
    }
    event = CanonicalEvent(
        event_id=str(uuid.uuid4()),
        schema_version=1,
        event_type=event_type,
        producer_name=_LEGACY_PRODUCER,
        producer_version=None,
        producer_instance_id=None,
        occurred_at=occurred_at,
        details=legacy_details,
    )
    activity = _activity_from_event(event)
    return IngestedEvent(
        event=event,
        activity=activity,
        fingerprint=_validated_event_fingerprint(event),
        legacy=True,
    )


def _activity_from_event(event: CanonicalEvent) -> Activity:
    flat_payload = {
        "type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        **event.details,
    }
    return normalize_activity(flat_payload)


def _canonical_required_string(
    payload: dict[str, Any],
    key: str,
    *,
    prefix: str | None = None,
) -> str:
    field = f"{prefix}.{key}" if prefix else key
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidActivity(
            f"{field} must be a non-empty string",
            field=field,
        )
    return value.strip()


def _canonical_optional_string(
    payload: dict[str, Any],
    key: str,
    *,
    prefix: str,
) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        field = f"{prefix}.{key}"
        raise InvalidActivity(
            f"{field} must be a string when provided",
            field=field,
        )
    return value


def _validated_event_fingerprint(event: CanonicalEvent) -> str:
    try:
        return canonical_event_fingerprint(event)
    except (TypeError, ValueError) as exc:
        raise InvalidActivity(
            "details must contain strictly valid JSON values",
            field="details",
        ) from exc
