"""Archivage zstd en lecture seule des transcripts d'agents (décision du 2026-08-30).

Copie compressée des ``.jsonl`` de sessions (Claude Code, Codex) vers un
dossier d'archive, AVANT leur purge par les outils sources (Claude Code
efface ses transcripts après ~30 jours par défaut). C'est le préalable à
l'ingestion ``agent_session`` : le pointeur vers le fichier source reste
résolvable via l'archive une fois l'original purgé.

Garanties :
- Les sources ne sont JAMAIS modifiées ni supprimées (lecture seule).
- Écritures atomiques (fichier temporaire puis rename), reruns idempotents :
  seul un fichier nouveau ou qui a grossi est (ré)archivé.
- Un transcript est append-only par nature : une source plus PETITE que sa
  version archivée est suspecte (troncature) — l'archive existante est
  conservée telle quelle et le cas est signalé, jamais écrasé.

Usage :
    python -m scripts.archive_transcripts [--source CHEMIN]... [--dry-run]

Sources par défaut : ``~/.claude/projects`` et ``~/.codex/sessions``.
Archive : ``PULSE_TRANSCRIPT_ARCHIVE_PATH`` sinon
``~/.pulse_v2/transcript_archive`` (miroir de l'arborescence source,
suffixe ``.zst``, manifeste ``manifest.json`` à la racine).

Codes de sortie : 0 = archivage terminé (y compris « rien à faire ») ;
2 = erreur d'infrastructure (archive inécrivable, manifeste corrompu) —
distinct pour que cron/launchd ne confonde jamais « panne de l'outil » et
« rien de nouveau ».

Compression : ``compression.zstd`` de la stdlib (Python ≥ 3.14) — aucune
dépendance externe.
"""

from __future__ import annotations

import argparse
import json
import os
from compression import zstd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from daemon_v2.private_files import apply_private_umask, ensure_private_directory


DEFAULT_SOURCES = (
    Path.home() / ".claude" / "projects",
    Path.home() / ".codex" / "sessions",
)
COMPRESSION_LEVEL = 9
MANIFEST_NAME = "manifest.json"


class ArchiveInfrastructureError(RuntimeError):
    """L'archive n'a pas pu être écrite ou son manifeste est corrompu."""


@dataclass
class ArchiveReport:
    archived: int = 0
    unchanged: int = 0
    shrunk_kept: int = 0
    skipped_unreadable: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    missing_sources: list[str] = field(default_factory=list)


def default_archive_root() -> Path:
    configured = os.environ.get("PULSE_TRANSCRIPT_ARCHIVE_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".pulse_v2" / "transcript_archive"


def source_slug(source: Path) -> str:
    """Nom de sous-dossier stable et lisible dérivé du chemin source."""
    parts = [part for part in source.expanduser().resolve().parts if part != "/"]
    return "-".join(parts)


def _load_manifest(archive_root: Path) -> dict[str, dict[str, int | str]]:
    manifest_path = archive_root / MANIFEST_NAME
    if not manifest_path.exists():
        return {}
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = loaded["files"]
        if not isinstance(files, dict):
            raise TypeError("files must be an object")
        return files
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Un manifeste corrompu perd la garde anti-troncature : on s'arrête
        # plutôt que de risquer d'écraser une archive plus complète.
        raise ArchiveInfrastructureError(
            f"unreadable manifest: {manifest_path} ({exc})"
        ) from exc


def _write_manifest(
    archive_root: Path, files: dict[str, dict[str, int | str]]
) -> None:
    manifest_path = archive_root / MANIFEST_NAME
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"files": files}, sort_keys=True, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def _archive_one(
    source_file: Path,
    destination: Path,
    *,
    level: int,
) -> int:
    data = source_file.read_bytes()
    compressed = zstd.compress(data, level)
    ensure_private_directory(destination.parent)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(compressed)
    os.replace(temporary, destination)
    return len(compressed)


