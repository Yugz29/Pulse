from daemon_v2.file_watcher import compare_snapshots, should_ignore, take_snapshot


def test_snapshot_ignores_technical_paths(tmp_path):
    workspace = tmp_path
    tracked = workspace / "daemon_v2" / "main.py"
    tracked.parent.mkdir()
    tracked.write_text("tracked")

    ignored_paths = [
        workspace / ".git" / "index",
        workspace / ".venv" / "state",
        workspace / ".build" / "debug.yaml",
        workspace / ".swiftpm" / "configuration",
        workspace / "__pycache__" / "main.pyc",
        workspace / ".pytest_cache" / "state",
        workspace / "node_modules" / "package" / "index.js",
        workspace / "dist" / "bundle.js",
        workspace / "build" / "generated.o",
        workspace / "trace.db",
        workspace / ".DS_Store",
    ]
    for path in ignored_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ignored")

    snapshot = take_snapshot(workspace)

    assert set(snapshot) == {tracked}
    assert all(should_ignore(path, workspace) for path in ignored_paths)


def test_macos_swift_build_artifacts_never_enter_snapshot(tmp_path):
    workspace = tmp_path
    artifact = (
        workspace
        / "macos_observer"
        / ".build"
        / "arm64-apple-macosx"
        / "debug"
        / "observer.o"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_text("artifact")

    assert should_ignore(artifact, workspace)
    assert artifact not in take_snapshot(workspace)


def test_compare_snapshots_reports_created_modified_and_deleted(tmp_path):
    created = tmp_path / "created.py"
    modified = tmp_path / "modified.py"
    deleted = tmp_path / "deleted.py"
    previous = {
        modified: (1, 10),
        deleted: (1, 10),
    }
    current = {
        created: (2, 20),
        modified: (2, 10),
    }

    assert compare_snapshots(previous, current) == [
        ("created", created),
        ("modified", modified),
        ("deleted", deleted),
    ]


def test_record_file_event_enqueues_canonical_event(tmp_path):
    from daemon_v2.file_watcher import record_file_event
    from daemon_v2.ingest import normalize_event
    from daemon_v2.producer_outbox import ProducerOutbox
    import json

    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")
    workspace = tmp_path / "repo"
    path = workspace / "daemon_v2" / "main.py"

    # Aucun daemon ne tourne : l'enqueue réussit quand même (décision
    # 2A-révisée — la durabilité vient de l'outbox, plus du POST direct).
    assert record_file_event(outbox, "modified", path, workspace) is True

    pending = outbox.oldest()
    assert pending is not None
    payload = json.loads(pending.payload_json)
    assert payload["type"] == "file_changed"
    assert payload["producer"]["name"] == "pulse-file-watcher"
    assert payload["details"] == {
        "path": str(path),
        "event": "modified",
        "workspace": str(workspace),
    }
    # Le payload enfilé est accepté tel quel par l'ingestion canonique.
    ingested = normalize_event(json.loads(pending.payload_json))
    assert ingested.activity.details["workspace"] == str(workspace)


def test_record_file_event_survives_storage_failure(tmp_path, monkeypatch):
    import sqlite3

    import daemon_v2.file_watcher as file_watcher_module
    from daemon_v2.file_watcher import record_file_event
    from daemon_v2.producer_outbox import ProducerOutbox

    outbox = ProducerOutbox(tmp_path / "outbox.sqlite3")

    def failing_enqueue(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(
        file_watcher_module, "enqueue_file_event", failing_enqueue
    )

    # Le watcher ne doit jamais crasher sur une erreur de stockage : il
    # signale l'échec et la boucle de polling continue.
    assert (
        record_file_event(outbox, "created", tmp_path / "a.py", tmp_path)
        is False
    )
