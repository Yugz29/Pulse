import json
import re
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

    code = cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa", "--json"])
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


# --- CLI show : fiche, annexe, préfixe, --all --------------------------------------


def card_lines(text: str) -> dict[str, str]:
    """La fiche en dictionnaire « libellé → valeur », clés sans l'indentation."""
    lines = {}
    for line in text.rstrip("\n").split("\n"):
        key, _, value = line.strip().partition("  ")
        lines[key.strip()] = value.strip()
    return lines


def previous_of_another_session() -> dict:
    return {
        "id": "9999999999999999",
        "label": "work-0",
        "session_ended_at": at(-150).isoformat(),
        "reprise": {
            "doing": "Tu préparais la migration.",
            "stopped_at": "Avant le premier commit.",
            "open": "PR #28 et migration restent à vérifier.",
        },
        "confidence": "medium",
        "age_minutes": 90,
    }


def test_cli_show_card_puts_the_received_open_under_the_produced_one(fake_core, tmp_path, fake_output_file, capsys):
    """Le résumé a été produit avec une annexe previous_summary : la fiche montre
    le `open` reçu juste sous le `open` produit (jugement de D1)."""
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    fake_core.add_context(
        at(-60), context_view(reference_at=at(-60), last_session_summary=previous_of_another_session())
    )
    assert cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == 0
    capsys.readouterr()

    code = cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa"])
    out = capsys.readouterr().out
    card = card_lines(out)

    assert code == 0
    assert card["session"].startswith("aaaaaaaaaaaaaaaa  work-1  ")
    # La version est celle de la config par défaut de la CLI, pas de la fixture.
    assert re.fullmatch(r"v\d+  fake/summarizer  généré \d{4}-\d{2}-\d{2} \d{2}:\d{2}", card["résumé"])
    assert card["confidence"] == "high"
    assert card["doing"] == "Tu implémentais la route /context/sessions dans Core."
    assert card["stopped_at"] == "Tu venais de faire passer la suite de tests."
    assert card["open"] == "La PR attend ta relecture."
    assert card["↳ reçu"] == "PR #28 et migration restent à vérifier.  [previous_summary 9999999999999999 work-0]"
    assert card["central_files"] == "core/daemon_v2/routes.py"
    # L'ordre compte : le reçu suit immédiatement le produit.
    lines = out.rstrip("\n").split("\n")
    assert lines.index(next(l for l in lines if l.startswith("  ↳ reçu"))) == lines.index(
        next(l for l in lines if l.startswith("open "))
    ) + 1


def test_cli_show_card_says_when_there_was_no_annex(fake_core, tmp_path, fake_output_file, capsys):
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    assert cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == 0
    capsys.readouterr()

    assert cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa"]) == 0
    card = card_lines(capsys.readouterr().out)

    assert card["↳ reçu"] == "(aucune annexe previous_summary)"


def test_cli_show_card_distinguishes_unknown_annex_on_older_state(fake_core, tmp_path, fake_output_file, capsys):
    """Un état local écrit avant l'enregistrement de l'annexe n'en porte pas la
    clé : « inconnue », jamais « aucune »."""
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    assert cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == 0
    capsys.readouterr()
    state_path = tmp_path / "state.json"
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    for entry in raw["emitted"].values():
        entry.pop("previous_summary")
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    assert cli.main([*base_args(fake_core, tmp_path), "show", "aaaaaaaaaaaaaaaa"]) == 0
    card = card_lines(capsys.readouterr().out)

    assert card["↳ reçu"].startswith("(annexe previous_summary inconnue")


def test_annex_survives_a_replayed_post(fake_core, client, config, state):
    """Le POST échoue, le payload reste pending avec son annexe ; le rejeu
    l'emporte dans emitted sans rappeler le modèle."""
    from pulse_intelligence.session_summary import summarize_session
    from pulse_intelligence.selection import SessionView

    view = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.astimezone().date())
    fake_core.add_context(
        at(-60), context_view(reference_at=at(-60), last_session_summary=previous_of_another_session())
    )
    fake_core.fail_posts = 1
    summarizer = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")

    first = summarize_session(view, client=client, summarizer=summarizer, config=config, state=state)
    second = summarize_session(view, client=client, summarizer=summarizer, config=config, state=state)

    assert first.status == "failed" and second.status == "created"
    assert len(summarizer.calls) == 1
    entries = JobState.load(state.path).summaries_for("aaaaaaaaaaaaaaaa")
    assert len(entries) == 1
    assert entries[0]["previous_summary"]["id"] == "9999999999999999"
    assert entries[0]["previous_summary"]["reprise"]["open"] == "PR #28 et migration restent à vérifier."


