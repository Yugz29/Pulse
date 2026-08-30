import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from daemon_v2.agent_sessions import (
    AgentSessionInfrastructureError,
    build_agent_session_payload,
    emit_agent_sessions,
    parse_claude_session,
    parse_codex_session,
    session_event_id,
)
from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_markdown
from daemon_v2.ingest import normalize_event
from daemon_v2.producer_outbox import ProducerOutbox
from daemon_v2.trace_store import TraceStore


# Ancre fixe à midi : stabilité et bornes déterministes.
NOW = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)


def claude_lines():
    return [
        json.dumps(
            {
                "type": "user",
                "userType": "external",
                "timestamp": "2026-07-03T09:00:00.000Z",
                "cwd": "/Users/dev/Projets/Pulse/Pulse_Core",
                "gitBranch": "main",
                "version": "2.1.251",
                "sessionId": "abc-123",
                "message": {
                    "role": "user",
                    "content": "<command-message>plan</command-message>",
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "userType": "external",
                "timestamp": "2026-07-03T09:01:00.000Z",
                "sessionId": "abc-123",
                "message": {
                    "role": "user",
                    "content": "Corrige le bug avec le token sk-abcdef1234567890XYZ merci",
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-07-03T09:02:30.000Z",
                "sessionId": "abc-123",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Je corrige."}],
                },
            }
        ),
        # tool_result renvoyé au modèle : ligne "user" SANS texte lisible.
        json.dumps(
            {
                "type": "user",
                "userType": "external",
                "timestamp": "2026-07-03T09:03:00.000Z",
                "sessionId": "abc-123",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1"}],
                },
            }
        ),
        json.dumps({"type": "file-history-snapshot", "snapshot": {}}),
    ]


def test_parse_claude_session_extracts_versioned_summary_fields():
    summary = parse_claude_session(claude_lines(), "fallback")

    assert summary is not None
    assert summary.source_tool == "claude-code"
    assert summary.session_id == "abc-123"
    assert summary.started_at.isoformat() == "2026-07-03T09:00:00+00:00"
    assert summary.ended_at.isoformat() == "2026-07-03T09:03:00+00:00"
    assert summary.user_messages == 2
    assert summary.assistant_messages == 1
    assert summary.cwd == "/Users/dev/Projets/Pulse/Pulse_Core"
    assert summary.git_branch == "main"
    assert summary.tool_version == "2.1.251"
    # L'enveloppe de slash command est sautée ; le vrai prompt est rédigé.
    assert summary.first_prompt == "Corrige le bug avec le token [REDACTED] merci"


def test_parse_codex_session_reads_meta_and_messages():
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-03T10:00:00.000Z",
                "type": "session_meta",
                "payload": {"id": "codex-1", "cwd": "/Users/dev/repo"},
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-03T10:00:05.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Ajoute un test"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-03T10:01:00.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Fait."}],
                },
            }
        ),
    ]

    summary = parse_codex_session(lines, "rollout-fallback")

    assert summary is not None
    assert summary.source_tool == "codex"
    assert summary.session_id == "codex-1"
    assert summary.cwd == "/Users/dev/repo"
    assert summary.user_messages == 1
    assert summary.assistant_messages == 1
    assert summary.first_prompt == "Ajoute un test"
    assert summary.started_at.isoformat() == "2026-07-03T10:00:00+00:00"
    assert summary.ended_at.isoformat() == "2026-07-03T10:01:00+00:00"


def test_unparseable_session_without_timestamps_returns_none():
    assert parse_claude_session(["not json", "{}"], "x") is None
    assert parse_codex_session([], "x") is None


def _write_transcript(directory: Path, name: str, lines: list[str], *, age_hours: float):
    transcript = directory / name
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n".join(lines), encoding="utf-8")
    stamp = (NOW - timedelta(hours=age_hours)).timestamp()
    os.utime(transcript, (stamp, stamp))
    return transcript


def emit(tmp_path, **overrides):
    defaults = dict(
        claude_dir=tmp_path / "claude",
        codex_dir=tmp_path / "codex",
        outbox=ProducerOutbox(tmp_path / "outbox.sqlite3"),
        manifest_path=tmp_path / "manifest.json",
        now=NOW,
    )
    defaults.update(overrides)
    return emit_agent_sessions(**defaults)


def test_emit_end_to_end_enqueues_canonical_event_once(tmp_path):
    _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=2
    )
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")

    report = emit(tmp_path, outbox=outbox)

    assert report.emitted == 1
    pending = outbox.oldest()
    assert pending is not None
    payload = json.loads(pending.payload_json)
    assert payload["type"] == "agent_session"
    assert payload["event_id"] == session_event_id("claude-code", "abc-123")
    assert payload["producer"]["name"] == "pulse-agent-sessions"
    assert payload["details"]["summary_version"] == 1
    assert payload["details"]["workspace"] == "/Users/dev/Projets/Pulse/Pulse_Core"
    assert "sk-abcdef" not in pending.payload_json
    # Le payload enfilé traverse l'ingestion canonique telle quelle.
    ingested = normalize_event(payload)
    assert ingested.activity.activity_type == "agent_session"

    # Second passage : rien à ré-émettre.
    second = emit(tmp_path, outbox=outbox)
    assert second.emitted == 0
    assert second.already_emitted == 1


def test_grown_session_is_flagged_but_never_reemitted(tmp_path):
    transcript = _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=2
    )
    emit(tmp_path)

    grown = claude_lines() + [
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-07-03T11:00:00.000Z",
                "message": {"role": "assistant", "content": "suite"},
            }
        )
    ]
    _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", grown, age_hours=2
    )
    assert transcript.exists()

    report = emit(tmp_path)

    # Résumé calculé une fois (décision 2026-08-30) : figé, jamais recalculé.
    assert report.emitted == 0
    assert report.grown_after_emit == 1


def test_recent_session_waits_for_the_quiet_window(tmp_path):
    _write_transcript(
        tmp_path / "claude", "proj/live.jsonl", claude_lines(), age_hours=0.1
    )

    report = emit(tmp_path)

    assert report.emitted == 0
    assert report.still_active == 1


def test_dry_run_writes_nothing(tmp_path):
    _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=2
    )
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")

    report = emit(tmp_path, outbox=outbox, dry_run=True)

    assert report.emitted == 1
    assert outbox.counts() == (0, 0)
    assert not (tmp_path / "manifest.json").exists()


def test_corrupt_manifest_is_an_infrastructure_error(tmp_path):
    (tmp_path / "manifest.json").write_text("broken{{", encoding="utf-8")

    with pytest.raises(AgentSessionInfrastructureError):
        emit(tmp_path)


def test_agent_session_renders_in_the_daily_trace(tmp_path):
    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    _write_transcript(
        tmp_path / "claude", "proj/abc-123.jsonl", claude_lines(), age_hours=2
    )
    emit(tmp_path, outbox=outbox)
    payload = json.loads(outbox.oldest().payload_json)

    store = TraceStore(tmp_path / "trace.db")
    store.append_event(normalize_event(payload))
    trace = build_daily_trace(store, date(2026, 7, 3), timezone.utc)
    markdown = render_daily_trace_markdown(trace, archive_mode=True)

    assert trace["activity_count"] == 1
    assert "Agent session (claude-code)" in markdown
