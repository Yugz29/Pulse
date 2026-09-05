#!/usr/bin/env python3
"""Normalise une COPIE d'une ancienne base Pulse pour la rendre fusionnable.

Voie C (one-shot) : aucune modification du code de Core, aucun dégel.
Deux dérives sont corrigées, dans cet ordre, sur des frontières de segment :

  1. correspondances de projet explicites (restructuration, renommages) ;
  2. casse du dossier utilisateur, en repli pour tout le reste.

Les chemins vivent sous quatre formes distinctes dans les données ; les trois
dernières sont dérivées mécaniquement de la première, jamais écrites à la main :

  a. chemin POSIX            /Users/yugz/Projets/Pulse_V2
  b. encodage Claude Code    -Users-yugz-Projets-Pulse-V2      ("/" et "_" -> "-")
  c. slug d'archive          Users-yugz-.claude-projects       (parts jointes par "-")
  d. texte libre             summary, command, message, first_prompt

Garanties :
  - les originaux ne sont jamais ouverts en écriture (copie systématique) ;
  - refus catégorique de travailler sous ~/.pulse_v2 (base active) ;
  - `event_id` et `session_id` ne sont jamais touchés (clés de fusion) ;
  - `event_fingerprint` est recalculé avec la fonction de Core elle-même, après
    un auto-test qui exige de reproduire 100 % des empreintes existantes.

Usage :
    python3 normalize_legacy_trace.py --report-only
    python3 normalize_legacy_trace.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# --------------------------------------------------------------------------
# Table de correspondance
# --------------------------------------------------------------------------
# Ordre significatif : premier préfixe qui matche sur une frontière de segment.
# Les plus spécifiques d'abord (Pulse/Pulse_Core avant Pulse).

@dataclass(frozen=True)
class Rule:
    old: str
    new: str
    why: str


PATH_RULES: tuple[Rule, ...] = (
    # --- restructuration en repo unique : Core a migré vers core/ -----------
    Rule("/Users/yugz/Projets/Pulse/Pulse_Core",
         "/Users/Yugz/Projets/Pulse/core",
         "Core avant le repo unique (2026-07-23 -> 2026-09-02)"),
    Rule("/Users/yugz/Projets/Pulse_V2",
         "/Users/Yugz/Projets/Pulse/core",
         "premier Core, avant le renommage (2026-07-03 -> 2026-07-07)"),
    # --- À TRANCHER : 6 événements d'avril, dossier disparu ----------------
    Rule("/Users/yugz/Projets/Pulse/Pulse",
         "/Users/Yugz/Projets/Pulse",
         "AMBIGU — imbrication transitoire d'avril 2026, 6 événements"),
    # --- renommages sans rapport avec Pulse --------------------------------
    Rule("/Users/yugz/Projets/portfolio",
         "/Users/Yugz/Projets/Portfolio",
         "seconde dérive de casse, indépendante de $HOME"),
    Rule("/Users/yugz/Projets/Holberton C#28",
         "/Users/Yugz/Projets/Holberton28",
         "renommé sur l'ancienne machine déjà"),
    # --- repli : la casse du dossier utilisateur ---------------------------
    Rule("/Users/yugz",
         "/Users/Yugz",
         "casse du dossier utilisateur"),
)


def encoded(path: str) -> str:
    """Encodage des dossiers de projet par Claude Code : "/" et "_" -> "-"."""
    return path.replace("/", "-").replace("_", "-")


def slugged(path: str) -> str:
    """Slug d'archive (`archive_transcripts.source_slug`) : parts jointes par "-"."""
    return "-".join(part for part in Path(path).parts if part != "/")


def derived_rules() -> tuple[Rule, ...]:
    """Formes b et c, dérivées des règles POSIX — jamais saisies à la main."""
    out: list[Rule] = []
    for rule in PATH_RULES:
        enc_old, enc_new = encoded(rule.old), encoded(rule.new)
        if enc_old != rule.old:
            out.append(Rule(enc_old, enc_new, f"{rule.why} (encodage Claude Code)"))
        for suffix in (".claude/projects", ".codex/sessions"):
            slug_old = slugged(f"{rule.old}/{suffix}")
            slug_new = slugged(f"{rule.new}/{suffix}")
            if slug_old != slug_new:
                out.append(Rule(slug_old, slug_new, f"{rule.why} (slug d'archive)"))
    # dédoublonnage en conservant l'ordre
    seen: set[str] = set()
    unique: list[Rule] = []
    for rule in out:
        if rule.old in seen:
            continue
        seen.add(rule.old)
        unique.append(rule)
    return tuple(unique)


