"""La version de reconstruction servie par Core face à celle connue du code :
annoncée au démarrage (premier `/context/sessions`) et dans l'export d'`eval`."""

from __future__ import annotations

import json

from conftest import REFERENCE, session_view
from pulse_intelligence import KNOWN_RECONSTRUCTION_VERSION, cli, selection
from pulse_intelligence.evaluation import evaluate, reconstruction_versions, load_corpus, DEFAULT_CORPUS
from pulse_intelligence.selection import check_reconstruction_version, fetch_sessions


def test_known_version_matches_core_code():
    """La constante suit `RECONSTRUCTION_VERSION` de Core (3 depuis le 2026-09-06)
    sans l'importer : lue dans la source, comme un lecteur le ferait."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "core" / "daemon_v2" / "analysis" / "timeline.py"
    if not source.exists():
        return
    line = next(l for l in source.read_text(encoding="utf-8").splitlines() if l.startswith("RECONSTRUCTION_VERSION ="))
    assert int(line.split("=")[1]) == KNOWN_RECONSTRUCTION_VERSION


def test_a_served_version_that_differs_is_announced_once_on_stderr(fake_core, client, capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_versions", set())
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))
    # Le faux Core sert la reconstruction 1 (conftest) : différente de la connue.
    assert KNOWN_RECONSTRUCTION_VERSION != 1

    fetch_sessions(client, REFERENCE.date(), at=REFERENCE)
    fetch_sessions(client, REFERENCE.date(), at=REFERENCE)

    err = capsys.readouterr().err
    assert err.count("⚠ Core sert la reconstruction de sessions v1") == 1
    assert f"validé sur v{KNOWN_RECONSTRUCTION_VERSION}" in err


def test_the_known_version_is_silent(capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_versions", set())
    assert check_reconstruction_version(KNOWN_RECONSTRUCTION_VERSION) is None
    assert capsys.readouterr().err == ""


def test_the_cli_announces_it_at_startup(fake_core, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_versions", set())
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))

    code = cli.main(["--core-url", fake_core.url, "--state", str(tmp_path / "state.json"), "list"])

    assert code == 0
    assert "⚠ Core sert la reconstruction de sessions v1" in capsys.readouterr().err


def test_eval_export_records_the_corpus_versions_and_warns_when_they_differ(tmp_path, capsys):
    from test_evaluation import StubProvider, _summarizer, _tiny_corpus

    corpus = _tiny_corpus(tmp_path)  # vue à reconstruction_version 1
    _, run_dir = evaluate(_summarizer(StubProvider()), provider_name="stub", corpus_dir=corpus, out_dir=tmp_path / "out")
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["known_reconstruction_version"] == KNOWN_RECONSTRUCTION_VERSION
    assert meta["corpus_reconstruction_versions"] == {"1": 1}

    config = tmp_path / "config.toml"
    config.write_text('llm_provider = "fake"\nmodel_id = "fake/eval"\n', encoding="utf-8")
    assert cli.main(["--config", str(config), "eval", "--corpus", str(corpus), "--out", str(tmp_path / "out2")]) == 0
    assert "⚠ corpus figé sous la reconstruction v1 (1)" in capsys.readouterr().err


def test_the_frozen_corpus_was_captured_under_reconstruction_2():
    """Fait, pas défaut : les 14 entrées datent d'avant la v3 de Core ; `eval`
    l'annonce à chaque passage tant que le corpus n'est pas recapturé."""
    assert reconstruction_versions(load_corpus(DEFAULT_CORPUS)) == {"2": 14}
