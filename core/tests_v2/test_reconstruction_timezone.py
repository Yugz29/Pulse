"""Fuseau de reconstruction explicite (audit 2026-09-06, défaut 7 ; décision
`docs/decisions/2026-09-06-fuseau-de-reconstruction.md`).

`datetime.now().astimezone().tzinfo` est un décalage fixe, celui du moment :
en été `+02:00`, appliqué à une journée de janvier il déplace 23 h locales
dans le jour suivant. La reconstruction lit désormais
`ZoneInfo(PULSE_RECONSTRUCTION_TZ)`, `Europe/Paris` par défaut, porteur des
règles calendaires, quelle que soit l'heure de la machine.
"""

import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from daemon_v2.context_snapshot import build_day_sessions
from daemon_v2.daily_trace import build_daily_trace
from daemon_v2.main import create_app
from daemon_v2.models import Activity
from daemon_v2.trace_store import TraceStore


PARIS = ZoneInfo("Europe/Paris")


def _reset_zone_cache() -> None:
    try:
        from daemon_v2.runtime_config import reconstruction_timezone
    except ImportError:
        return
    reconstruction_timezone.cache_clear()


@pytest.fixture
def machine_clock(monkeypatch):
    """Force le fuseau machine sur un décalage POSIX fixe, toute l'année,
    pour que le test soit reproductible en CI quelle que soit la saison :
    `XXX-2` vaut UTC+02:00 (heure d'été), `XXX-1` vaut UTC+01:00 (hiver)."""

    def force(posix_tz: str) -> None:
        monkeypatch.setenv("TZ", posix_tz)
        time.tzset()
        _reset_zone_cache()

    monkeypatch.delenv("PULSE_RECONSTRUCTION_TZ", raising=False)
    _reset_zone_cache()
    yield force
    monkeypatch.undo()
    time.tzset()
    _reset_zone_cache()


def _file_changed(occurred_at: datetime, index: int = 0) -> Activity:
    return Activity(
        "file_changed",
        occurred_at,
        "filesystem",
        f"Modified /project/Pulse/f{index}.py",
        {"path": f"/project/Pulse/f{index}.py", "event": "modified", "workspace": "/project/Pulse"},
    )


def _january_store(tmp_path) -> TraceStore:
    # Scénario de l'audit : deux événements le 1er janvier 2026 à 22:10 et
    # 22:20 UTC, soit 23:10 et 23:20 à Paris (hiver, +01:00).
    store = TraceStore(tmp_path / "trace.db")
    store.append(_file_changed(datetime(2026, 1, 1, 22, 10, tzinfo=timezone.utc), 1))
    store.append(_file_changed(datetime(2026, 1, 1, 22, 20, tzinfo=timezone.utc), 2))
    return store


SUMMER_NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
WINTER_NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def test_a_january_day_replayed_in_summer_keeps_its_late_session(tmp_path, machine_clock):
    """Aujourd'hui, avec la machine en heure d'été : 0 session le 1er janvier
    (le décalage fixe +02:00 pousse 22:10 UTC au 2 janvier). Attendu : 1."""
    machine_clock("XXX-2")
    store = _january_store(tmp_path)

    listed = build_day_sessions(store, day=date(2026, 1, 1), reference_at=SUMMER_NOW)
    trace = build_daily_trace(store, date(2026, 1, 1), now=SUMMER_NOW.astimezone(PARIS))

    assert len(listed["sessions"]) == 1
    assert listed["timezone"] == "Europe/Paris"
    assert trace["activity_count"] == 2
    assert trace["timezone"] == "Europe/Paris"
    assert build_daily_trace(store, date(2026, 1, 2), now=SUMMER_NOW.astimezone(PARIS))["activity_count"] == 0


def test_the_same_day_read_in_winter_and_in_summer_gives_the_same_sessions(tmp_path, machine_clock):
    store = _january_store(tmp_path)

    machine_clock("XXX-1")
    winter = build_day_sessions(store, day=date(2026, 1, 1), reference_at=WINTER_NOW)
    machine_clock("XXX-2")
    summer = build_day_sessions(store, day=date(2026, 1, 1), reference_at=SUMMER_NOW)

    assert [s["id"] for s in winter["sessions"]] == [s["id"] for s in summer["sessions"]]
    assert len(winter["sessions"]) == 1
    assert winter["timezone"] == summer["timezone"] == "Europe/Paris"
    assert winter["reconstruction_version"] == summer["reconstruction_version"] == 3


@pytest.mark.parametrize(
    ("first_local_day", "expected_hours"),
    [
        (date(2026, 3, 28), [24, 23, 24]),   # 29 mars : passage à l'heure d'été
        (date(2026, 10, 24), [24, 25, 24]),  # 25 octobre : retour à l'heure d'hiver
    ],
    ids=["mars-23h", "octobre-25h"],
)
def test_dst_days_have_23_or_25_hours_without_losing_or_duplicating_activity(
    tmp_path, machine_clock, first_local_day, expected_hours
):
    """Une activité par heure UTC sur trois journées locales consécutives :
    la journée de changement d'heure compte 23 ou 25 activités, les voisines
    24, et la somme vaut exactement le nombre d'activités insérées."""
    machine_clock("XXX-2")
    store = TraceStore(tmp_path / "trace.db")
    start = datetime.combine(first_local_day, datetime.min.time(), PARIS)
    end = datetime.combine(first_local_day + timedelta(days=3), datetime.min.time(), PARIS)
    inserted = 0
    moment = start.astimezone(timezone.utc)
    while moment < end:
        store.append(_file_changed(moment, inserted))
        inserted += 1
        moment += timedelta(hours=1)
    anchored = datetime.combine(first_local_day + timedelta(days=3), datetime.min.time(), PARIS)

    counts = [
        build_daily_trace(store, first_local_day + timedelta(days=offset), now=anchored)["activity_count"]
        for offset in range(3)
    ]

    assert counts == expected_hours
    assert sum(counts) == inserted == sum(expected_hours)


def test_an_invalid_reconstruction_timezone_fails_explicitly_at_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSE_RECONSTRUCTION_TZ", "Mars/Olympus")
    _reset_zone_cache()

    with pytest.raises(ValueError, match="PULSE_RECONSTRUCTION_TZ"):
        create_app(tmp_path / "trace.db")
    _reset_zone_cache()


def test_the_reconstruction_timezone_defaults_to_paris_and_honours_the_variable(monkeypatch):
    from daemon_v2.runtime_config import reconstruction_timezone

    monkeypatch.delenv("PULSE_RECONSTRUCTION_TZ", raising=False)
    reconstruction_timezone.cache_clear()
    assert reconstruction_timezone() == ZoneInfo("Europe/Paris")

    monkeypatch.setenv("PULSE_RECONSTRUCTION_TZ", "UTC")
    reconstruction_timezone.cache_clear()
    assert reconstruction_timezone() == ZoneInfo("UTC")
    reconstruction_timezone.cache_clear()
