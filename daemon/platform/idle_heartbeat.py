from __future__ import annotations

import threading
from collections.abc import Callable

from daemon.platform.idle_probe import get_user_idle_seconds


class IdlePresenceHeartbeat:
    """Optional heartbeat that publishes user_presence from an idle probe."""

    def __init__(
        self,
        *,
        bus,
        probe=get_user_idle_seconds,
        interval_sec: float = 30.0,
        idle_threshold_sec: int = 300,
        source: str = "iokit",
        is_locked: Callable[[], bool] | None = None,
    ) -> None:
        self.bus = bus
        self.probe = probe
        self.interval_sec = interval_sec
        self.idle_threshold_sec = idle_threshold_sec
        self.source = source
        self.is_locked = is_locked
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="pulse-idle-heartbeat",
            )
            self._thread.start()

    def stop(self, *, timeout: float = 1.0) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def tick_once(self) -> bool:
        if self._is_runtime_locked():
            return False
        idle_seconds = self.probe()
        if idle_seconds is None:
            return False
        try:
            idle_value = max(int(idle_seconds), 0)
        except (TypeError, ValueError):
            return False
        presence_state = "idle" if idle_value >= self.idle_threshold_sec else "active"
        self.bus.publish(
            "user_presence",
            {
                "presence_state": presence_state,
                "idle_seconds": idle_value,
                "source": self.source,
            },
        )
        return True

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_sec):
            self.tick_once()

    def _is_runtime_locked(self) -> bool:
        if self.is_locked is None:
            return False
        try:
            return bool(self.is_locked())
        except Exception:
            # Fail closed: a missing presence heartbeat is safer than a stale
            # active signal while the runtime may be screen-locked.
            return True


def create_idle_presence_heartbeat(
    bus,
    *,
    is_locked: Callable[[], bool] | None = None,
) -> IdlePresenceHeartbeat:
    return IdlePresenceHeartbeat(bus=bus, is_locked=is_locked)
