"""Producteur agent_session : un événement dérivé par session d'agent terminée.

Décision de rétention du 2026-08-30 : le brut des transcripts (Claude Code,
Codex) n'entre JAMAIS dans trace.db. Ce producteur en dérive un résumé
déterministe — calculé UNE SEULE FOIS par session, versionné
(``SUMMARY_VERSION``), jamais recalculé : la stabilité temporelle du journal
prime sur la fraîcheur du résumé. Une session déjà émise qui grossit ensuite
(reprise tardive) est signalée mais pas ré-émise.

Le payload canonique part dans l'outbox durable via ``enqueue_json_input``
(même chemin que l'observateur Swift) : validation d'ingestion incluse,
daemon indisponible sans perte. ``event_id`` est déterministe (uuid5 par
session) : une ré-émission accidentelle est un duplicate, pas un doublon.

Une session n'est émise que STABLE : dernier mtime plus vieux que la fenêtre
de silence (``--quiet-minutes``, défaut 60) — un transcript encore en cours
d'écriture attend le prochain passage.

Usage :
    python -m daemon_v2.agent_sessions [--dry-run] [--quiet-minutes N]
        [--transcript PATH]   # mode ciblé (hook SessionEnd), fenêtre contournée

Codes de sortie : 0 = passage terminé ; 2 = erreur d'infrastructure
(manifeste corrompu, outbox inécrivable).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ingest import redact_command
from .producer_outbox import ProducerOutbox, enqueue_json_input


SUMMARY_VERSION = 2
PRODUCER_NAME = "pulse-agent-sessions"
PRODUCER_VERSION = "1.0"
DEFAULT_QUIET = timedelta(minutes=60)
FIRST_PROMPT_LIMIT = 280

DEFAULT_CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_DIR = Path.home() / ".codex" / "sessions"

# Enveloppes d'outillage dans les prompts Claude Code (slash commands,
# sorties locales) : pas le premier prompt humain de la session.
_WRAPPED_PROMPT_PREFIXES = ("<command-message>", "<local-command", "<bash-input>")


class AgentSessionInfrastructureError(RuntimeError):
    """Le manifeste ou l'outbox n'ont pas pu être utilisés."""


@dataclass(frozen=True)
class AgentSessionSummary:
    source_tool: str
    session_id: str
    started_at: datetime
    ended_at: datetime
    user_messages: int
    assistant_messages: int
    cwd: str | None = None
    git_branch: str | None = None
    tool_version: str | None = None
    first_prompt: str | None = None
    sidechain: bool = False


@dataclass
class EmitReport:
    emitted: int = 0
    already_emitted: int = 0
    still_active: int = 0
    grown_after_emit: int = 0
    unparseable: int = 0
    duplicate_sessions: int = 0
    sidechain_skipped: int = 0


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text_from_content(content: Any) -> str | None:
    """Premier texte lisible d'un champ ``message.content`` (str ou blocs)."""
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"text", "input_text"}:
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    return None


def _clip_prompt(text: str) -> str:
    redacted = redact_command(" ".join(text.split()))
    if len(redacted) <= FIRST_PROMPT_LIMIT:
        return redacted
    return f"{redacted[: FIRST_PROMPT_LIMIT - 1].rstrip()}…"


def parse_claude_session(
    lines: list[str], fallback_session_id: str
) -> AgentSessionSummary | None:
    session_id = fallback_session_id
    cwd = git_branch = tool_version = first_prompt = None
    started = ended = None
    user_messages = assistant_messages = 0
    saw_sidechain = saw_mainline = False

    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind") or entry.get("type")
        if kind not in {"user", "assistant"}:
            continue
        moment = _parse_timestamp(entry.get("timestamp"))
        if moment is not None:
            started = moment if started is None else min(started, moment)
            ended = moment if ended is None else max(ended, moment)
        if entry.get("isSidechain") is True:
            saw_sidechain = True
        else:
            saw_mainline = True
        raw_session = entry.get("sessionId")
        if isinstance(raw_session, str) and raw_session:
            session_id = raw_session
        if cwd is None and isinstance(entry.get("cwd"), str) and entry["cwd"]:
            cwd = entry["cwd"]
        if (
            git_branch is None
            and isinstance(entry.get("gitBranch"), str)
            and entry["gitBranch"]
        ):
            git_branch = entry["gitBranch"]
        if (
            tool_version is None
            and isinstance(entry.get("version"), str)
            and entry["version"]
        ):
            tool_version = entry["version"]

        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        text = _text_from_content(content)
        if kind == "assistant":
            assistant_messages += 1
            continue
        # Une ligne "user" peut être un tool_result renvoyé au modèle : seul
        # un texte lisible d'un utilisateur externe compte comme message.
        if entry.get("userType") == "external" and text is not None:
            user_messages += 1
            if first_prompt is None and not text.lstrip().startswith(
                _WRAPPED_PROMPT_PREFIXES
            ):
                first_prompt = _clip_prompt(text)

    if started is None or ended is None:
        return None
    return AgentSessionSummary(
        source_tool="claude-code",
        # Transcript de sous-agent (Task/revue) : toutes les lignes portent
        # isSidechain — pas une session de travail de l'utilisateur.
        sidechain=saw_sidechain and not saw_mainline,
        session_id=session_id,
        started_at=started,
        ended_at=ended,
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        cwd=cwd,
        git_branch=git_branch,
        tool_version=tool_version,
        first_prompt=first_prompt,
    )


