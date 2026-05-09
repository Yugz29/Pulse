import sys
from types import SimpleNamespace
from unittest.mock import patch

from daemon.core.event_bus import EventBus
from daemon.platform.idle_heartbeat import IdlePresenceHeartbeat
from daemon.platform.idle_probe import get_user_idle_seconds
from daemon.platform.macos_iokit_idle import get_macos_user_idle_seconds
from daemon.runtime_state import RuntimeState


def test_idle_probe_fallback_linux_ne_leve_pas_et_retourne_none():
    sys.modules.pop("daemon.platform.macos_iokit_idle", None)
    with patch.object(sys, "platform", "linux"):
        assert get_user_idle_seconds() is None


def test_macos_iokit_idle_parse_hid_idle_time_en_secondes():
    result = SimpleNamespace(returncode=0, stdout='    "HIDIdleTime" = 420000000000\n')
    with patch.object(sys, "platform", "darwin"), patch(
        "daemon.platform.macos_iokit_idle.subprocess.run",
        return_value=result,
    ):
        assert get_macos_user_idle_seconds() == 420


def test_idle_heartbeat_probe_none_ne_publie_rien():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(bus=bus, probe=lambda: None)

    assert heartbeat.tick_once() is False
    assert bus.recent() == []


def test_idle_heartbeat_publie_active_quand_idle_seconds_bas():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(bus=bus, probe=lambda: 10, idle_threshold_sec=300)

    assert heartbeat.tick_once() is True
    event = bus.recent(1)[0]
    assert event.type == "user_presence"
    assert event.payload == {
        "presence_state": "active",
        "idle_seconds": 10,
        "source": "iokit",
    }


def test_idle_heartbeat_publie_active_quand_runtime_non_locke():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(
        bus=bus,
        probe=lambda: 10,
        idle_threshold_sec=300,
        is_locked=lambda: False,
    )

    assert heartbeat.tick_once() is True
    assert bus.recent(1)[0].payload["presence_state"] == "active"


def test_idle_heartbeat_publie_idle_quand_idle_seconds_depasse_seuil():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(bus=bus, probe=lambda: 420, idle_threshold_sec=300)

    assert heartbeat.tick_once() is True
    event = bus.recent(1)[0]
    assert event.type == "user_presence"
    assert event.payload == {
        "presence_state": "idle",
        "idle_seconds": 420,
        "source": "iokit",
    }


def test_idle_heartbeat_ne_publie_pas_active_quand_runtime_locke():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(
        bus=bus,
        probe=lambda: 10,
        idle_threshold_sec=300,
        is_locked=lambda: True,
    )

    assert heartbeat.tick_once() is False
    assert bus.recent() == []


def test_idle_heartbeat_ne_publie_pas_idle_quand_runtime_locke():
    bus = EventBus()
    heartbeat = IdlePresenceHeartbeat(
        bus=bus,
        probe=lambda: 420,
        idle_threshold_sec=300,
        is_locked=lambda: True,
    )

    assert heartbeat.tick_once() is False
    assert bus.recent() == []


def test_idle_heartbeat_ne_publie_pas_si_lock_callback_echoue():
    bus = EventBus()

    def broken_lock_state():
        raise RuntimeError("lock unavailable")

    heartbeat = IdlePresenceHeartbeat(
        bus=bus,
        probe=lambda: 10,
        idle_threshold_sec=300,
        is_locked=broken_lock_state,
    )

    assert heartbeat.tick_once() is False
    assert bus.recent() == []


def test_runtime_state_expose_user_idle_seconds_et_source():
    state = RuntimeState()
    state.update_presence(
        presence_state="idle",
        idle_seconds=420,
        source="iokit",
    )
    present = state.update_present(
        signals=SimpleNamespace(),
        session_status="active",
        awake=True,
        locked=False,
    )

    assert present.user_presence_state == "idle"
    assert present.user_idle_seconds == 420
    assert present.user_presence_source == "iokit"
    assert state.get_present_snapshot()["user_idle_seconds"] == 420
