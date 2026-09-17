"""`make status` doit dire STALE pour un service launchd qui exécute une
autre version que celle du checkout : du 2026-09-06 au 11, quatre services
ont tourné sur du code antérieur au schéma 3 sans qu'aucun affichage le
montre. Depuis la 0.8.9.0 la comparaison porte sur les versions, plus sur
l'heure de démarrage contre la date du dernier commit."""

from __future__ import annotations

import os

from daemon_v2.service_staleness import main, service_suffix, staleness_suffix
from daemon_v2.version import UNKNOWN_VERSION, announce


def test_a_service_running_the_checkout_version_is_not_stale():
    assert staleness_suffix("0.8.9.0", "0.8.9.0") == " — version 0.8.9.0"


def test_a_service_running_another_version_is_stale_and_says_both():
    suffix = staleness_suffix("0.8.8.0", "0.8.9.0")

    assert "STALE" in suffix
    assert "exécute 0.8.8.0" in suffix and "checkout en 0.8.9.0" in suffix


def test_a_service_that_announces_nothing_is_stale():
    # Démarré avant la 0.8.9.0 : il exécute forcément un code plus ancien.
    assert "STALE : version non annoncée" in staleness_suffix(None, "0.8.9.0")
    assert "STALE : version non annoncée" in staleness_suffix("", "0.8.9.0")


def test_a_service_whose_version_file_was_missing_is_stale():
    assert "STALE : exécute unknown" in staleness_suffix(UNKNOWN_VERSION, "0.8.9.0")


def test_an_unreadable_checkout_version_is_not_a_verdict():
    suffix = staleness_suffix("0.8.9.0", UNKNOWN_VERSION)

    assert "STALE" not in suffix
    assert "non comparée" in suffix


def test_the_daemon_is_judged_on_the_version_it_serves():
    assert service_suffix(
        "com.pulse.daemon", 1, served="0.8.9.0", checkout="0.8.9.0"
    ) == " — version 0.8.9.0"
    assert "STALE" in service_suffix(
        "com.pulse.daemon", 1, served=None, checkout="0.8.9.0"
    )


def test_worker_and_watcher_are_judged_on_the_version_they_announced(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("daemon_v2.version.announce_directory", lambda: tmp_path)
    monkeypatch.setattr("daemon_v2.version.CORE_VERSION", "0.8.8.0")
    announce("outbox-worker")

    mine = service_suffix("com.pulse.outbox-worker", os.getpid(), checkout="0.8.9.0")
    # Une annonce laissée par un processus précédent ne vaut pas pour ce pid.
    other = service_suffix("com.pulse.outbox-worker", os.getpid() + 1, checkout="0.8.9.0")
    watcher = service_suffix("com.pulse.file-watcher", os.getpid(), checkout="0.8.9.0")

    assert "exécute 0.8.8.0" in mine
    assert "version non annoncée" in other
    assert "version non annoncée" in watcher


def test_the_swift_observer_is_never_called_stale():
    suffix = service_suffix("com.pulse.app-observer", 1, checkout="0.8.9.0")

    assert "STALE" not in suffix
    assert "non comparé" in suffix


def test_a_periodic_service_gets_no_suffix():
    assert service_suffix("com.pulse.agent-producers", 1, checkout="0.8.9.0") == ""


def test_the_cli_prints_the_suffix_status_sh_appends(capsys):
    assert main(["com.pulse.daemon", "42", ""]) == 0
    assert "version non annoncée" in capsys.readouterr().out
    assert main(["com.pulse.daemon"]) == 2
