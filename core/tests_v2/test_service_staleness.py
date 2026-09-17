"""`make status` doit dire qu'un service launchd n'exécute pas le code du
checkout : du 2026-09-06 au 11, quatre services ont tourné sur du code
antérieur au schéma 3 sans qu'aucun affichage le montre. Trois états : à
jour, STALE, INCONNU. L'empreinte du code décide, la version se lit."""

from __future__ import annotations

import json
import os

from daemon_v2.service_staleness import (
    STALE,
    UNKNOWN,
    UP_TO_DATE,
    main,
    observer_record_path,
    observer_verdict,
    python_service_verdict,
    record_observer,
    service_suffix,
)
from daemon_v2.version import CODE_FINGERPRINT, CORE_VERSION, announce

CHECKOUT = {"checkout_version": "0.8.9.0", "checkout_fingerprint": "aaaaaaaaaaaa"}


def test_same_code_is_up_to_date_and_shows_the_version():
    verdict = python_service_verdict("0.8.9.0", "aaaaaaaaaaaa", **CHECKOUT)

    assert verdict.state == UP_TO_DATE
    assert "version 0.8.9.0" in verdict.detail
    assert verdict.suffix().startswith(" — à jour : ")


def test_another_version_is_stale_and_says_both():
    verdict = python_service_verdict("0.8.8.0", "bbbbbbbbbbbb", **CHECKOUT)

    assert verdict.state == STALE
    assert "exécute 0.8.8.0" in verdict.detail and "checkout en 0.8.9.0" in verdict.detail


def test_a_merge_without_a_bump_is_still_stale():
    verdict = python_service_verdict("0.8.9.0", "bbbbbbbbbbbb", **CHECKOUT)

    assert verdict.state == STALE
    assert "changement sans bump" in verdict.detail


def test_a_service_that_announces_no_fingerprint_is_unknown_not_stale():
    for version in (None, "", "0.8.9.0"):
        verdict = python_service_verdict(version, None, **CHECKOUT)
        assert verdict.state == UNKNOWN
        assert "STALE" not in verdict.suffix()


def test_an_unreadable_checkout_is_unknown():
    verdict = python_service_verdict(
        "0.8.9.0", "aaaaaaaaaaaa", checkout_version="unknown", checkout_fingerprint=None
    )

    assert verdict.state == UNKNOWN


def test_the_daemon_is_judged_on_what_it_serves():
    up_to_date = service_suffix(
        "com.pulse.daemon", 1,
        served_version=CORE_VERSION, served_fingerprint=CODE_FINGERPRINT,
    )
    other_code = service_suffix(
        "com.pulse.daemon", 1,
        served_version=CORE_VERSION, served_fingerprint="bbbbbbbbbbbb",
    )

    assert up_to_date.startswith(" — à jour")
    assert other_code.startswith(" — STALE") and "sans bump" in other_code
    assert service_suffix("com.pulse.daemon", 1).startswith(" — INCONNU")


def test_worker_and_watcher_are_judged_on_what_they_announced(tmp_path, monkeypatch):
    monkeypatch.setattr("daemon_v2.version.announce_directory", lambda: tmp_path)
    announce("outbox-worker")

    mine = service_suffix("com.pulse.outbox-worker", os.getpid())
    # Une annonce laissée par un processus précédent ne vaut pas pour ce pid.
    other_pid = service_suffix("com.pulse.outbox-worker", os.getpid() + 1)
    silent = service_suffix("com.pulse.file-watcher", os.getpid())

    assert mine.startswith(" — à jour")
    assert other_pid.startswith(" — INCONNU")
    assert silent.startswith(" — INCONNU")


def test_a_periodic_service_gets_no_suffix():
    assert service_suffix("com.pulse.agent-producers", 1) == ""


def _observer(tmp_path):
    root = tmp_path / "macos_observer"
    (root / "Sources").mkdir(parents=True)
    (root / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (root / "Sources" / "main.swift").write_text("print(1)\n")
    binary = tmp_path / "bin" / "PulseApplicationObserver"
    binary.parent.mkdir()
    binary.write_bytes(b"\xcf\xfa\xed\xfe binaire")
    return root, binary


def test_the_observer_is_compared_through_the_sources_recorded_at_install(tmp_path):
    root, binary = _observer(tmp_path)

    assert observer_verdict(binary, observer_root=root).state == UNKNOWN
    assert record_observer(binary, observer_root=root)
    assert observer_verdict(binary, observer_root=root).state == UP_TO_DATE
    assert set(json.loads(observer_record_path(binary).read_text())) == {
        "source_fingerprint", "binary_sha256",
    }

    (root / "Sources" / "main.swift").write_text("print(2)\n")
    stale = observer_verdict(binary, observer_root=root)
    assert stale.state == STALE
    # Une relance ne recharge pas un binaire copié : le remède est différent.
    assert "réinstaller" in stale.detail


def test_an_observer_binary_replaced_by_hand_is_unknown(tmp_path):
    root, binary = _observer(tmp_path)
    record_observer(binary, observer_root=root)
    binary.write_bytes(b"autre binaire")

    assert observer_verdict(binary, observer_root=root).state == UNKNOWN


def test_recording_a_missing_binary_fails_without_writing(tmp_path):
    root, binary = _observer(tmp_path)
    binary.unlink()

    assert not record_observer(binary, observer_root=root)
    assert not observer_record_path(binary).exists()


def test_the_cli_prints_the_state_first_then_the_detail(capsys):
    # status.sh place l'état en tête de ligne : « INCONNU » ne doit jamais se
    # lire comme « à jour », ni se cacher derrière le « running » de launchd.
    assert main(["com.pulse.daemon", "42", "", ""]) == 0
    state, detail = capsys.readouterr().out.rstrip("\n").split("\t")
    assert state == "INCONNU" and "à jour" not in detail

    assert main(["com.pulse.daemon", "42", CORE_VERSION, CODE_FINGERPRINT]) == 0
    assert capsys.readouterr().out.startswith("à jour\t")

    assert main(["com.pulse.agent-producers", "42"]) == 0
    assert capsys.readouterr().out == "\n"
    assert main(["com.pulse.daemon"]) == 2
    assert main(["--record-observer"]) == 2


def test_the_three_states_cannot_be_mistaken_for_one_another():
    assert {UP_TO_DATE, STALE, UNKNOWN} == {"à jour", "STALE", "INCONNU"}
    for verdict in (
        python_service_verdict(None, None, **CHECKOUT),
        python_service_verdict("0.8.9.0", None, **CHECKOUT),
    ):
        assert "à jour" not in verdict.columns()
