"""Read-only Phase 2a debug memory views."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from daemon.memory.commit_episode_linker import link_commits_to_episodes
from daemon.memory.journal_candidate_builder import build_journal_candidates, journal_candidates_to_payload
from daemon.memory.journal_candidate_comparator import compare_journal_candidates
from daemon.memory.work_episode_builder import build_work_episodes

_JOURNAL_DATA_START = "<!-- pulse-journal-data:start"
_JOURNAL_DATA_END = "pulse-journal-data:end -->"


class DebugMemoryViews:
    """Build debug-only views from SessionMemory without mutating storage."""

    def __init__(self, session_memory: Any):
        self.session_memory = session_memory

    def get_work_episodes(self, date: datetime | None = None) -> dict[str, Any]:
        """Return experimental work episodes for debug/observation only."""
        now = datetime.now()
        target_date = (date or now).date()
        all_events = self._events_for_date(target_date)
        episodes = [asdict(episode) for episode in build_work_episodes(all_events)]
        return {
            "date": target_date.isoformat(),
            "generated_at": now.isoformat(),
            "episode_count": len(episodes),
            "episodes": episodes,
        }

    def get_journal_candidates(self, date: datetime | None = None) -> dict[str, Any]:
        """Return dry-run journal candidates from work episodes without writing memory."""
        episodes_payload = self.get_work_episodes(date=date)
        candidates = build_journal_candidates(episodes_payload.get("episodes", []))
        payload = journal_candidates_to_payload(candidates)
        return {
            "date": episodes_payload["date"],
            "generated_at": datetime.now().isoformat(),
            **payload,
        }

    def get_journal_comparison(self, date: datetime | None = None) -> dict[str, Any]:
        """Compare persisted journal entries and dry-run candidates for debug only."""
        now = datetime.now()
        target_date = (date or now).date()
        candidates_payload = self.get_journal_candidates(date=date)
        journal_entries = self._load_journal_entries_for_date(target_date.isoformat())
        comparison = compare_journal_candidates(
            journal_entries,
            candidates_payload.get("candidates", []),
        )
        return {
            "date": target_date.isoformat(),
            "generated_at": now.isoformat(),
            **comparison,
        }

    def get_commit_episode_links(self, date: datetime | None = None) -> dict[str, Any]:
        """Return dry-run commit-to-episode links for debug only."""
        now = datetime.now()
        target_date = (date or now).date()
        candidates_payload = self.get_journal_candidates(date=date)
        journal_entries = self._load_journal_entries_for_date(target_date.isoformat())
        links = link_commits_to_episodes(
            journal_entries,
            candidates_payload.get("candidates", []),
        )
        return {
            "date": target_date.isoformat(),
            "generated_at": now.isoformat(),
            **links,
        }

    def _events_for_date(self, target_date) -> list[dict[str, Any]]:
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        with self.session_memory._lock:
            with self.session_memory._connect() as conn:
                event_rows = conn.execute(
                    """
                    SELECT event_type, payload_json, created_at
                    FROM events
                    WHERE created_at >= ? AND created_at < ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (day_start.isoformat(), day_end.isoformat()),
                ).fetchall()

        all_events = []
        for row in event_rows:
            observed_at = _parse_iso_datetime(row["created_at"])
            if observed_at is None:
                continue
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = {}
            all_events.append(
                {
                    "type": row["event_type"],
                    "payload": payload,
                    "timestamp": observed_at,
                }
            )
        return all_events

    def _load_journal_entries_for_date(self, day: str) -> list[dict[str, Any]]:
        journal_file = self.session_memory.db_path.parent / "memory" / "sessions" / f"{day}.md"
        if not journal_file.exists():
            return []
        try:
            content = journal_file.read_text(encoding="utf-8")
        except OSError:
            return []
        start_index = content.find(_JOURNAL_DATA_START)
        if start_index < 0:
            return []
        payload_start = content.find("\n", start_index)
        if payload_start < 0:
            return []
        end_index = content.find(_JOURNAL_DATA_END, payload_start)
        if end_index < 0:
            return []
        try:
            raw_entries = json.loads(content[payload_start:end_index].strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(raw_entries, list):
            return []
        return [entry for entry in raw_entries if isinstance(entry, dict) and entry.get("entry_id")]


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
