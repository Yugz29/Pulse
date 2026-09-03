import json
from pathlib import Path

from conftest import REFERENCE, at, context_view, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.session_summary import run_pass
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def base_args(fake_core, tmp_path) -> list[str]:
    return ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json")]


# --- run_pass ------------------------------------------------------------------


def test_run_pass_summarizes_every_candidate_once(fake_core, client, config, state):
    fake_core.add_sessions(
        today(),
        session_view("aaaaaaaaaaaaaaaa"),
        session_view("bbbbbbbbbbbbbbbb", label="work-2", started=-50, ended=-20),
        session_view("cccccccccccccccc", label="work-3", started=-10, ended=-6, activity_count=12),
    )
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    first = run_pass(client, summarizer, config, state, now=REFERENCE)
    second = run_pass(client, summarizer, config, state, now=REFERENCE)

    assert first.candidates == 2 and first.count("created") == 2
    assert [o.session_id for o in first.outcomes] == ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"]
    assert len(fake_core.posts) == 2
    assert len(summarizer.calls) == 2
    # Second passage : les deux sessions sont connues de l'état local, plus
    # candidates, donc ni POST ni appel au modèle, ni même lecture de /context.
    assert second.candidates == 0 and second.outcomes == []
    assert len(fake_core.posts) == 2
    assert len(summarizer.calls) == 2
    assert fake_core.context_requests == 2


def test_run_pass_gives_up_after_three_failures_and_never_asks_again(fake_core, client, config, state):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    summarizer = FakeSummarizer(outputs="pas du json", model_id="fake/summarizer")

    statuses = [
        run_pass(client, summarizer, config, state, now=REFERENCE).outcomes[0].status
        for _ in range(5)
    ]

    assert statuses == ["failed", "failed", "given_up", "given_up", "given_up"]
    assert len(summarizer.calls) == 3
    assert fake_core.context_requests == 3
    assert fake_core.posts == []
    # L'état survit à un redémarrage.
    reloaded = JobState.load(state.path)
    assert reloaded.is_failed("aaaaaaaaaaaaaaaa")


def test_run_pass_reports_a_core_that_vanished(config, state, tmp_path):
    from pulse_intelligence.core_client import CoreClient

    report = run_pass(
        CoreClient("http://127.0.0.1:9", timeout_s=0.5),
        FakeSummarizer(outputs=valid_output()),
        config,
        state,
    )

    assert report.candidates == 0 and report.outcomes == []
    assert report.error and "injoignable" in report.error


# --- CLI run -----------------------------------------------------------------------


def test_cli_run_once_then_nothing_left(fake_core, tmp_path, fake_output_file, capsys):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))

    first = cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)])
    first_out = capsys.readouterr().out
    second = cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)])
    second_out = capsys.readouterr().out

    assert first == 0 and "candidates=1 created=1" in first_out
    assert "  created aaaaaaaaaaaaaaaa event_id=" in first_out
    assert second == 0 and "candidates=0 created=0" in second_out
    assert len(fake_core.posts) == 1


def test_cli_run_requires_fake_until_a_real_model_exists(fake_core, tmp_path, capsys):
    code = cli.main([*base_args(fake_core, tmp_path), "run", "--once"])

    assert code == 1
    assert "--fake" in capsys.readouterr().err


def test_cli_run_with_core_down_exits_2(tmp_path, capsys, fake_output_file):
    code = cli.main(
        ["--core-url", "http://127.0.0.1:9", "--state", str(tmp_path / "state.json"), "run", "--once", "--fake", str(fake_output_file)]
    )

    assert code == 2
    assert "Core injoignable" in capsys.readouterr().err


# --- CLI show ---------------------------------------------------------------------


def latest_summary() -> dict:
    return {
        "id": "aaaaaaaaaaaaaaaa",
        "label": "work-1",
        "session_ended_at": at(-60).isoformat(),
        "reprise": {
            "doing": "Tu implémentais la route /context/sessions dans Core.",
            "stopped_at": "Tu venais de faire passer la suite de tests.",
            "open": "La PR attend ta relecture.",
        },
        "confidence": "high",
        "age_minutes": 60,
    }


def test_cli_show_latest_reads_core(fake_core, tmp_path, capsys):
    fake_core.default_context = context_view(reference_at=REFERENCE, last_session_summary=latest_summary())

    code = cli.main([*base_args(fake_core, tmp_path), "show", "latest"])
    body = json.loads(capsys.readouterr().out)
    md_code = cli.main([*base_args(fake_core, tmp_path), "show", "latest", "--md"])
    md = capsys.readouterr().out

    assert code == 0 and body["id"] == "aaaaaaaaaaaaaaaa"
    assert md_code == 0
    assert md.rstrip("\n").split("\n") == [
        "Tu implémentais la route /context/sessions dans Core.",
        "Tu venais de faire passer la suite de tests.",
        "La PR attend ta relecture.",
    ]


def test_cli_show_latest_without_any_summary(fake_core, tmp_path, capsys):
    code = cli.main([*base_args(fake_core, tmp_path), "show", "latest"])

    assert code == 1
    assert "aucun résumé" in capsys.readouterr().err


def test_cli_show_by_id_reads_the_local_copy_of_the_emitted_event(fake_core, tmp_path, fake_output_file, capsys):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    assert cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == 0
    capsys.readouterr()

    code = cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa"])
    event = json.loads(capsys.readouterr().out)
    md_code = cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa", "--md"])
    md = capsys.readouterr().out

    assert code == 0
    assert event["type"] == "session_summary"
    assert event["details"]["session_id"] == "aaaaaaaaaaaaaaaa"
    assert event["details"]["structured"]["confidence"] == "high"
    assert md_code == 0 and len(md.rstrip("\n").split("\n")) == 3


def test_cli_show_unknown_id_falls_back_to_core_then_fails(fake_core, tmp_path, capsys):
    fake_core.default_context = context_view(reference_at=REFERENCE, last_session_summary=latest_summary())

    known_in_core = cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa", "--md"])
    known_out = capsys.readouterr().out
    unknown = cli.main([*base_args(fake_core, tmp_path), "show", "ffffffffffffffff"])
    unknown_err = capsys.readouterr().err

    assert known_in_core == 0 and len(known_out.rstrip("\n").split("\n")) == 3
    assert unknown == 1 and "aucun résumé connu" in unknown_err