def archive_transcripts(
    sources: list[Path] | tuple[Path, ...] = DEFAULT_SOURCES,
    archive_root: Path | None = None,
    *,
    dry_run: bool = False,
    level: int = COMPRESSION_LEVEL,
    now: datetime | None = None,
) -> ArchiveReport:
    root = (archive_root or default_archive_root()).expanduser()
    archived_at = (now or datetime.now(timezone.utc)).isoformat()
    report = ArchiveReport()

    if not dry_run:
        try:
            ensure_private_directory(root)
        except OSError as exc:
            raise ArchiveInfrastructureError(
                f"cannot create archive root: {root} ({exc})"
            ) from exc
    manifest = _load_manifest(root)

    for source in sources:
        source = source.expanduser()
        if not source.is_dir():
            report.missing_sources.append(str(source))
            continue
        slug = source_slug(source)
        for source_file in sorted(source.rglob("*.jsonl")):
            try:
                stat = source_file.stat()
            except OSError:
                # Purgé par l'outil source entre le rglob et le stat :
                # transitoire, le prochain run n'y verra rien à faire.
                report.skipped_unreadable += 1
                continue
            key = f"{slug}/{source_file.relative_to(source)}"
            recorded = manifest.get(key)
            if recorded is not None:
                if (
                    stat.st_size == recorded["size"]
                    and stat.st_mtime_ns == recorded["mtime_ns"]
                ):
                    report.unchanged += 1
                    continue
                if stat.st_size < int(recorded["size"]):
                    # Append-only par nature : une source rétrécie est une
                    # troncature suspecte — l'archive (plus complète) prime.
                    report.shrunk_kept += 1
                    continue
            if dry_run:
                report.archived += 1
                report.bytes_in += stat.st_size
                continue
            destination = root / slug / source_file.relative_to(source)
            destination = destination.with_suffix(destination.suffix + ".zst")
            try:
                compressed_size = _archive_one(
                    source_file, destination, level=level
                )
            except OSError as exc:
                raise ArchiveInfrastructureError(
                    f"cannot write archive: {destination} ({exc})"
                ) from exc
            manifest[key] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "compressed_size": compressed_size,
                "archived_at": archived_at,
            }
            report.archived += 1
            report.bytes_in += stat.st_size
            report.bytes_out += compressed_size

    if not dry_run and report.archived:
        _write_manifest(root, manifest)
    return report


def main() -> None:
    apply_private_umask()
    parser = argparse.ArgumentParser(
        description="Archive agent transcripts as zstd copies (read-only)"
    )
    parser.add_argument(
        "--source",
        action="append",
        type=Path,
        default=None,
        help="source directory (repeatable; defaults to Claude Code + Codex)",
    )
    parser.add_argument("--archive-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--level", type=int, default=COMPRESSION_LEVEL)
    args = parser.parse_args()

    try:
        report = archive_transcripts(
            tuple(args.source) if args.source else DEFAULT_SOURCES,
            args.archive_root,
            dry_run=args.dry_run,
            level=args.level,
        )
    except ArchiveInfrastructureError as exc:
        print(f"Pulse transcript archive: {exc}")
        raise SystemExit(2) from exc

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Archived: {report.archived}")
    print(f"Unchanged: {report.unchanged}")
    if report.shrunk_kept:
        print(
            f"ATTENTION — sources rétrécies, archives conservées : "
            f"{report.shrunk_kept}"
        )
    if report.skipped_unreadable:
        print(f"Skipped (vanished/unreadable): {report.skipped_unreadable}")
    if report.bytes_in:
        ratio = report.bytes_out / report.bytes_in if report.bytes_out else 0
        print(
            f"Bytes: {report.bytes_in} -> {report.bytes_out}"
            + (f" ({ratio:.0%})" if report.bytes_out else "")
        )
    for missing in report.missing_sources:
        print(f"Source absente (ignorée) : {missing}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
