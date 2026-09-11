"""`make status` doit dire STALE pour un service launchd démarré avant le
dernier commit touchant core/ : du 2026-09-06 au 11, quatre services ont
tourné sur du code antérieur au schéma 3 sans qu'aucun affichage le montre."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daemon_v2.service_staleness import elapsed_seconds, is_stale, started_at


@pytest.mark.parametrize(
    "etime, seconds",
    [
        ("14:42", 14 * 60 + 42),
        ("1:02:03", 3600 + 2 * 60 + 3),
        ("04-21:06:23", 4 * 86400 + 21 * 3600 + 6 * 60 + 23),
        ("  00:07\n", 7),
    ],
)
def test_ps_etime_is_parsed_in_all_its_forms(etime, seconds):
    assert elapsed_seconds(etime) == seconds


def test_started_at_is_now_minus_elapsed():
    now = datetime(2026, 9, 11, 20, 48, 19, tzinfo=timezone.utc)
    assert started_at("14:42", now=now) == now - timedelta(minutes=14, seconds=42)


def test_a_service_started_before_the_last_core_commit_is_stale():
    code_changed = datetime(2026, 9, 9, 0, 35, 41, tzinfo=timezone.utc)
    started_06 = datetime(2026, 9, 6, 23, 56, 37, tzinfo=timezone.utc)
    started_11 = datetime(2026, 9, 11, 20, 48, 19, tzinfo=timezone.utc)
    assert is_stale(started_06, code_changed_at=code_changed)
    assert not is_stale(started_11, code_changed_at=code_changed)
    # Démarré dans la même seconde que le commit : pas périmé.
    assert not is_stale(code_changed, code_changed_at=code_changed)
