#!/usr/bin/env python3
"""Étape 1 de la fusion : base tierce = ancienne normalisée + base active.

Ne touche ni l'une ni l'autre : les deux sources sont ouvertes en lecture, la
sortie est un fichier neuf. La bascule est une étape séparée.

Règles :
  - `id` n'est jamais transporté : les deux bases partent de 1, AUTOINCREMENT
    réattribue dans l'ordre chronologique ;
  - `INSERT OR IGNORE` sur `idx_activities_event_id` (UNIQUE) rend l'opération
    idempotente ;
  - les événements de l'ancienne machine à partir de la première trace locale
    du nouveau Mac sont écartés (décision du 2026-09-05).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


COLUMNS = (
    "session_id", "activity_type", "occurred_at", "recorded_at", "source",
    "summary", "details_json", "event_id", "schema_version", "type",
    "producer_name", "producer_version", "producer_instance_id",
    "event_fingerprint", "occurred_at_utc",
)


def clone_schema(reference: Path, target: Path) -> sqlite3.Connection:
    source = sqlite3.connect(f"file:{reference}?mode=ro", uri=True)
    target.unlink(missing_ok=True)
    connection = sqlite3.connect(target)
    statements = source.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END"
    ).fetchall()
    for (statement,) in statements:
        if statement.startswith("CREATE TABLE sqlite_sequence"):
            continue
        connection.execute(statement)
    connection.commit()
    source.close()
    return connection


def copy_rows(target: sqlite3.Connection, source_path: Path, where: str) -> int:
    columns = ", ".join(COLUMNS)
    # ATTACH n'interprète pas les URI sans SQLITE_CONFIG_URI : chemin nu. Les
    # deux sources sont déjà des copies de travail, jamais les originaux.
    target.execute("ATTACH DATABASE ? AS src", (str(source_path),))
    before = target.execute("SELECT count(*) FROM activities").fetchone()[0]
    target.execute(
        f"INSERT OR IGNORE INTO activities ({columns}) "
        f"SELECT {columns} FROM src.activities WHERE {where} "
        "ORDER BY occurred_at_utc"
    )
    target.commit()
    after = target.execute("SELECT count(*) FROM activities").fetchone()[0]
    target.execute("DETACH DATABASE src")
    return after - before


def main() -> int:
    scratch = Path(__file__).parent
    legacy = scratch / "normalized" / "trace.normalized.db"
    # La copie de la base active doit être prise APRÈS l'arrêt des services,
    # sinon les événements enregistrés entre la copie et la bascule sont perdus.
    live = Path(sys.argv[1]) if len(sys.argv) > 1 else scratch / "dbs" / "live_trace.db"
    merged = scratch / "merged" / "trace.db"
    merged.parent.mkdir(parents=True, exist_ok=True)

    cutoff = sqlite3.connect(f"file:{live}?mode=ro", uri=True).execute(
        "SELECT min(occurred_at_utc) FROM activities"
    ).fetchone()[0]

    target = clone_schema(live, merged)
    inserted_legacy = copy_rows(target, legacy, f"occurred_at_utc < '{cutoff}'")
    inserted_live = copy_rows(target, live, "1=1")

    total = target.execute("SELECT count(*) FROM activities").fetchone()[0]
    distinct = target.execute(
        "SELECT count(DISTINCT event_id) FROM activities"
    ).fetchone()[0]
    integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    span = target.execute(
        "SELECT min(occurred_at_utc), max(occurred_at_utc) FROM activities"
    ).fetchone()

    legacy_total = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True).execute(
        "SELECT count(*) FROM activities"
    ).fetchone()[0]
    live_total = sqlite3.connect(f"file:{live}?mode=ro", uri=True).execute(
        "SELECT count(*) FROM activities"
    ).fetchone()[0]

    print("=== Fusion — base tierce ===")
    print(f"seuil (première trace locale) : {cutoff}\n")
    print(f"ancienne normalisée : {legacy_total} lignes")
    print(f"  retenues          : {inserted_legacy}")
    print(f"  écartées (>= seuil): {legacy_total - inserted_legacy}")
    print(f"base active         : {live_total} lignes")
    print(f"  retenues          : {inserted_live}")
    print(f"\nrésultat            : {total} lignes, {distinct} event_id distincts")
    print(f"integrity_check     : {integrity}")
    print(f"plage               : {span[0]}  ->  {span[1]}")
    print(f"fichier             : {merged}")

    if total != distinct:
        print("\n✗ doublons d'event_id : ABANDON")
        return 1
    if integrity != "ok":
        print("\n✗ integrity_check en échec : ABANDON")
        return 1

    print("\nRépartition par mois :")
    for month, count in target.execute(
        "SELECT substr(occurred_at_utc,1,7), count(*) FROM activities "
        "GROUP BY 1 ORDER BY 1"
    ):
        print(f"  {month}  {count:>6}")
    target.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