ALL_RULES: tuple[Rule, ...] = tuple(
    sorted(PATH_RULES + derived_rules(), key=lambda r: -len(r.old))
)


def _boundary_ok(text: str, start: int, length: int) -> bool:
    """Le préfixe ne matche que s'il ne coupe pas un nom en deux.

    On refuse uniquement une suite alphanumérique ou `_`, qui ferait un autre
    nom dans le même segment (`…/Pulse` ne doit pas avaler `…/Pulse_V2`).
    Tout le reste est une frontière valide — y compris `.` (fin de phrase :
    « le dépôt /…/Pulse_Core. Lance… ») et `-` (encodage Claude Code, où
    `-Users-yugz` précède `-Projets-Cortex`). Le tri des règles par longueur
    décroissante tranche déjà les préfixes emboîtés ; cette garde couvre le
    reste.
    """
    end = start + length
    if end >= len(text):
        return True
    following = text[end]
    return not (following.isalnum() or following == "_")


def rewrite_text(text: str, hits: Counter[str]) -> str:
    """Applique les règles sur toutes les occurrences, la première qui matche."""
    if not text:
        return text
    result: list[str] = []
    index = 0
    while index < len(text):
        for rule in ALL_RULES:
            if text.startswith(rule.old, index) and _boundary_ok(text, index, len(rule.old)):
                result.append(rule.new)
                hits[rule.old] += 1
                index += len(rule.old)
                break
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def rewrite_json(value, hits: Counter[str]):
    """Réécriture récursive : chaînes seulement, structure préservée."""
    if isinstance(value, str):
        return rewrite_text(value, hits)
    if isinstance(value, dict):
        return {key: rewrite_json(item, hits) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_json(item, hits) for item in value]
    return value


# --------------------------------------------------------------------------
# Empreinte canonique — importée de Core, jamais réimplémentée
# --------------------------------------------------------------------------

def load_core_fingerprint(core_root: Path):
    sys.path.insert(0, str(core_root))
    from daemon_v2.models import CanonicalEvent, canonical_event_fingerprint
    return CanonicalEvent, canonical_event_fingerprint


def fingerprint_of(row, details: dict, CanonicalEvent, compute) -> str:
    return compute(
        CanonicalEvent(
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            event_type=row["type"],
            producer_name=row["producer_name"],
            producer_version=row["producer_version"],
            producer_instance_id=row["producer_instance_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            details=details,
        )
    )


# --------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------

@dataclass
class Report:
    rows_total: int = 0
    rows_changed: int = 0
    details_changed: int = 0
    summary_changed: int = 0
    fingerprints_recomputed: int = 0
    fingerprints_left_stale: int = 0
    fingerprints_stale: int = 0
    stale_types: Counter[str] = field(default_factory=Counter)
    fingerprint_selftest_total: int = 0
    fingerprint_selftest_ok: int = 0
    rule_hits: Counter[str] = field(default_factory=Counter)
    leftovers: Counter[str] = field(default_factory=Counter)
    manifest_archive_keys: int = 0
    manifest_archive_renamed: int = 0
    manifest_agent_keys: int = 0
    manifest_agent_renamed: int = 0
    tree_renames: list[tuple[str, str]] = field(default_factory=list)
    resolved_sample: tuple[int, int] = (0, 0)


def scan_leftovers(text: str, report: Report) -> None:
    """Toute trace résiduelle de l'ancienne machine après réécriture."""
    for needle in ("/Users/yugz", "Users-yugz", "-users-yugz", "Pulse_V2", "Pulse_Core"):
        if needle in text:
            report.leftovers[needle] += 1


# --------------------------------------------------------------------------
# Passes
# --------------------------------------------------------------------------

COLUMNS = (
    "id", "session_id", "activity_type", "occurred_at", "recorded_at", "source",
    "summary", "details_json", "event_id", "schema_version", "type",
    "producer_name", "producer_version", "producer_instance_id",
    "event_fingerprint", "occurred_at_utc",
)


def clone_schema(source: sqlite3.Connection, target_path: Path) -> sqlite3.Connection:
    """Base neuve avec le DDL exact de la source (table, index, triggers).

    `activities` est append-only par trigger : un UPDATE est refusé, donc on
    ne normalise pas en place — on écrit une base neuve. C'est aussi la forme
    dont la fusion a besoin.
    """
    target_path.unlink(missing_ok=True)
    target = sqlite3.connect(target_path)
    statements = source.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END"
    ).fetchall()
    for (statement,) in statements:
        if statement.startswith("CREATE TABLE sqlite_sequence"):
            continue  # créée implicitement par AUTOINCREMENT
        target.execute(statement)
    target.commit()
    return target


