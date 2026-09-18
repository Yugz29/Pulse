from datetime import date, timedelta

from conftest import REFERENCE, at, session_view
from pulse_intelligence.config import Config
from pulse_intelligence.selection import (
    MAX_CATCHUP_DAYS,
    classify,
    classify_sessions,
    find_session,
    select_candidates,
    selection_days,
    SessionView,
)


def view(session_id="aaaaaaaaaaaaaaaa", **kwargs) -> SessionView:
    return SessionView(raw=session_view(session_id, **kwargs), day=REFERENCE.date())


def test_open_session_is_not_a_candidate(config):
    result = classify(view(is_open=True), config=config, model_id="m", known=set())

    assert result.candidate is False
    assert result.reason == "session ouverte"


def test_too_short_session_is_not_a_candidate(config):
    result = classify(
        view(started=-10, ended=-6, activity_count=12), config=config, model_id="m", known=set()
    )

    assert result.candidate is False
    assert result.reason == "trop courte (4 min, 12 activités)"


def test_short_but_busy_session_is_a_candidate(config):
    result = classify(
        view(started=-10, ended=-6, activity_count=30), config=config, model_id="m", known=set()
    )

    assert result.candidate is True


def _with_commit(raw, commit_hash: str, at: float):
    """La forme réelle du schéma 3 : le commit est un fait `commit` de la
    chronologie des observations, pas un champ `git` de la vue."""
    raw["observations"] = {
        "version": 1,
        "timeline": [
            {"ref": "o1", "kind": "file", "path": "docs/decisions/x.md", "at": 0.0,
             "changes": [{"event": "modified", "first_at": 0.0, "last_at": 0.0, "count": 1}]},
            {"ref": "o2", "kind": "commit", "hash": commit_hash, "branch": "main", "at": at},
        ],
        "applications": [],
        "last_observed": {"commands": [], "files": ["o1"], "git": {"/work/Pulse": {"branch": "o2", "commit": "o2"}}},
        "sources": {"o1": ["src-1"], "o2": ["src-2"]},
    }
    return raw


def test_short_session_carrying_a_commit_is_a_candidate(config):
    # work-9 dd06e6c8 du 2026-09-15 : 3 min, 20 activités, commit 86c0348.
    raw = _with_commit(
        session_view("dd06e6c8932f06ee", label="work-9", started=-10, ended=-7, activity_count=20),
        "86c03480000000000000000000000000000000000", 220.0,
    )
    result = classify(SessionView(raw=raw, day=REFERENCE.date()), config=config, model_id="m", known=set())

    assert result.candidate is True
    assert result.reason == "candidate"


def test_zero_minute_session_carrying_a_commit_is_a_candidate(config):
    # work-10 8069a1f4 du 2026-09-15 : 0 min, 5 activités, commit 626bbad.
    raw = _with_commit(
        session_view("8069a1f4a4200e5e", label="work-10", started=-10, ended=-10, activity_count=5),
        "626bbad48a5b2436027a5e6903590457e265d4af", 9.0,
    )
    result = classify(SessionView(raw=raw, day=REFERENCE.date()), config=config, model_id="m", known=set())

    assert result.candidate is True
    assert result.reason == "candidate"


def test_existing_summary_same_version_blocks_and_other_version_does_not(config):
    known = {("aaaaaaaaaaaaaaaa", "v1", "m")}

    same = classify(view(), config=config, model_id="m", known=known)
    other_model = classify(view(), config=config, model_id="m2", known=known)
    other_prompt = classify(
        view(), config=Config(prompt_version="v2"), model_id="m", known=known
    )

    assert same.candidate is False and same.reason == "résumé existant (v1, m)"
    assert other_model.candidate is True
    assert other_prompt.candidate is True


def test_core_advertised_summaries_are_honoured_when_present(config):
    result = classify(
        view(summaries=[{"prompt_version": "v1", "model_id": "m"}]),
        config=config,
        model_id="m",
        known=set(),
    )

    assert result.candidate is False


TODAY = REFERENCE.astimezone().date()


def _days_back(count: int) -> list[date]:
    return [TODAY - timedelta(days=offset) for offset in range(count + 1)]


def test_selection_window_is_full_without_a_marker(state):
    # Premier passage, ou état perdu : sept jours en arrière, aujourd'hui compris.
    assert selection_days(REFERENCE, state) == _days_back(MAX_CATCHUP_DAYS)
    assert len(selection_days(REFERENCE, state)) == 8


def test_selection_window_starts_on_the_day_of_the_last_complete_pass(state):
    # Régime quotidien : le passage d'hier compte encore (des sessions s'y sont
    # closes après lui), rien avant.
    state.record_complete_pass(REFERENCE - timedelta(days=1))
    assert selection_days(REFERENCE, state) == _days_back(1)

    # Un second passage le même jour ne relit que la journée.
    state.record_complete_pass(REFERENCE - timedelta(hours=2))
    assert selection_days(REFERENCE, state) == [TODAY]


