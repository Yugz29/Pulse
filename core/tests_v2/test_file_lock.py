import threading
import time

import pytest

from daemon_v2.file_lock import LockTimeout, exclusive_lock


def test_second_holder_waits_then_enters(tmp_path):
    lock_path = tmp_path / "locks" / ".lock"
    order = []
    released = threading.Event()

    def first():
        with exclusive_lock(lock_path):
            order.append("first-in")
            released.wait(timeout=5)
            order.append("first-out")

    def second():
        time.sleep(0.1)
        with exclusive_lock(lock_path, timeout_s=5):
            order.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)
    assert order == ["first-in"]  # le second attend
    released.set()
    for thread in threads:
        thread.join(timeout=5)

    assert order == ["first-in", "first-out", "second-in"]
    assert lock_path.parent.exists()


def test_timeout_is_a_clean_error(tmp_path):
    lock_path = tmp_path / ".lock"
    with exclusive_lock(lock_path):
        with pytest.raises(LockTimeout):
            with exclusive_lock(lock_path, timeout_s=0.2):
                pass