def parse_codex_session(
    lines: list[str], fallback_session_id: str
) -> AgentSessionSummary | None:
    session_id = fallback_session_id
    cwd = first_prompt = None
    started = ended = None
    user_messages = assistant_messages = 0

    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        moment = _parse_timestamp(entry.get("timestamp"))
        if moment is not None:
            started = moment if started is None else min(started, moment)
            ended = moment if ended is None else max(ended, moment)
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if entry.get("type") == "session_meta":
            raw_session = payload.get("id") or payload.get("session_id")
            if isinstance(raw_session, str) and raw_session:
                session_id = raw_session
            if isinstance(payload.get("cwd"), str) and payload["cwd"]:
                cwd = payload["cwd"]
            continue
        if entry.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        text = _text_from_content(payload.get("content"))
        if role == "assistant":
            assistant_messages += 1
        elif role == "user" and text is not None:
            user_messages += 1
            if first_prompt is None:
                first_prompt = _clip_prompt(text)

    if started is None or ended is None:
        return None
    return AgentSessionSummary(
        source_tool="codex",
        session_id=session_id,
        started_at=started,
        ended_at=ended,
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        cwd=cwd,
        first_prompt=first_prompt,
    )


_PARSERS = {
    "claude-code": parse_claude_session,
    "codex": parse_codex_session,
}


def session_event_id(source_tool: str, session_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"pulse-agent-session:{source_tool}:{session_id}")
    )


