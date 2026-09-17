"""Les worktrees liés d'un dépôt déclaré sont observés d'office, et rattachés à lui."""

import json
import shutil
from datetime import timezone

from daemon_v2.analysis.projects import persisted_workspace_identity
from daemon_v2.context_snapshot import build_context_snapshot
from daemon_v2.daily_trace import (
    build_daily_trace,
    render_daily_trace_html,
    render_daily_trace_markdown,
)
from daemon_v2.file_watcher import (
    WatchedWorkspace,
    DirtyPathCollector,
    event_workspace,
    flush_workspace,
    record_file_event,
    sync_worktrees,
    take_snapshot,
    worktree_is_gone,
    worktree_targets,
)
from daemon_v2.ingest import normalize_event
from daemon_v2.producer_outbox import ProducerOutbox, build_file_event_payload
from daemon_v2.trace_store import TraceStore
from daemon_v2.work_observations import project_work_observations
from tests_v2.test_context_snapshot import REFERENCE, at
from tests_v2.test_git_context import create_repository, git


class FakeObserver:
    def __init__(self):
        self.scheduled, self.unscheduled = [], []

    def schedule(self, collector, path):
        self.scheduled.append(path)
        return f"handle:{path}"

    def unschedule(self, handle):
        self.unscheduled.append(handle)


def repository_with_worktree(tmp_path, name="Pulse-live"):
    main = create_repository(tmp_path / "Pulse").resolve()
    worktree = (tmp_path / name).resolve()
    git("worktree", "add", "-b", name, str(worktree), cwd=main)
    return main, worktree


def declared(main):
    collector = DirtyPathCollector(main)
    return WatchedWorkspace(main, collector, take_snapshot(main))


def sync(watched, main, observer):
    return sync_worktrees(
        watched, [main], schedule=observer.schedule, unschedule=observer.unschedule
    )


# --- Quels worktrees ---------------------------------------------------------------


