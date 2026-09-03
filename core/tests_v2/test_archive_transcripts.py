import json
import sys
from compression import zstd
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.archive_transcripts import (
    ArchiveInfrastructureError,
    archive_transcripts,
    main,
    source_slug,
)


# Ancre fixe à midi : timestamps d'archive déterministes.
NOW = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)


def make_source(tmp_path, name="claude", files=None):
    source = tmp_path / name
    for relative, content in (files or {"proj/session-1.jsonl": '{"a":1}\n'}).items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return source


def archived_file(archive_root, source, relative):
    return archive_root / source_slug(source) / (relative + ".zst")


def test_initial_run_archives_jsonl_mirror_with_manifest(tmp_path):
    source = make_source(
        tmp_path,
        files={
            "proj/session-1.jsonl": '{"role":"user"}\n{"role":"assistant"}\n',
            "proj/notes.txt": "pas un transcript",
        },
    )
    archive_root = tmp_path / "archive"

    report = archive_transcripts([source], archive_root, now=NOW)

    assert report.archived == 1
    assert report.unchanged == 0
    compressed = archived_file(archive_root, source, "proj/session-1.jsonl")
    assert compressed.exists()
    # Round-trip exact : l'archive restitue l'original octet pour octet.
    assert zstd.decompress(compressed.read_bytes()) == (
        source / "proj/session-1.jsonl"
    ).read_bytes()
    # Les fichiers non-.jsonl ne sont pas archivés.
    assert not archived_file(archive_root, source, "proj/notes.txt").exists()
    manifest = json.loads((archive_root / "manifest.json").read_text())
    key = f"{source_slug(source)}/proj/session-1.jsonl"
    assert manifest["files"][key]["archived_at"] == NOW.isoformat()
    assert manifest["files"][key]["size"] == (
        source / "proj/session-1.jsonl"
    ).stat().st_size


def test_second_run_is_idempotent(tmp_path):
    source = make_source(tmp_path)
    archive_root = tmp_path / "archive"
    archive_transcripts([source], archive_root, now=NOW)

    report = archive_transcripts([source], archive_root, now=NOW)

    assert report.archived == 0
    assert report.unchanged == 1


def test_grown_transcript_is_rearchived(tmp_path):
    source = make_source(tmp_path, files={"s.jsonl": '{"n":1}\n'})
    archive_root = tmp_path / "archive"
    archive_transcripts([source], archive_root, now=NOW)

    grown = '{"n":1}\n{"n":2}\n'
    (source / "s.jsonl").write_text(grown, encoding="utf-8")
    report = archive_transcripts([source], archive_root, now=NOW)

    assert report.archived == 1
    compressed = archived_file(archive_root, source, "s.jsonl")
    assert zstd.decompress(compressed.read_bytes()).decode() == grown


def test_shrunk_source_never_overwrites_a_fuller_archive(tmp_path):
    full = '{"n":1}\n{"n":2}\n{"n":3}\n'
    source = make_source(tmp_path, files={"s.jsonl": full})
    archive_root = tmp_path / "archive"
    archive_transcripts([source], archive_root, now=NOW)

    # Troncature suspecte côté source : un transcript est append-only.
    (source / "s.jsonl").write_text('{"n":1}\n', encoding="utf-8")
    report = archive_transcripts([source], archive_root, now=NOW)

    assert report.archived == 0
    assert report.shrunk_kept == 1
    compressed = archived_file(archive_root, source, "s.jsonl")
    assert zstd.decompress(compressed.read_bytes()).decode() == full


def test_missing_source_is_reported_not_fatal(tmp_path):
    report = archive_transcripts(
        [tmp_path / "absent"], tmp_path / "archive", now=NOW
    )

    assert report.archived == 0
    assert report.missing_sources == [str(tmp_path / "absent")]


def test_dry_run_writes_nothing(tmp_path):
    source = make_source(tmp_path)
    archive_root = tmp_path / "archive"

    report = archive_transcripts([source], archive_root, dry_run=True, now=NOW)

    assert report.archived == 1
    assert not archive_root.exists()


def test_corrupt_manifest_is_an_infrastructure_error(tmp_path):
    source = make_source(tmp_path)
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    (archive_root / "manifest.json").write_text("not json{{{", encoding="utf-8")

    # La garde anti-troncature dépend du manifeste : mieux vaut s'arrêter
    # que risquer d'écraser une archive plus complète.
    with pytest.raises(ArchiveInfrastructureError):
        archive_transcripts([source], archive_root, now=NOW)


def test_cli_reports_summary_and_exit_codes(tmp_path, monkeypatch, capsys):
    source = make_source(tmp_path)
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "archive_transcripts",
            "--source",
            str(source),
            "--archive-root",
            str(archive_root),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "Archived: 1" in output

    (archive_root / "manifest.json").write_text("broken", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2


def test_concurrent_passes_on_the_same_transcript_are_serialized(tmp_path):
    # Hook SessionEnd et passage horaire lancés en même temps : une archive,
    # une entrée de manifeste, zéro exception. Le verrou sérialise, les
    # temporaires uniques couvrent le reste.
    import threading

    source = make_source(tmp_path, files={"proj/s.jsonl": '{"a":1}\n' * 200})
    archive_root = tmp_path / "archive"
    barrier = threading.Barrier(2)
    reports, errors = [], []

    def run():
        try:
            barrier.wait(timeout=5)
            reports.append(archive_transcripts([source], archive_root, now=NOW))
        except Exception as exc:  # noqa: BLE001 — le test veut zéro exception
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sum(report.archived for report in reports) == 1
    assert sum(report.unchanged for report in reports) == 1
    assert archived_file(archive_root, source, "proj/s.jsonl").exists()
    manifest = json.loads((archive_root / "manifest.json").read_text())
    assert len(manifest["files"]) == 1
    leftovers = [p for p in archive_root.rglob("*.tmp")]
    assert leftovers == []


def test_lock_held_elsewhere_is_a_clean_infrastructure_error(tmp_path):
    from daemon_v2.file_lock import exclusive_lock
    from scripts.archive_transcripts import LOCK_NAME

    source = make_source(tmp_path)
    archive_root = tmp_path / "archive"
    archive_root.mkdir()

    with exclusive_lock(archive_root / LOCK_NAME):
        with pytest.raises(ArchiveInfrastructureError, match="verrou occupé"):
            archive_transcripts([source], archive_root, now=NOW, lock_timeout_s=0.2)