def build_agent_session_payload(
    outbox: ProducerOutbox,
    summary: AgentSessionSummary,
    *,
    transcript_path: str,
) -> str:
    details: dict[str, Any] = {
        "source_tool": summary.source_tool,
        "session_id": summary.session_id,
        "transcript_path": transcript_path,
        "summary_version": SUMMARY_VERSION,
        "started_at": summary.started_at.isoformat(),
        "ended_at": summary.ended_at.isoformat(),
        "user_messages": summary.user_messages,
        "assistant_messages": summary.assistant_messages,
    }
    if summary.first_prompt:
        details["first_prompt"] = summary.first_prompt
    if summary.git_branch:
        details["git_branch"] = summary.git_branch
    if summary.tool_version:
        details["tool_version"] = summary.tool_version
    if summary.cwd:
        # Le résolveur 5A lit "workspace" : la session s'attribue au projet.
        details["workspace"] = summary.cwd
    payload = {
        "event_id": session_event_id(summary.source_tool, summary.session_id),
        "schema_version": 1,
        "type": "agent_session",
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
            "instance_id": outbox.producer_instance_id(),
        },
        "occurred_at": summary.started_at.isoformat(),
        "details": details,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def default_manifest_path() -> Path:
    configured = os.environ.get("PULSE_AGENT_SESSIONS_MANIFEST_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".pulse_v2" / "agent_sessions_manifest.json"


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        emitted = loaded["emitted"]
        if not isinstance(emitted, dict):
            raise TypeError("emitted must be an object")
        return emitted
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Sans manifeste fiable, une ré-émission d'une session qui a grossi
        # produirait des conflits 409 en série : on s'arrête.
        raise AgentSessionInfrastructureError(
            f"unreadable manifest: {path} ({exc})"
        ) from exc


def _write_manifest(path: Path, emitted: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"emitted": emitted}, sort_keys=True, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def emit_agent_sessions(
    *,
    claude_dir: Path = DEFAULT_CLAUDE_DIR,
    codex_dir: Path = DEFAULT_CODEX_DIR,
    outbox: ProducerOutbox | None = None,
    manifest_path: Path | None = None,
    quiet: timedelta = DEFAULT_QUIET,
    dry_run: bool = False,
    now: datetime | None = None,
    transcript: Path | None = None,
) -> EmitReport:
    """Emit derived events; ``transcript`` switches to targeted mode.

    Mode ciblé (hook SessionEnd, décision (a) du 2026-08-31) : seul CE
    transcript est traité et la fenêtre de silence est contournée — la
    session vient de se terminer, c'est le hook qui le dit. Toutes les
    autres règles (déjà émis, sidechain, doublon de session, résumé figé)
    restent identiques au passage périodique.
    """
    moment = now or datetime.now(timezone.utc)
    manifest_file = manifest_path or default_manifest_path()
    emitted = _load_manifest(manifest_file)
    report = EmitReport()
    resolved_outbox = outbox
    manifest_dirty = False
    # Des transcripts distincts peuvent porter le même sessionId interne
    # (session reprise/forkée : Claude Code copie les lignes d'origine).
    # Le premier fichier émis porte l'identité ; les suivants sont des
    # doublons de session — le résumé est calculé une fois (décision
    # 2026-08-30), donc la première émission prime.
    emitted_event_ids = {
        str(entry.get("event_id"))
        for entry in emitted.values()
        if entry.get("event_id")
    }

    sources = (("claude-code", claude_dir), ("codex", codex_dir))
    if transcript is None:
        selected: list[tuple[str, list[Path]]] = []
        for source_tool, directory in sources:
            directory = directory.expanduser()
            if directory.is_dir():
                selected.append((source_tool, sorted(directory.rglob("*.jsonl"))))
    else:
        target = transcript.expanduser().resolve()
        if not target.is_file():
            raise AgentSessionInfrastructureError(
                f"targeted transcript not found: {target}"
            )
        matched_tool = next(
            (
                source_tool
                for source_tool, directory in sources
                if directory.expanduser().is_dir()
                and target.is_relative_to(directory.expanduser().resolve())
            ),
            None,
        )
        if matched_tool is None:
            raise AgentSessionInfrastructureError(
                f"targeted transcript outside known sources: {target}"
            )
        selected = [(matched_tool, [target])]

    try:
        for source_tool, transcripts in selected:
            for candidate in transcripts:
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                key = str(candidate)
                recorded = emitted.get(key)
                if recorded is not None:
                    if recorded.get("sidechain"):
                        report.sidechain_skipped += 1
                        continue
                    if stat.st_size > int(recorded["size"]):
                        # Session reprise après émission : le résumé est figé
                        # (décision : calculé une fois) — signalé, pas ré-émis.
                        report.grown_after_emit += 1
                    else:
                        report.already_emitted += 1
                    continue
                modified = datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                )
                if transcript is None and moment - modified < quiet:
                    report.still_active += 1
                    continue
                try:
                    lines = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    continue
                summary = _PARSERS[source_tool](lines, candidate.stem)
                if summary is None:
                    report.unparseable += 1
                    continue
                if summary.sidechain:
                    report.sidechain_skipped += 1
                    if not dry_run:
                        emitted[key] = {
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                            "sidechain": True,
                            "emitted_at": moment.isoformat(),
                        }
                        manifest_dirty = True
                    continue
                event_id = session_event_id(
                    summary.source_tool, summary.session_id
                )
                if event_id in emitted_event_ids:
                    report.duplicate_sessions += 1
                    if not dry_run:
                        emitted[key] = {
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                            "event_id": event_id,
                            "emitted_at": moment.isoformat(),
                            "duplicate_of_session": summary.session_id,
                        }
                        manifest_dirty = True
                    continue
                if not dry_run:
                    if resolved_outbox is None:
                        resolved_outbox = ProducerOutbox()
                    payload = build_agent_session_payload(
                        resolved_outbox, summary, transcript_path=key
                    )
                    try:
                        enqueue_json_input(resolved_outbox, payload)
                    except sqlite3.IntegrityError:
                        # Déjà en file (passe précédente interrompue avant
                        # l'écriture du manifeste) : duplicate bénin.
                        report.duplicate_sessions += 1
                    except sqlite3.Error as exc:
                        raise AgentSessionInfrastructureError(
                            f"cannot enqueue: {exc}"
                        ) from exc
                    else:
                        report.emitted += 1
                    emitted[key] = {
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "event_id": event_id,
                        "emitted_at": moment.isoformat(),
                    }
                    manifest_dirty = True
                else:
                    report.emitted += 1
                emitted_event_ids.add(event_id)
    finally:
        # Même si une passe s'interrompt, ce qui a été enfilé est tracé :
        # sans cela, un re-run ré-émettrait les mêmes sessions (duplicates
        # inoffensifs grâce à l'event_id déterministe, mais bruyants).
        if manifest_dirty:
            _write_manifest(manifest_file, emitted)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit one derived agent_session event per finished session"
    )
    parser.add_argument("--claude-dir", type=Path, default=DEFAULT_CLAUDE_DIR)
    parser.add_argument("--codex-dir", type=Path, default=DEFAULT_CODEX_DIR)
    parser.add_argument("--outbox-database", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--quiet-minutes", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="targeted mode: emit only this transcript, quiet window bypassed",
    )
    args = parser.parse_args()

    try:
        report = emit_agent_sessions(
            claude_dir=args.claude_dir,
            codex_dir=args.codex_dir,
            outbox=(
                ProducerOutbox(args.outbox_database)
                if args.outbox_database
                else None
            ),
            manifest_path=args.manifest,
            quiet=timedelta(minutes=args.quiet_minutes),
            dry_run=args.dry_run,
            transcript=args.transcript,
        )
    except AgentSessionInfrastructureError as exc:
        print(f"Pulse agent sessions: {exc}")
        raise SystemExit(2) from exc

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Emitted: {report.emitted}")
    print(f"Already emitted: {report.already_emitted}")
    print(f"Still active (quiet window): {report.still_active}")
    if report.grown_after_emit:
        print(f"Grown after emit (summary frozen): {report.grown_after_emit}")
    if report.unparseable:
        print(f"Unparseable sessions: {report.unparseable}")
    if report.duplicate_sessions:
        print(f"Duplicate sessions (first emission wins): {report.duplicate_sessions}")
    if report.sidechain_skipped:
        print(f"Sidechain transcripts (skipped): {report.sidechain_skipped}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
