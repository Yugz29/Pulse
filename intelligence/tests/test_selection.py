from datetime import date, timedelta

from conftest import REFERENCE, at, session_view
from pulse_intelligence.config import Config
from pulse_intelligence.selection import (
    classify,
    classify_sessions,
    find_session,
    lookback_days,
    select_candidates,
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


def test_lookback_covers_today_and_yesterday_not_further(config):
    days = lookback_days(REFERENCE, config)

    assert days == [REFERENCE.astimezone().date(), REFERENCE.astimezone().date() - timedelta(days=1)]
    assert len(lookback_days(REFERENCE, Config(lookback_days=2))) == 3


def test_classify_sessions_reads_exactly_the_lookback_days(fake_core, client, config, state):
    today = REFERENCE.astimezone().date()
    yesterday = today - timedelta(days=1)
    before = yesterday - timedelta(days=1)
    fake_core.add_sessions(today.isoformat(), session_view("aaaaaaaaaaaaaaaa"))
    fake_core.add_sessions(yesterday.isoformat(), session_view("bbbbbbbbbbbbbbbb", started=-1500, ended=-1440))
    fake_core.add_sessions(before.isoformat(), session_view("cccccccccccccccc", started=-3000, ended=-2900))

    items = classify_sessions(client, now=REFERENCE, config=config, model_id="m", state=state)

    assert fake_core.requested_dates == [today.isoformat(), yesterday.isoformat()]
    assert [item.session.id for item in items] == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"]
    assert all(item.candidate for item in items)


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


def test_find_session_by_id_across_lookback(fake_core, client, config):
    today = REFERENCE.astimezone().date().isoformat()
    fake_core.add_sessions(today, session_view("aaaaaaaaaaaaaaaa"))

    found = find_session(client, "aaaaaaaaaaaaaaaa", now=REFERENCE, config=config)
    missing = find_session(client, "ffffffffffffffff", now=REFERENCE, config=config)

    assert found is not None and found.label == "work-1"
    assert missing is None
