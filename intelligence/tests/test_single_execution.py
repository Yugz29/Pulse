"""Exécution unique d'un passage Intelligence (audit 2026-09-06, défaut 2).

Deux processus qui chargent le même `state.json` se réécrivent l'un l'autre :
`load` lit tout, `save` réécrit tout. Le verrou couvre le chargement et tout
le passage ; le second lancement sort tout de suite, sans rien perdre ni
générer deux fois.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from conftest import REFERENCE, session_view, valid_output
from pulse_intelligence import cli
from pulse_intelligence.state import JobState
from pulse_intelligence.summarizer import FakeSummarizer


def today() -> str:
    return REFERENCE.astimezone().date().isoformat()


def _emitted(state: JobState, event_id: str) -> None:
    state.record_emitted(
        event_id, session_id=event_id[:16].ljust(16, "0"), prompt_version="v1",
        model_id="fake/summarizer", at=REFERENCE.isoformat(),
    )


def test_a_second_loader_of_the_same_state_is_refused_and_nothing_is_lost(tmp_path):
    """Scénario de l'audit : deux JobState du même fichier, e1 puis e2.
    Sans verrou, seul e2 survit. Avec : le second chargement est refusé."""
    from pulse_intelligence.state import StateLocked

    path = tmp_path / "state" / "state.json"
    first = JobState.load(path, lock=True)
    _emitted(first, "e1")

    with pytest.raises(StateLocked):
        JobState.load(path, lock=True)

    assert set(JobState.load(path).emitted) == {"e1"}
    first.release()
    # Verrou rendu : le prochain passage charge normalement et voit e1.
    second = JobState.load(path, lock=True)
    _emitted(second, "e2")
    assert set(JobState.load(path).emitted) == {"e1", "e2"}


def test_reading_commands_do_not_take_the_lock(tmp_path):
    path = tmp_path / "state" / "state.json"
    held = JobState.load(path, lock=True)

    JobState.load(path)  # list / show : lecture seule, jamais bloquée

    held.release()


class _SlowSummarizer(FakeSummarizer):
    def summarize(self, model_input: str) -> str:
        time.sleep(0.6)
        return super().summarize(model_input)


def test_two_simultaneous_runs_generate_once_and_the_loser_exits_locked(
    fake_core, tmp_path, monkeypatch, capsys
):
    """Deux `run --once` en même temps sur le même état : un seul passe, un
    seul appel modèle, un seul POST ; l'autre sort immédiatement avec le code
    dédié. Threads : flock est par descripteur ouvert, donc valable ici aussi ;
    le scénario réel est inter-processus (wrapper launchd), voir la PR."""
    fake_core.add_sessions(today(), session_view("aaaaaaaaaaaaaaaa"))
    summarizer = _SlowSummarizer(outputs=valid_output(), model_id="fake/summarizer")
    monkeypatch.setattr(cli, "_summarizer", lambda args, config: summarizer)
    args = ["--core-url", fake_core.url, "--state", str(tmp_path / "state.json"),
            "run", "--once", "--fake", "unused"]
    codes: list[int] = []
    lock = threading.Lock()

    def launch():
        code = cli.main(args)
        with lock:
            codes.append(code)

    first = threading.Thread(target=launch)
    second = threading.Thread(target=launch)
    first.start()
    time.sleep(0.2)  # le premier tient déjà le verrou et génère
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert sorted(codes) == [cli.EXIT_OK, getattr(cli, "EXIT_LOCKED", 5)]
    assert len(summarizer.calls) == 1
    assert len(fake_core.posts) == 1
    assert "verrou" in capsys.readouterr().err
    assert set(JobState.load(tmp_path / "state.json").emitted)  # l'entrée du gagnant est là


def test_save_never_reuses_a_fixed_temporary_name(tmp_path, monkeypatch):
    """Deux sauvegardes réellement simultanées ne doivent pas se partager
    `state.json.tmp` : chaque save écrit sous un nom unique puis remplace."""
    import pulse_intelligence.state as state_module

    sources: list[str] = []
    real_replace = os.replace

    def recording_replace(src, dst):
        sources.append(os.fspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(state_module.os, "replace", recording_replace)
    path = tmp_path / "state" / "state.json"
    state = JobState.load(path)

    _emitted(state, "e1")
    _emitted(state, "e2")

    assert len(sources) == 2 and sources[0] != sources[1]
    assert str(path.with_suffix(".json.tmp")) not in sources
    assert set(JobState.load(path).emitted) == {"e1", "e2"}