def test_cli_show_accepts_a_prefix_and_refuses_an_ambiguous_one(fake_core, tmp_path, fake_output_file, capsys):
    fake_core.add_sessions(
        today(),
        session_view("aaaaaaaaaaaaaaaa"),
        session_view("aaaabbbbbbbbbbbb", label="work-2", started=-50, ended=-20),
    )
    assert cli.main([*base_args(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == 0
    capsys.readouterr()

    unique = cli.main([*base_args(fake_core, tmp_path), "show", "aaaab"])
    unique_out = capsys.readouterr().out
    ambiguous = cli.main([*base_args(fake_core, tmp_path), "show", "aaaa"])
    ambiguous_err = capsys.readouterr().err

    assert unique == 0 and card_lines(unique_out)["session"].startswith("aaaabbbbbbbbbbbb  work-2")
    assert ambiguous == 1
    assert "préfixe ambigu" in ambiguous_err
    assert "aaaaaaaaaaaaaaaa" in ambiguous_err and "aaaabbbbbbbbbbbb" in ambiguous_err


def test_cli_show_all_lists_coexisting_summaries_oldest_first(fake_core, tmp_path, capsys):
    """Deux versions de prompt, deux résumés de la même session : `--all` les
    rend tous, `show` sans option ne rend que le dernier."""
    from pulse_intelligence.config import Config
    from pulse_intelligence.core_client import CoreClient
    from pulse_intelligence.session_summary import summarize_session
    from pulse_intelligence.selection import SessionView

    view = SessionView(raw=session_view("aaaaaaaaaaaaaaaa"), day=REFERENCE.astimezone().date())
    client = CoreClient(fake_core.url, timeout_s=5.0)
    state = JobState.load(tmp_path / "state.json")
    v1 = FakeSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    v2 = FakeSummarizer(
        outputs=valid_output(
            reprise={"doing": "Idem.", "stopped_at": "Idem.", "open": "Rien : la PR est mergée."}
        ),
        model_id="fake/summarizer",
    )
    assert summarize_session(view, client=client, summarizer=v1, config=Config(model_id="fake/summarizer", prompt_version="v1"), state=state, now=at(0)).status == "created"
    assert summarize_session(view, client=client, summarizer=v2, config=Config(model_id="fake/summarizer", prompt_version="v2"), state=state, now=at(10)).status == "created"

    last = cli.main([*base_args(fake_core, tmp_path), "show", "aaaa"])
    last_out = capsys.readouterr().out
    everything = cli.main([*base_args(fake_core, tmp_path), "show", "aaaa", "--all"])
    all_out = capsys.readouterr().out
    as_json = cli.main([*base_args(fake_core, tmp_path), "show", "aaaa", "--all", "--json"])
    events = json.loads(capsys.readouterr().out)

    assert last == 0 and card_lines(last_out)["open"] == "Rien : la PR est mergée."
    assert last_out.count("session         aaaaaaaaaaaaaaaa") == 1
    assert everything == 0 and all_out.startswith("2 résumé(s) pour aaaaaaaaaaaaaaaa")
    assert all_out.count("session         aaaaaaaaaaaaaaaa") == 2
    assert all_out.index("résumé          v1 ") < all_out.index("résumé          v2 ")
    assert as_json == 0 and [e["details"]["prompt_version"] for e in events] == ["v1", "v2"]


def test_cli_show_core_fallback_uses_the_card_and_cannot_know_the_annex(fake_core, tmp_path, capsys):
    fake_core.default_context = context_view(reference_at=REFERENCE, last_session_summary=latest_summary())

    code = cli.main([*base_args(fake_core, tmp_path), "show", "aaaa"])
    card = card_lines(capsys.readouterr().out)

    assert code == 0
    assert card["session"].startswith("aaaaaaaaaaaaaaaa  work-1  —–")
    assert card["résumé"].startswith("—  —")
    assert card["confidence"] == "high"
    assert card["open"] == "La PR attend ta relecture."
    assert card["↳ reçu"].startswith("(annexe previous_summary inconnue")
    assert card["central_files"] == "—"