def test_selection_window_never_goes_past_the_cap(state):
    # Trois semaines sans lot : on relit sept jours, pas vingt et un.
    state.record_complete_pass(REFERENCE - timedelta(days=21))
    assert selection_days(REFERENCE, state) == _days_back(MAX_CATCHUP_DAYS)

    # Repère à quatre jours : quatre jours plus aujourd'hui.
    state.record_complete_pass(REFERENCE - timedelta(days=4))
    assert selection_days(REFERENCE, state) == _days_back(4)


def test_selection_window_ignores_a_marker_in_the_future(state):
    # Horloge reculée : jamais de fenêtre vide, aujourd'hui au moins.
    state.record_complete_pass(REFERENCE + timedelta(days=3))
    assert selection_days(REFERENCE, state) == [TODAY]


def test_marker_survives_a_reload_and_an_unreadable_one_means_full_window(tmp_path):
    from pulse_intelligence.state import JobState

    path = tmp_path / "state.json"
    JobState.load(path).record_complete_pass(REFERENCE - timedelta(days=2))
    reloaded = JobState.load(path)
    assert reloaded.last_complete_pass_at() == REFERENCE - timedelta(days=2)
    assert selection_days(REFERENCE, reloaded) == _days_back(2)

    reloaded.last_complete_pass = "pas une date"
    assert reloaded.last_complete_pass_at() is None
    assert selection_days(REFERENCE, reloaded) == _days_back(MAX_CATCHUP_DAYS)


def test_classify_sessions_reads_exactly_the_selection_window(fake_core, client, config, state):
    yesterday = TODAY - timedelta(days=1)
    before = yesterday - timedelta(days=1)
    fake_core.add_sessions(TODAY.isoformat(), session_view("aaaaaaaaaaaaaaaa"))
    fake_core.add_sessions(yesterday.isoformat(), session_view("bbbbbbbbbbbbbbbb", started=-1500, ended=-1440))
    fake_core.add_sessions(before.isoformat(), session_view("cccccccccccccccc", started=-3000, ended=-2900))
    state.record_complete_pass(REFERENCE - timedelta(days=1))

    items = classify_sessions(client, now=REFERENCE, config=config, model_id="m", state=state)

    assert fake_core.requested_dates == [TODAY.isoformat(), yesterday.isoformat()]
    assert [item.session.id for item in items] == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"]
    assert all(item.candidate for item in items)


def test_a_day_skipped_by_a_missed_pass_is_caught_up(fake_core, client, config, state):
    # Le lot d'hier n'a pas tourné : la session d'avant-hier est encore lue.
    before = TODAY - timedelta(days=2)
    fake_core.add_sessions(before.isoformat(), session_view("cccccccccccccccc", started=-3000, ended=-2900))
    state.record_complete_pass(REFERENCE - timedelta(days=2))

    candidates = select_candidates(client, now=REFERENCE, config=config, model_id="m", state=state)

    assert [s.id for s in candidates] == ["cccccccccccccccc"]
    assert fake_core.requested_dates == [d.isoformat() for d in _days_back(2)]


def test_state_known_summaries_exclude_sessions(fake_core, client, config, state):
    today = REFERENCE.astimezone().date().isoformat()
    fake_core.add_sessions(today, session_view("aaaaaaaaaaaaaaaa"), session_view("bbbbbbbbbbbbbbbb", label="work-2", started=-50, ended=-20))
    state.record_emitted(
        "evt", session_id="aaaaaaaaaaaaaaaa", prompt_version="v1", model_id="fake/summarizer", at="x"
    )

    candidates = select_candidates(
        client, now=REFERENCE, config=config, model_id="fake/summarizer", state=state
    )

    assert [session.id for session in candidates] == ["bbbbbbbbbbbbbbbb"]


def test_session_whose_id_vanished_between_two_passes_is_simply_forgotten(
    fake_core, client, config, state
):
    today = REFERENCE.astimezone().date().isoformat()
    fake_core.add_sessions(today, session_view("aaaaaaaaaaaaaaaa"))
    first = select_candidates(client, now=REFERENCE, config=config, model_id="m", state=state)
    assert [s.id for s in first] == ["aaaaaaaaaaaaaaaa"]

    # Un événement tardif a changé la composition : nouvel id, l'ancien disparaît.
    fake_core.sessions_by_date[today] = [session_view("dddddddddddddddd")]
    state.record_emitted("evt", session_id="aaaaaaaaaaaaaaaa", prompt_version="v1", model_id="m", at="x")

    second = select_candidates(client, now=REFERENCE, config=config, model_id="m", state=state)

    assert [s.id for s in second] == ["dddddddddddddddd"]


def test_find_session_by_id_across_the_selection_window(fake_core, client, state):
    today = REFERENCE.astimezone().date().isoformat()
    fake_core.add_sessions(today, session_view("aaaaaaaaaaaaaaaa"))

    found = find_session(client, "aaaaaaaaaaaaaaaa", now=REFERENCE, state=state)
    missing = find_session(client, "ffffffffffffffff", now=REFERENCE, state=state)

    assert found is not None and found.label == "work-1"
    assert missing is None