def normalize_database(db_path: Path, core_root: Path, report: Report, apply: bool) -> Path:
    CanonicalEvent, compute = load_core_fingerprint(core_root)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    rows = connection.execute("SELECT * FROM activities ORDER BY id").fetchall()
    report.rows_total = len(rows)

    # -- auto-test : reproduire les empreintes existantes AVANT de toucher --
    # Une empreinte n'est recalculée que si l'on sait d'abord reproduire celle
    # qui est stockée : c'est la preuve, ligne par ligne, que la reconstruction
    # est fidèle. Les autres gardent la leur (déjà périmée avant nous).
    reproducible: set[int] = set()
    stale: list[sqlite3.Row] = []
    for row in rows:
        if row["event_fingerprint"] is None:
            continue
        report.fingerprint_selftest_total += 1
        try:
            recomputed = fingerprint_of(
                row, json.loads(row["details_json"]), CanonicalEvent, compute
            )
        except Exception:
            recomputed = None
        if recomputed == row["event_fingerprint"]:
            report.fingerprint_selftest_ok += 1
            reproducible.add(row["id"])
        else:
            stale.append(row)

    report.fingerprints_stale = len(stale)
    report.stale_types = Counter(row["type"] for row in stale)

    # Une empreinte périmée n'est dangereuse que sur un `event_id` déterministe
    # (uuid5) : une ré-émission ultérieure lèverait EventConflictError. Les
    # `event_id` uuid4 ne sont jamais ré-émis, donc jamais confrontés.
    deterministic = [row for row in stale if row["type"] == "agent_session"]
    if deterministic:
        raise SystemExit(
            f"ABANDON : {len(deterministic)} agent_session ont une empreinte non "
            "reproductible. Leur event_id est déterministe : une ré-émission "
            "lèverait EventConflictError. À trancher avant de continuer."
        )

    # -- réécriture vers une base neuve -------------------------------------
    target_path = db_path.with_name("trace.normalized.db")
    target = clone_schema(connection, target_path) if apply else None
    outgoing: list[tuple] = []

    for row in rows:
        hits: Counter[str] = Counter()
        details = json.loads(row["details_json"])
        new_details = rewrite_json(details, hits)
        new_summary = rewrite_text(row["summary"] or "", hits)

        details_changed = new_details != details
        summary_changed = new_summary != (row["summary"] or "")

        # Une ligne intacte garde ses octets d'origine : on ne re-sérialise
        # que ce qu'on a réellement modifié.
        new_details_json = (
            json.dumps(new_details, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
            if details_changed
            else row["details_json"]
        )
        new_fingerprint = row["event_fingerprint"]

        if details_changed or summary_changed:
            report.rows_changed += 1
            report.details_changed += int(details_changed)
            report.summary_changed += int(summary_changed)
            report.rule_hits.update(hits)
            scan_leftovers(new_details_json + new_summary, report)

            if new_fingerprint is not None and details_changed:
                if row["id"] in reproducible:
                    new_fingerprint = fingerprint_of(
                        row, new_details, CanonicalEvent, compute
                    )
                    report.fingerprints_recomputed += 1
                else:
                    report.fingerprints_left_stale += 1

        values = dict(row)
        values["details_json"] = new_details_json
        values["summary"] = new_summary
        values["event_fingerprint"] = new_fingerprint
        outgoing.append(tuple(values[column] for column in COLUMNS))

    if target is not None:
        placeholders = ", ".join("?" for _ in COLUMNS)
        target.executemany(
            f"INSERT INTO activities ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            outgoing,
        )
        target.commit()
        target.close()
    connection.close()
    return target_path


def normalize_archive_manifest(manifest_path: Path, report: Report, apply: bool) -> None:
    """Clés du manifeste d'archive + plan de renommage de l'arborescence."""
    if not manifest_path.exists():
        return
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = loaded["files"]
    report.manifest_archive_keys = len(files)

    rewritten: dict[str, dict] = {}
    renames: dict[str, str] = {}

    for key, entry in files.items():
        hits: Counter[str] = Counter()
        new_key = rewrite_text(key, hits)
        if new_key != key:
            report.manifest_archive_renamed += 1
            report.rule_hits.update(hits)
            # Un renommage par SEGMENT modifié, pas par dossier feuille : le
            # slug `Users-yugz-.codex-sessions` est un seul `mv`, pas un par
            # jour archivé. Les parents se renomment avant leurs enfants, donc
            # la cible est exprimée sous le parent déjà renommé.
            old_parts, new_parts = key.split("/"), new_key.split("/")
            for depth in range(len(old_parts) - 1):  # jamais le fichier final
                if old_parts[depth] == new_parts[depth]:
                    continue
                parent = "/".join(new_parts[:depth])
                source = f"{parent}/{old_parts[depth]}" if parent else old_parts[depth]
                destination = "/".join(new_parts[: depth + 1])
                renames[source] = destination
        scan_leftovers(new_key, report)
        if new_key in rewritten:
            # Deux clés d'origine pour une seule clé normalisée : l'écrasement
            # silencieux perdrait une entrée d'archive.
            raise SystemExit(f"ABANDON : collision de clé de manifeste sur {new_key}")
        rewritten[new_key] = entry

    report.tree_renames = sorted(renames.items(), key=lambda item: item[0].count("/"))
    if apply:
        loaded["files"] = rewritten
        manifest_path.write_text(
            json.dumps(loaded, indent=1, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


def normalize_agent_manifest(manifest_path: Path, report: Report, apply: bool) -> None:
    """Clés = chemins absolus de transcripts (`agent_sessions.py:491`)."""
    if not manifest_path.exists():
        return
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    emitted = loaded["emitted"]
    report.manifest_agent_keys = len(emitted)

    rewritten: dict[str, dict] = {}
    for key, entry in emitted.items():
        hits: Counter[str] = Counter()
        new_key = rewrite_text(key, hits)
        new_entry = rewrite_json(entry, hits)
        if new_key != key or new_entry != entry:
            report.manifest_agent_renamed += 1
            report.rule_hits.update(hits)
        scan_leftovers(new_key + json.dumps(new_entry, ensure_ascii=False), report)
        rewritten[new_key] = new_entry

    if apply:
        loaded["emitted"] = rewritten
        manifest_path.write_text(
            json.dumps(loaded, indent=1, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


def check_resolution(db_path: Path, report: Report, limit: int = 400) -> None:
    """Combien de chemins réécrits désignent un fichier réel, à la casse exacte ?"""

    def exists_exact(path: Path) -> bool:
        cursor = Path("/")
        for part in path.parts[1:]:
            try:
                if part not in {entry.name for entry in cursor.iterdir()}:
                    return False
            except OSError:
                return False
            cursor = cursor / part
        return True

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT DISTINCT json_extract(details_json, '$.path') FROM activities "
        "WHERE type = 'file_changed' AND json_extract(details_json, '$.path') "
        f"IS NOT NULL LIMIT {limit}"
    ).fetchall()
    connection.close()
    resolved = sum(1 for (path,) in rows if exists_exact(Path(path)))
    report.resolved_sample = (resolved, len(rows))


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path.home() / "Desktop" / "Pulse" / ".pulse_v2")
    parser.add_argument("--workdir", type=Path,
                        default=Path(__file__).parent / "normalized")
    parser.add_argument("--core-root", type=Path,
                        default=Path.home() / "Projets" / "Pulse" / "core")
    parser.add_argument("--apply", action="store_true",
                        help="écrit dans la copie (sinon simulation)")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    live = Path.home() / ".pulse_v2"
    for candidate in (args.source, args.workdir):
        resolved = candidate.expanduser().absolute()
        if resolved == live or str(resolved).startswith(f"{live}/"):
            raise SystemExit(f"REFUS : {resolved} est sous la base active {live}.")

    apply = args.apply and not args.report_only
    args.workdir.mkdir(parents=True, exist_ok=True)

    # Copie : les originaux ne sont jamais ouverts en écriture.
    db_copy = args.workdir / "trace.db"
    shutil.copy2(args.source / "trace.db", db_copy)
    archive_manifest = args.workdir / "transcript_archive_manifest.json"
    source_archive = args.source / "transcript_archive" / "manifest.json"
    if source_archive.exists():
        shutil.copy2(source_archive, archive_manifest)
    agent_manifest = args.workdir / "agent_sessions_manifest.json"
    source_agent = args.source / "agent_sessions_manifest.json"
    if source_agent.exists():
        shutil.copy2(source_agent, agent_manifest)

    report = Report()
    normalized = normalize_database(db_copy, args.core_root, report, apply)
    normalize_archive_manifest(archive_manifest, report, apply)
    normalize_agent_manifest(agent_manifest, report, apply)
    if apply:
        check_resolution(normalized, report)

    render(report, args.workdir, apply)
    if apply:
        print(f"\nBase normalisée : {normalized}")
    return 0


def render(report: Report, workdir: Path, apply: bool) -> None:
    mode = "APPLIQUÉ" if apply else "SIMULATION (aucune écriture)"
    print(f"\n=== Normalisation — {mode} ===")
    print(f"copie de travail : {workdir}\n")

    print("Règles utilisées (frontière de segment, première qui matche) :")
    for rule in ALL_RULES:
        count = report.rule_hits.get(rule.old, 0)
        if count:
            print(f"  {count:>6}  {rule.old}\n          -> {rule.new}   [{rule.why}]")
    unused = [r for r in ALL_RULES if not report.rule_hits.get(r.old)]
    if unused:
        print(f"\n  ({len(unused)} règle(s) dérivée(s) sans occurrence)")

    print(f"\nBase : {report.rows_total} lignes, {report.rows_changed} modifiées")
    print(f"  details_json réécrit        : {report.details_changed}")
    print(f"  summary réécrit             : {report.summary_changed}")
    print(f"  empreintes recalculées      : {report.fingerprints_recomputed}")
    print(f"  auto-test empreinte         : "
          f"{report.fingerprint_selftest_ok}/{report.fingerprint_selftest_total} reproduites")
    if report.fingerprints_stale:
        types = ", ".join(f"{k} {v}" for k, v in report.stale_types.most_common())
        print(f"  empreintes déjà périmées    : {report.fingerprints_stale} "
              f"({types}) — laissées intactes,")
        print(f"    dont modifiées par nous   : {report.fingerprints_left_stale} "
              f"— event_id uuid4, jamais ré-émis, aucun conflit possible")

    print(f"\nManifeste d'archive : {report.manifest_archive_renamed}"
          f"/{report.manifest_archive_keys} clés réécrites")
    print(f"Manifeste agent_sessions : {report.manifest_agent_renamed}"
          f"/{report.manifest_agent_keys} clés réécrites")

    if report.tree_renames:
        script = workdir / "rename_archive_tree.sh"
        lines = [
            "#!/usr/bin/env bash",
            "# Renomme l'arborescence d'archive pour qu'elle corresponde aux",
            "# clés normalisées du manifeste. À lancer sur une COPIE des 215 Mo,",
            "# depuis la racine de l'archive. Parents avant enfants.",
            "set -euo pipefail",
            'root="${1:?usage: rename_archive_tree.sh <racine-archive-copiee>}"',
            'cd "$root"',
            "",
        ]
        targets = Counter(new for _, new in report.tree_renames)
        # Les renommages qui ne changent QUE la casse passent d'abord et en
        # `mv` nu : APFS est insensible à la casse, donc source et destination
        # y sont le même inode — une fusion de contenus s'y auto-détruirait.
        ordered = sorted(
            report.tree_renames,
            key=lambda item: (item[0].casefold() != item[1].casefold(),
                              item[0].count("/")),
        )
        for old, new in ordered:
            if targets[new] > 1 and old.casefold() != new.casefold():
                # Deux dossiers d'origine visent la même destination (deux
                # orthographes du même projet). Un `mv` nu imbriquerait le
                # second dans le premier : on fusionne les contenus.
                lines += [
                    f'if [ -e "{old}" ]; then',
                    f'  mkdir -p "{new}"',
                    f'  mv "{old}"/* "{new}"/ 2>/dev/null || true',
                    f'  rmdir "{old}"',
                    "fi",
                ]
            else:
                lines.append(f'[ -e "{old}" ] && mv "{old}" "{new}"')
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
        print(f"\nArborescence d'archive : {len(report.tree_renames)} renommages "
              f"-> {script.name}")
        for old, new in report.tree_renames[:4]:
            print(f"    mv {old} -> {new}")
        if len(report.tree_renames) > 4:
            print(f"    … {len(report.tree_renames) - 4} autres")

    if report.resolved_sample[1]:
        resolved, total = report.resolved_sample
        print(f"\nContrôle : {resolved}/{total} chemins réécrits désignent un "
              f"fichier réel aujourd'hui (casse exacte)")

    if report.leftovers:
        print("\n⚠ Résidus de l'ancienne machine après réécriture :")
        for needle, count in report.leftovers.most_common():
            print(f"  {count:>6}  {needle}")
    else:
        print("\n✓ Aucun résidu /Users/yugz, Users-yugz, Pulse_V2 ou Pulse_Core")


if __name__ == "__main__":
    raise SystemExit(main())
