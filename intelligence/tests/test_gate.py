"""La garde du lot : un lot par jour, réveil complet, capot ouvert, batterie.

Le lot planifié de 06:30 partait dans un DarkWake de deux secondes, capot
fermé, et n'avançait que par tranches jusqu'au réveil complet : le 19,
4 h 33 d'horloge pour dix minutes de calcul. Ici : l'ordre des tests (lot
déjà fait, muet ; puis DarkWake ; puis capot ; puis batterie sous le
plancher), le début du cycle en heure locale, une ligne « lot reporté » par
cycle au plus, et les codes que le wrapper lit (décision 2026-09-19).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from pulse_intelligence import cli, gate
from pulse_intelligence.gate import (
    DEFERRED,
    DONE,
    GO,
    PowerState,
    cycle_threshold,
    decide,
    deferred_already_logged,
    parse_cycle_start,
    parse_ioreg,
    parse_pmset,
    parse_systemstate,
    record_deferred_logged,
)
from pulse_intelligence.state import JobState

PARIS = timezone(timedelta(hours=2))
FULL = ("CPU", "Graphics", "Audio", "Network")
DARK = ("CPU", "Network")
AC_OPEN = PowerState(on_ac=True, lid_closed=False, charge=68, capabilities=FULL)
BATTERY_OPEN = PowerState(on_ac=False, lid_closed=False, charge=85, capabilities=FULL)
BATTERY_LOW_OPEN = PowerState(on_ac=False, lid_closed=False, charge=39, capabilities=FULL)
BATTERY_CLOSED = PowerState(on_ac=False, lid_closed=True, charge=50, capabilities=FULL)
DARKWAKE_OPEN = PowerState(on_ac=False, lid_closed=False, charge=85, capabilities=DARK)


def _local(hour: int, minute: int = 0, day: int = 19) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=PARIS)


@pytest.fixture(autouse=True)
def _paris(monkeypatch):
    # Le seuil se calcule dans le fuseau du poste ; on le fixe pour comparer
    # des heures locales lisibles, comme le 19 à Paris.
    import os
    import time as time_module

    monkeypatch.setenv("TZ", "Europe/Paris")
    time_module.tzset()
    yield
    os.environ.pop("TZ", None)
    time_module.tzset()


def _state(tmp_path, marker: datetime | None) -> JobState:
    state = JobState.load(tmp_path / "state.json")
    if marker is not None:
        state.record_complete_pass(marker)
    return state


# --- le début du cycle, en heure locale ---------------------------------


def test_cycle_starts_today_once_the_hour_has_passed():
    assert cycle_threshold(_local(11, 9)) == _local(6, 30)


def test_cycle_started_yesterday_before_the_hour():
    assert cycle_threshold(_local(5, 0)) == _local(6, 30, day=18)


def test_cycle_threshold_compares_across_timezones():
    # 04:45 UTC le 19 = 06:45 à Paris : le cycle du 19 a commencé.
    now_utc = datetime(2026, 9, 19, 4, 45, tzinfo=timezone.utc)
    assert cycle_threshold(now_utc) == _local(6, 30)


def test_cycle_threshold_requires_an_aware_clock():
    with pytest.raises(ValueError):
        cycle_threshold(datetime(2026, 9, 19, 11, 0))


def test_parse_cycle_start_reads_the_hour():
    assert parse_cycle_start("07:00") == time(7, 0)
    with pytest.raises(ValueError):
        parse_cycle_start("7h")


# --- l'ordre des tests -------------------------------------------------


def test_done_today_wins_whatever_the_lid_and_battery(tmp_path):
    # Le lot de 06:45 a posé le repère (UTC) : les appels suivants du jour,
    # capot fermé ou batterie basse, ne relancent rien et n'écrivent rien.
    state = _state(tmp_path, datetime(2026, 9, 19, 4, 45, tzinfo=timezone.utc))

    assert decide(state, _local(15, 0), BATTERY_CLOSED) == gate.Verdict(DONE)


def test_yesterdays_pass_does_not_count_as_today(tmp_path):
    state = _state(tmp_path, _local(11, 9, day=18))

    assert decide(state, _local(6, 45), BATTERY_OPEN) == gate.Verdict(GO)


def test_a_late_pass_counts_for_the_whole_cycle(tmp_path):
    # Passage à 11:09 : fait pour le reste du 19, et encore le 20 à 05:00,
    # avant le début du cycle suivant.
    state = _state(tmp_path, _local(11, 9))

    assert decide(state, _local(18, 0), BATTERY_OPEN).outcome == DONE
    assert decide(state, _local(5, 0, day=20), BATTERY_OPEN).outcome == DONE


def test_darkwake_defers_before_the_lid_with_the_capabilities_read(tmp_path):
    # Veille d'inactivité capot ouvert : launchd tire l'appel dans un DarkWake,
    # capot ouvert, batterie haute. Sans Graphics, le lot ne part pas, et la
    # ligne montre ce qui a été lu pour vérifier le signal au premier cas réel.
    verdict = decide(_state(tmp_path, None), _local(6, 45), DARKWAKE_OPEN)

    assert verdict == gate.Verdict(DEFERRED, "pas en réveil complet (capacités lues : CPU Network)")


def test_darkwake_wins_over_a_closed_lid(tmp_path):
    power = PowerState(on_ac=False, lid_closed=True, charge=50, capabilities=DARK)

    assert decide(_state(tmp_path, None), _local(6, 45), power).reason.startswith("pas en réveil complet")


def test_unreadable_systemstate_does_not_defer(tmp_path):
    power = PowerState(on_ac=False, lid_closed=False, charge=85, capabilities=None)

    assert decide(_state(tmp_path, None), _local(6, 45), power) == gate.Verdict(GO)


def test_empty_capabilities_defer_and_say_so(tmp_path):
    power = PowerState(on_ac=False, lid_closed=False, charge=85, capabilities=())

    assert decide(_state(tmp_path, None), _local(6, 45), power).reason == "pas en réveil complet (capacités lues : aucune)"


def test_lid_closed_defers_first_even_on_ac(tmp_path):
    power = PowerState(on_ac=True, lid_closed=True, charge=100, capabilities=FULL)

    assert decide(_state(tmp_path, None), _local(6, 45), power) == gate.Verdict(DEFERRED, "capot fermé")


def test_battery_under_the_floor_defers_with_the_level(tmp_path):
    verdict = decide(_state(tmp_path, None), _local(6, 45), BATTERY_LOW_OPEN)

    assert verdict == gate.Verdict(DEFERRED, "sur batterie à 39 %, plancher 40 %")


def test_battery_at_the_floor_goes(tmp_path):
    power = PowerState(on_ac=False, lid_closed=False, charge=40, capabilities=FULL)

    assert decide(_state(tmp_path, None), _local(6, 45), power) == gate.Verdict(GO)


def test_battery_above_the_floor_goes_without_ac(tmp_path):
    assert decide(_state(tmp_path, None), _local(6, 45), BATTERY_OPEN) == gate.Verdict(GO)


def test_ac_goes_whatever_the_level(tmp_path):
    power = PowerState(on_ac=True, lid_closed=False, charge=5, capabilities=FULL)

    assert decide(_state(tmp_path, None), _local(6, 45), power) == gate.Verdict(GO)


def test_the_floor_is_a_parameter(tmp_path):
    assert decide(_state(tmp_path, None), _local(6, 45), BATTERY_OPEN, battery_floor=90).outcome == DEFERRED


def test_unreadable_sources_do_not_block_a_desktop(tmp_path):
    # Pas de batterie, pas de capot : rien à reporter.
    unknown = PowerState(on_ac=None, lid_closed=None, charge=None, capabilities=None)

    assert decide(_state(tmp_path, None), _local(11, 9), unknown) == gate.Verdict(GO)


# --- lecture des deux commandes système ----------------------------------


def test_parse_pmset_ac():
    text = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=7471203)\t68%; charging; 1:06 remaining present: true\n"
    assert parse_pmset(text) == (True, 68)


def test_parse_pmset_battery():
    text = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=7471203)\t50%; discharging; 4:10 remaining present: true\n"
    assert parse_pmset(text) == (False, 50)


def test_parse_pmset_unreadable():
    assert parse_pmset("") == (None, None)


def test_parse_systemstate_full_dark_absent():
    assert parse_systemstate("Current System Capabilities are: CPU Graphics Audio Network \nCurrent Power State: 4\n") == (
        "CPU", "Graphics", "Audio", "Network",
    )
    assert parse_systemstate("Current System Capabilities are: CPU Network\n") == ("CPU", "Network")
    assert parse_systemstate("") is None


def test_parse_ioreg_closed_open_absent():
    assert parse_ioreg('  |   "AppleClamshellState" = Yes\n') is True
    assert parse_ioreg('  |   "AppleClamshellState" = No\n') is False
    assert parse_ioreg("") is None


# --- une ligne « lot reporté » par cycle ---------------------------------


def test_deferred_log_is_remembered_within_the_cycle(tmp_path):
    path = tmp_path / "gate.json"
    threshold = _local(6, 30)

    assert not deferred_already_logged(path, threshold)
    record_deferred_logged(path, _local(6, 45))
    assert deferred_already_logged(path, threshold)
    assert not deferred_already_logged(path, _local(6, 30, day=20))
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_deferred_log_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "gate.json"
    path.write_text("{pas du json", encoding="utf-8")

    assert not deferred_already_logged(path, _local(6, 30))
    record_deferred_logged(path, _local(6, 45))
    assert deferred_already_logged(path, _local(6, 30))


# --- la sous-commande, telle que le wrapper la lit ----------------------


def _cli(monkeypatch, tmp_path, now: datetime, power: PowerState, marker: datetime | None):
    _state(tmp_path, marker)
    monkeypatch.setattr(cli, "_now", lambda: now)
    monkeypatch.setattr(cli, "read_power_state", lambda: power)
    return ["--state", str(tmp_path / "state.json"), "gate"]


def test_gate_done_is_silent(monkeypatch, tmp_path, capsys):
    args = _cli(monkeypatch, tmp_path, _local(15, 0), BATTERY_CLOSED, _local(6, 45))

    assert cli.main(args) == cli.EXIT_GATE_DONE
    assert capsys.readouterr() == ("", "")


def test_gate_deferred_writes_one_line_per_cycle(monkeypatch, tmp_path, capsys):
    args = _cli(monkeypatch, tmp_path, _local(6, 45), BATTERY_CLOSED, None)

    assert cli.main(args) == cli.EXIT_GATE_DEFERRED
    assert capsys.readouterr() == ("[2026-09-19 06:45:00] lot reporté : capot fermé\n", "")

    # Quinze minutes plus tard, même cycle, autre motif : reporté, muet.
    monkeypatch.setattr(cli, "_now", lambda: _local(7, 0))
    monkeypatch.setattr(cli, "read_power_state", lambda: BATTERY_LOW_OPEN)
    assert cli.main(args) == cli.EXIT_GATE_DEFERRED
    assert capsys.readouterr() == ("", "")

    # Le lendemain, nouveau cycle : une nouvelle ligne.
    monkeypatch.setattr(cli, "_now", lambda: _local(6, 45, day=20))
    assert cli.main(args) == cli.EXIT_GATE_DEFERRED
    assert capsys.readouterr().out == "[2026-09-20 06:45:00] lot reporté : sur batterie à 39 %, plancher 40 %\n"
    assert (tmp_path / "gate.json").exists()


def test_gate_go_is_silent_and_zero(monkeypatch, tmp_path, capsys):
    args = _cli(monkeypatch, tmp_path, _local(11, 9), BATTERY_OPEN, None)

    assert cli.main(args) == cli.EXIT_OK
    assert capsys.readouterr() == ("", "")


def test_gate_honours_the_cycle_start(monkeypatch, tmp_path):
    # Repère hier 13:00, maintenant 11:00. Cycle à 12:00 : le cycle en cours
    # a commencé hier à 12:00, le lot est fait. Cycle à 06:30 : le cycle a
    # commencé ce matin, rien n'est fait.
    args = _cli(monkeypatch, tmp_path, _local(11, 0), BATTERY_OPEN, _local(13, 0, day=18))

    assert cli.main([*args, "--cycle-start", "12:00"]) == cli.EXIT_GATE_DONE
    assert cli.main([*args, "--cycle-start", "06:30"]) == cli.EXIT_OK


def test_gate_rejects_a_malformed_hour(monkeypatch, tmp_path, capsys):
    args = _cli(monkeypatch, tmp_path, _local(11, 0), BATTERY_OPEN, None)

    assert cli.main([*args, "--cycle-start", "7h"]) == cli.EXIT_USAGE
    assert "HH:MM" in capsys.readouterr().err


def test_gate_takes_no_lock_and_needs_no_config(monkeypatch, tmp_path):
    # Un passage en cours tient le verrou ; la garde de l'appel suivant doit
    # répondre quand même (elle lit l'état sans verrou, et pas la config).
    args = _cli(monkeypatch, tmp_path, _local(11, 9), BATTERY_OPEN, None)
    held = JobState.load(tmp_path / "state.json", lock=True)
    try:
        assert cli.main(args) == cli.EXIT_OK
    finally:
        held.release()
