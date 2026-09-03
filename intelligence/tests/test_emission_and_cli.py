import json
import stat

from conftest import REFERENCE, at, context_view, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.selection import SessionView
from pulse_intelligence.session_summary import summarize_session
from pulse_intelligence.summarizer import FakeSummarizer


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def test_emission_posts_once_then_never_calls_the_model_again(fake_core, client, config, state):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    first = summarize_session(session, client=client, summarizer=summarizer, config=config, state=state)
    second = summarize_session(session, client=client, summarizer=summarizer, config=config, state=state)

    assert first.status == "created"
    assert second.status == "already_known"
    assert len(fake_core.posts) == 1
    assert len(summarizer.calls) == 1
    assert fake_core.posts[0]["details"]["session_id"] == "aaaaaaaaaaaaaaaa"
    assert state.known_summaries() == {("aaaaaaaaaaaaaaaa", "v1", "fake/summarizer")}
    assert stat.S_IMODE(state.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.path.parent.stat().st_mode) == 0o700


def test_core_replies_duplicate_when_the_state_was_lost(fake_core, client, config, state, tmp_path):
    session = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.date())
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    summarize_session(session, client=client, summarizer=summarizer, config=config, state=state)

    from pulse_intelligence.state import JobState

    fresh_state = JobState.load(tmp_path / "other" / "state.json")
    outcome = summarize_session(
        session, client=client, summarizer=summarizer, config=config, state=fresh_state
    )

    assert outcome.status == "duplicate"
    assert len(fake_core.posts) == 2  # Core a répondu duplicate, rien de nouveau en base


def test_cli_list_marks_candidates_with_a_reason(fake_core, tmp_path, capsys):
    fake_core.add_sessions(
        today(),
        session_view("aaaaaaaaaaaaaaaa"),
        session_view("bbbbbbbbbbbbbbbb", label="work-2", started=-10, ended=-6, activity_count=12),
        session_view("cccccccccccccccc", label="work-3", started=-5, ended=-1, is_open=True),
    )

    code = cli.main(["--core-url", fake_core.url, "--state", str(tmp_path / "state.json"), "list"])

    assert code == 0
    output = capsys.readouterr().out
    assert "* work-1   aaaaaaaaaaaaaaaa" in output and "candidate" in output
    assert "  work-2   bbbbbbbbbbbbbbbb" in output and "trop courte (4 min, 12 activités)" in output
    assert "  work-3   cccccccccccccccc" in output and "session ouverte" in output


def test_cli_list_json(fake_core, tmp_path, capsys):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))

    code = cli.main(
        ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json"), "list", "--date", today(), "--json"]
    )

    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["id"] == "aaaaaaaaaaaaaaaa" and rows[0]["candidate"] is True
    assert fake_core.requested_dates == [today()]


def test_cli_summarize_dry_run_prints_the_event_and_emits_nothing(
    fake_core, tmp_path, fake_output_file, capsys
):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    fake_core.add_context(at(-60), context_view(reference_at=at(-60)))

    code = cli.main(
        [
            "--core-url", fake_core.url, "--state", str(tmp_path / "state.json"),
            "summarize", "aaaaaaaaaaaaaaaa", "--dry-run", "--fake", str(fake_output_file),
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert output.startswith("dry_run work-1 aaaaaaaaaaaaaaaa event_id=")
    event = json.loads(output.split("\n", 1)[1])
    assert event["details"]["source_event_ids_hash"] == "aaaaaaaaaaaaaaaa"
    assert fake_core.posts == []
    assert not (tmp_path / "state.json").exists()


def test_cli_summarize_without_a_model_explains(fake_core, tmp_path, capsys):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))

    code = cli.main(
        ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json"), "summarize", "aaaaaaaaaaaaaaaa", "--dry-run"]
    )

    assert code == 1
    assert "--fake" in capsys.readouterr().err


def test_cli_unknown_session(fake_core, tmp_path, fake_output_file, capsys):
    code = cli.main(
        [
            "--core-url", fake_core.url, "--state", str(tmp_path / "state.json"),
            "summarize", "ffffffffffffffff", "--dry-run", "--fake", str(fake_output_file),
        ]
    )

    assert code == 1
    assert "introuvable" in capsys.readouterr().err


def test_cli_reports_a_stopped_core_and_exits_2(tmp_path, capsys):
    code = cli.main(["--core-url", "http://127.0.0.1:9", "--state", str(tmp_path / "state.json"), "list"])

    assert code == 2
    assert "Core injoignable" in capsys.readouterr().err


def test_client_refuses_an_old_core_schema(fake_core, client):
    from pulse_intelligence.core_client import CoreError

    fake_core.default_context = {**context_view(reference_at=REFERENCE), "schema_version": 1}

    import pytest

    with pytest.raises(CoreError, match="schema_version 1"):
        client.get_context()
