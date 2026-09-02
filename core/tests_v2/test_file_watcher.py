from watchdog.events import (
    DirDeletedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from daemon_v2.file_watcher import (
    DirtyPathCollector,
    resolve_dirty_paths,
    should_ignore,
    should_ignore_directory,
    take_snapshot,
)


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


def test_should_ignore_directory_covers_ignored_names_and_outside_paths(tmp_path):
    workspace = tmp_path
    assert should_ignore_directory(workspace / ".git", workspace)
    assert should_ignore_directory(workspace / ".git" / "objects", workspace)
    assert should_ignore_directory(workspace / "a" / "node_modules", workspace)
    assert should_ignore_directory(workspace.parent / "elsewhere", workspace)
    assert not should_ignore_directory(workspace / "daemon_v2", workspace)


def test_collector_marks_dirty_paths_without_trusting_event_kinds(tmp_path):
    workspace = tmp_path
    collector = DirtyPathCollector(workspace)
    created = workspace / "a.py"
    modified = workspace / "b.py"
    deleted = workspace / "c.py"
    moved_src = workspace / "old.py"
    moved_dest = workspace / "new.py"
    touched_dir = workspace / "daemon_v2"

    collector.dispatch(FileCreatedEvent(str(created)))
    collector.dispatch(FileModifiedEvent(str(modified)))
    collector.dispatch(FileDeletedEvent(str(deleted)))
    collector.dispatch(FileMovedEvent(str(moved_src), str(moved_dest)))
    collector.dispatch(DirDeletedEvent(str(touched_dir)))

    files, directories = collector.drain()
    assert files == {created, modified, deleted, moved_src, moved_dest}
    assert directories == {touched_dir}
    # Le drain vide le collecteur : la fenêtre suivante repart de zéro.
    assert collector.drain() == (set(), set())


def test_collector_filters_ignored_paths_at_the_source(tmp_path):
    workspace = tmp_path
    collector = DirtyPathCollector(workspace)

    collector.dispatch(FileModifiedEvent(str(workspace / ".git" / "index")))
    collector.dispatch(FileCreatedEvent(str(workspace / ".DS_Store")))
    collector.dispatch(FileModifiedEvent(str(workspace / "trace.db")))
    collector.dispatch(DirModifiedEvent(str(workspace / ".git")))
    collector.dispatch(DirModifiedEvent(str(workspace / "node_modules" / "pkg")))
    collector.dispatch(FileModifiedEvent(str(workspace.parent / "outside.py")))

    assert collector.drain() == (set(), set())


def test_resolve_reports_created_modified_and_deleted(tmp_path):
    workspace = tmp_path
    created = workspace / "created.py"
    modified = workspace / "modified.py"
    deleted = workspace / "deleted.py"
    created.write_text("new")
    modified.write_text("longer content")
    snapshot = {
        modified: (1, 1),
        deleted: (1, 1),
    }

    events = resolve_dirty_paths(
        snapshot, {created, modified, deleted}, set(), workspace
    )

    assert events == [
        ("created", created),
        ("modified", modified),
        ("deleted", deleted),
    ]
    assert set(snapshot) == {created, modified}
    assert snapshot[modified] != (1, 1)


def test_resolve_ignores_spurious_notifications(tmp_path):
    # FSEvents sur-signale (lectures, événements coalescés) : un chemin sale
    # dont la signature n'a pas bougé ne produit aucun événement.
    workspace = tmp_path
    steady = workspace / "steady.py"
    steady.write_text("same")
    snapshot = take_snapshot(workspace)

    events = resolve_dirty_paths(snapshot, {steady}, set(), workspace)

    assert events == []
    assert set(snapshot) == {steady}


def test_resolve_drops_deletion_of_unknown_path(tmp_path):
    workspace = tmp_path
    never_seen = workspace / "ephemeral.py"

    events = resolve_dirty_paths({}, {never_seen}, set(), workspace)

    assert events == []


def test_resolve_atomic_save_reports_modified_not_created(tmp_path):
    # Save atomique d'un éditeur : temp créé puis renommé sur la cible.
    # watchdog verrait created(temp)+moved ; la vérité snapshot rend
    # « modified » pour la cible, rien pour le temp disparu.
    workspace = tmp_path
    target = workspace / "document.py"
    target.write_text("version 2")
    temp = workspace / "document.py.tmp1234"
    snapshot = {target: (1, 1)}

    events = resolve_dirty_paths(snapshot, {temp, target}, set(), workspace)

    assert events == [("modified", target)]
    assert set(snapshot) == {target}


def test_resolve_rename_reports_created_and_deleted_pair(tmp_path):
    # mv ou git mv d'un fichier suivi : watchdog marque src+dest sales,
    # la résolution rend created(dest) + deleted(src) dans la même fenêtre
    # — même sémantique que l'ancien poller, le vocabulaire canonique n'a
    # pas de kind « renamed ». Vérifié en réel sur FSEvents le 2026-08-31.
    workspace = tmp_path
    source = workspace / "before.py"
    destination = workspace / "after.py"
    destination.write_text("same content")
    snapshot = {source: (1, 1)}

    events = resolve_dirty_paths(snapshot, {source, destination}, set(), workspace)

    assert events == [
        ("created", destination),
        ("deleted", source),
    ]
    assert set(snapshot) == {destination}


def test_resolve_expands_deleted_directory_to_known_children(tmp_path):
    # FSEvents peut coalescer la suppression d'un arbre en un seul événement
    # répertoire : les enfants connus du snapshot doivent sortir en deleted.
    workspace = tmp_path
    removed_dir = workspace / "feature"
    child_a = removed_dir / "a.py"
    child_b = removed_dir / "nested" / "b.py"
    survivor = workspace / "keep.py"
    survivor.write_text("keep")
    snapshot = {
        child_a: (1, 1),
        child_b: (1, 1),
        survivor: (1, 4),
    }

    events = resolve_dirty_paths(snapshot, set(), {removed_dir}, workspace)

    assert events == [
        ("deleted", child_a),
        ("deleted", child_b),
    ]
    assert set(snapshot) == {survivor}


def test_resolve_scans_directory_moved_in_with_contents(tmp_path):
    # Un répertoire déposé d'un bloc (mv depuis l'extérieur) peut n'émettre
    # qu'un événement répertoire : le re-scan borné découvre ses fichiers.
    workspace = tmp_path
    arrived = workspace / "imported"
    inner = arrived / "module.py"
    ignored = arrived / "__pycache__" / "module.pyc"
    inner.parent.mkdir(parents=True)
    inner.write_text("content")
    ignored.parent.mkdir(parents=True)
    ignored.write_text("cache")
    snapshot = {}

    events = resolve_dirty_paths(snapshot, set(), {arrived}, workspace)

    assert events == [("created", inner)]
    assert set(snapshot) == {inner}


def test_resolve_never_reports_a_directory_as_a_file(tmp_path):
    workspace = tmp_path
    directory = workspace / "daemon_v2"
    directory.mkdir()

    events = resolve_dirty_paths({}, {directory}, set(), workspace)

    assert events == []


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


def test_read_watched_workspaces_parses_comments_tilde_and_duplicates(tmp_path, monkeypatch):
    from daemon_v2.file_watcher import read_watched_workspaces

    monkeypatch.setenv("HOME", str(tmp_path))
    first = tmp_path / "Projets" / "alpha"
    second = tmp_path / "beta"
    first.mkdir(parents=True)
    second.mkdir()
    config = tmp_path / "watched"
    config.write_text(
        "# workspaces observés\n"
        "~/Projets/alpha\n"
        f"{second}\n"
        "\n"
        f"{first}\n",  # doublon (via ~) : gardé une seule fois
        encoding="utf-8",
    )

    workspaces, warnings = read_watched_workspaces(config)

    assert workspaces == [first.resolve(), second.resolve()]
    assert warnings == []


def test_read_watched_workspaces_skips_missing_entries_with_warning(tmp_path):
    from daemon_v2.file_watcher import read_watched_workspaces

    alive = tmp_path / "alive"
    alive.mkdir()
    config = tmp_path / "watched"
    config.write_text(f"{tmp_path / 'gone'}\n{alive}\n", encoding="utf-8")

    workspaces, warnings = read_watched_workspaces(config)

    # Un workspace supprimé n'aveugle pas le service pour les autres.
    assert workspaces == [alive.resolve()]
    assert len(warnings) == 1 and "gone" in warnings[0]


def test_read_watched_workspaces_missing_file_is_an_error(tmp_path):
    import pytest

    from daemon_v2.file_watcher import read_watched_workspaces

    with pytest.raises(ValueError):
        read_watched_workspaces(tmp_path / "absent")
