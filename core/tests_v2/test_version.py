"""La version que Core exécute : lue au démarrage, jamais une erreur."""

from __future__ import annotations

import json
import os
import stat

from daemon_v2.main import create_app
from daemon_v2.version import (
    CODE_FINGERPRINT,
    CORE_VERSION,
    UNKNOWN_VERSION,
    VERSION_FILE,
    announce,
    announced,
    read_version,
)


def test_the_version_comes_from_the_version_file_of_core():
    assert VERSION_FILE.name == "VERSION"
    assert VERSION_FILE.parent.name == "core"
    assert CORE_VERSION == VERSION_FILE.read_text().strip()


def test_a_missing_empty_or_unreadable_file_gives_unknown_never_an_error(tmp_path):
    empty = tmp_path / "EMPTY"
    empty.write_text("\n")
    binary = tmp_path / "BINARY"
    binary.write_bytes(b"\xff\xfe\x00")

    assert read_version(tmp_path / "ABSENT") == UNKNOWN_VERSION
    assert read_version(empty) == UNKNOWN_VERSION
    assert read_version(binary) == UNKNOWN_VERSION
    assert read_version(tmp_path) == UNKNOWN_VERSION


def test_status_serves_the_version_read_at_startup_not_the_file(tmp_path, monkeypatch):
    # Le checkout avance après le démarrage : le processus dit toujours la
    # version du code qu'il exécute.
    monkeypatch.setattr("daemon_v2.routes.CORE_VERSION", "0.8.8.0")
    moved = tmp_path / "VERSION"
    moved.write_text("version-du-checkout-apres-merge\n")
    monkeypatch.setattr("daemon_v2.version.VERSION_FILE", moved)
    client = create_app(tmp_path / "trace.db").test_client()

    status = client.get("/status").get_json()
    assert status["version"] == "0.8.8.0"
    assert status["code_fingerprint"] == CODE_FINGERPRINT
    assert (
        f"<dt>Version de Core</dt><dd>0.8.8.0 · code {CODE_FINGERPRINT}</dd>"
        in client.get("/").get_data(as_text=True)
    )


def test_the_version_stays_out_of_the_consumed_contracts(tmp_path):
    client = create_app(tmp_path / "trace.db").test_client()

    for url in ("/context", "/context/sessions", "/trace/today"):
        body = client.get(url).get_json()
        assert "version" not in body and "code_fingerprint" not in body, url
    assert CORE_VERSION not in json.dumps(client.get("/context").get_json())


def test_announce_writes_pid_and_version_in_a_private_file(tmp_path):
    announce("file-watcher", directory=tmp_path / "run")
    target = tmp_path / "run" / "file-watcher.json"

    assert json.loads(target.read_text()) == {
        "pid": os.getpid(),
        "version": CORE_VERSION,
        "code_fingerprint": CODE_FINGERPRINT,
    }
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert announced("file-watcher", os.getpid(), directory=tmp_path / "run") == {
        "version": CORE_VERSION,
        "code_fingerprint": CODE_FINGERPRINT,
    }
    assert announced("file-watcher", os.getpid() + 1, directory=tmp_path / "run") is None
    assert announced("outbox-worker", os.getpid(), directory=tmp_path / "run") is None


def test_announce_never_raises(tmp_path):
    blocker = tmp_path / "run"
    blocker.write_text("un fichier là où il faut un dossier")

    announce("outbox-worker", directory=blocker)

    assert announced("outbox-worker", os.getpid(), directory=blocker) is None


def test_a_corrupt_announce_reads_as_none(tmp_path):
    (tmp_path / "outbox-worker.json").write_text("{pas du json")

    assert announced("outbox-worker", os.getpid(), directory=tmp_path) is None
