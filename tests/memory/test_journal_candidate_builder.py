from daemon.memory.journal_candidate_builder import build_journal_candidates, journal_candidates_to_payload


def episode(**overrides):
    base = {
        "id": "work-episode-2026-05-05T10:00:00",
        "project": "Pulse",
        "probable_task": "coding",
        "dominant_scope": "source",
        "started_at": "2026-05-05T10:00:00",
        "ended_at": "2026-05-05T10:12:00",
        "duration_min": 12,
        "boundary_reason": "screen_locked",
        "strong_event_count": 2,
        "weak_event_count": 1,
        "confidence": 0.9,
        "uncertainty_flags": ["single_block"],
        "debug_reason": "split on boundary event screen_locked",
    }
    base.update(overrides)
    return base


def test_closed_episode_becomes_active_journal_candidate():
    candidates = build_journal_candidates([episode()])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.ignored is False
    assert candidate.status == "candidate"
    assert candidate.ignore_reason is None
    assert candidate.episode_id == "work-episode-2026-05-05T10:00:00"
    assert candidate.dominant_scope == "source"


def test_end_of_events_episode_is_ignored_as_open_episode():
    candidates = build_journal_candidates([
        episode(boundary_reason="end_of_events", debug_reason="episode open until end of observed events")
    ])

    candidate = candidates[0]
    assert candidate.ignored is True
    assert candidate.status == "ignored"
    assert candidate.ignore_reason == "open_episode_end_of_events"
    assert candidate.debug_reason == "episode open until end of observed events"


def test_candidate_does_not_create_commit_or_delivery_fields():
    payload = journal_candidates_to_payload(build_journal_candidates([episode()]))
    candidate = payload["candidates"][0]

    assert "commit_message" not in candidate
    assert "delivered_at" not in candidate


def test_low_evidence_short_episode_remains_candidate_with_flags():
    candidates = build_journal_candidates([
        episode(
            duration_min=1,
            evidence_count=1,
            confidence=0.25,
            uncertainty_flags=["single_block", "low_evidence", "short_episode"],
            debug_reason="split after 60 min long gap",
        )
    ])

    candidate = candidates[0]
    assert candidate.ignored is False
    assert candidate.status == "candidate"
    assert candidate.confidence == 0.25
    assert candidate.uncertainty_flags == ("single_block", "low_evidence", "short_episode")
    assert candidate.debug_reason == "split after 60 min long gap"