def test_worktrees_of_a_declared_repository_are_targets(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    inside = main / "wt" / "inside"
    git("worktree", "add", "-b", "inside", str(inside), cwd=main)

    targets = worktree_targets([main])

    # Celui qui vit sous le workspace déclaré est déjà observé par lui.
    assert targets == {worktree: main}
    assert worktree_targets([tmp_path / "pas-un-depot"]) == {}


def test_a_new_worktree_is_watched_from_a_silent_baseline(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    (worktree / "notes.md").write_text("déjà là")
    watched, observer = [declared(main)], FakeObserver()

    added, removed = sync(watched, main, observer)

    assert (added, removed) == ([worktree], [])
    assert observer.scheduled == [worktree]
    entry = watched[-1]
    assert entry.owner == main and entry.handle == f"handle:{worktree}"
    # Son contenu au moment de la découverte ne produit aucun événement.
    seen = []
    flush_workspace(entry, lambda event, path: seen.append((event, path)) or True)
    assert seen == []
    # Une seconde relecture ne l'ajoute pas deux fois.
    assert sync(watched, main, observer) == ([], [])


def test_a_change_in_a_worktree_is_attributed_to_the_main_repository(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    entry = watched[-1]
    edited = worktree / "README.md"
    edited.write_text("modifié dans le worktree, assez long pour changer de taille")
    entry.collector._mark(edited, directory=False)

    seen = []
    flush_workspace(entry, lambda event, path: seen.append((event, path)) or True)

    assert [path for _event, path in seen] == [edited]
    workspace = event_workspace(entry)
    assert workspace == {
        "project_name": "Pulse",
        "workspace_root": str(worktree),
        "git_root": str(worktree),
        "resolution_method": "git",
        "resolution_confidence": "high",
    }
    # Un workspace déclaré garde sa forme de toujours : son chemin.
    assert event_workspace(watched[0]) == main


def test_the_resolved_workspace_survives_outbox_ingestion_and_projection(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    outbox = ProducerOutbox(tmp_path / "outbox.db")

    assert record_file_event(outbox, "modified", worktree / "core" / "a.py", event_workspace(watched[-1]))
    payload = json.loads(
        build_file_event_payload(
            outbox, path=str(worktree / "core" / "a.py"), event="modified",
            workspace=event_workspace(watched[-1]), occurred_at=at(-10),
        )
    )
    ingested = normalize_event(payload)

    details = ingested.activity.details
    assert details["workspace"]["project_name"] == "Pulse"
    assert details["workspace"]["workspace_root"] == str(worktree)
    activity = {"id": 1, "event_id": "e1", "type": "file_changed", "occurred_at": at(-10).isoformat(), "details": details}
    identity = persisted_workspace_identity(activity)
    assert (identity.root, identity.project_name) == (str(worktree), "Pulse")
    fact = project_work_observations([activity])["timeline"][0]
    assert fact["path"] == "core/a.py" and fact["workspace"] == str(worktree)


def test_context_and_journal_render_a_worktree_file_event(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    outbox = ProducerOutbox(tmp_path / "outbox.db")
    store = TraceStore(tmp_path / "trace.db")
    for minutes, name in ((-20, "a.py"), (-12, "b.py"), (-5, "a.py")):
        payload = json.loads(
            build_file_event_payload(
                outbox, path=str(worktree / "core" / name), event="modified",
                workspace=event_workspace(watched[-1]), occurred_at=at(minutes),
            )
        )
        store.append_event(normalize_event(payload))

    snapshot = build_context_snapshot(store, reference_at=REFERENCE, local_timezone=timezone.utc)
    trace = build_daily_trace(store, REFERENCE.date(), timezone.utc, now=REFERENCE)
    html, markdown = render_daily_trace_html(trace), render_daily_trace_markdown(trace)

    assert snapshot["workspace"]["path"] == str(worktree)
    assert snapshot["workspace"]["project"] == "Pulse"
    assert "core/a.py" in html and "core/a.py" in markdown


# --- Quand le worktree s'en va -----------------------------------------------------


def test_a_removed_worktree_stops_being_watched_without_emitting_deletions(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    (worktree / "notes.md").write_text("x")
    git("add", "notes.md", cwd=worktree)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    entry = watched[-1]
    tracked = set(entry.snapshot)
    assert tracked
    git("worktree", "remove", "--force", str(worktree), cwd=main)
    entry.collector._mark(worktree, directory=True)  # ce que FSEvents signale

    assert worktree_is_gone(entry)
    added, removed = sync(watched, main, observer)

    assert (added, removed) == ([], [worktree])
    assert observer.unscheduled == [f"handle:{worktree}"]
    assert entry not in watched and [e.workspace for e in watched] == [main]
    # Sans ce retrait, le flush aurait émis une suppression par fichier suivi.
    seen = []
    flush_workspace(entry, lambda event, path: seen.append(event) or True)
    assert seen and set(seen) == {"deleted"} and len(seen) == len(tracked)


def test_a_worktree_directory_deleted_by_hand_is_retired_too(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    shutil.rmtree(worktree)  # sans `git worktree remove` : Git le dit « prunable »

    assert worktree_is_gone(watched[-1])
    assert sync(watched, main, observer) == ([], [worktree])


def test_a_failing_unschedule_does_not_keep_a_dead_worktree(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    watched, observer = [declared(main)], FakeObserver()
    sync(watched, main, observer)
    shutil.rmtree(worktree)

    def broken(_handle):
        raise KeyError("surveillance déjà morte")

    sync_worktrees(watched, [main], schedule=observer.schedule, unschedule=broken)

    assert [e.workspace for e in watched] == [main]


def test_a_declared_workspace_is_never_retired(tmp_path):
    plain = tmp_path / "sans-git"
    plain.mkdir()
    entry = declared(plain)

    assert not worktree_is_gone(entry)
    assert sync_worktrees([entry], [plain], schedule=lambda *_: None, unschedule=lambda _h: None) == ([], [])


# --- Bruit ---------------------------------------------------------------------------


def test_virtualenvs_and_caches_of_a_worktree_are_not_observed(tmp_path):
    main, worktree = repository_with_worktree(tmp_path)
    for relative in ("core/.venv/lib/x.py", "core/.pytest_cache/v", "core/daemon_v2/__pycache__/m.pyc"):
        target = worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    other = worktree / "intelligence" / "env-nommé-autrement"
    (other / "lib").mkdir(parents=True)
    (other / "pyvenv.cfg").write_text("home = /usr/bin\\n")
    (other / "lib" / "site.py").write_text("x")
    watched, observer = [declared(main)], FakeObserver()

    sync(watched, main, observer)

    paths = {str(path.relative_to(worktree)) for path in watched[-1].snapshot}
    assert not any(".venv" in p or "pyvenv" in p or "env-nommé" in p or "__pycache__" in p or ".pytest_cache" in p for p in paths)
    # Le fichier .git du worktree n'est pas un fichier de travail.
    assert ".git" not in paths
