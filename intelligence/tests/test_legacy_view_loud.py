"""Un Core qui sert un schéma plus ancien que celui attendu (daemon jamais
redémarré après un merge, 2026-09-06 → 11) rend la vue héritée sans
`observations` : Intelligence replie sur `legacy_aggregates`, sans aucun
point `open` citable. Le repli reste possible ; il cesse d'être silencieux."""

from __future__ import annotations

from conftest import REFERENCE, session_view
from pulse_intelligence import cli, selection
from pulse_intelligence.core_client import EXPECTED_SCHEMA_VERSION
from pulse_intelligence.selection import fetch_sessions


def _base(fake_core, tmp_path) -> list[str]:
    return ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json")]


def test_a_served_schema_older_than_expected_is_announced_once_on_stderr(fake_core, client, capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_schemas", set(), raising=False)
    fake_core.schema_version = 2
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))

    fetch_sessions(client, REFERENCE.date(), at=REFERENCE)
    fetch_sessions(client, REFERENCE.date(), at=REFERENCE)

    err = capsys.readouterr().err
    assert err.count("⚠ Core sert le Context API schema_version 2") == 1
    assert f"attendu {EXPECTED_SCHEMA_VERSION}" in err
    assert "vue héritée" in err


def test_the_expected_schema_is_silent(fake_core, client, capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_schemas", set(), raising=False)
    monkeypatch.setattr(selection, "_announced_versions", {1})
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))

    fetch_sessions(client, REFERENCE.date(), at=REFERENCE)

    assert "schema_version" not in capsys.readouterr().err


def test_run_once_exits_with_the_legacy_view_code_and_still_summarizes(fake_core, tmp_path, fake_output_file, capsys, monkeypatch):
    monkeypatch.setattr(selection, "_announced_schemas", set(), raising=False)
    fake_core.schema_version = 2
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))

    code = cli.main([*_base(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)])

    assert code == cli.EXIT_LEGACY_VIEW == 6
    out, err = capsys.readouterr()
    assert "created=1" in out  # le repli reste possible
    assert "schema_version 2" in err and f"attendu {EXPECTED_SCHEMA_VERSION}" in err


def test_run_once_on_the_expected_schema_keeps_exit_zero(fake_core, tmp_path, fake_output_file, monkeypatch):
    monkeypatch.setattr(selection, "_announced_schemas", set(), raising=False)
    fake_core.add_sessions(REFERENCE.date().isoformat(), session_view("aaaaaaaaaaaaaaaa"))

    assert cli.main([*_base(fake_core, tmp_path), "run", "--once", "--fake", str(fake_output_file)]) == cli.EXIT_OK
