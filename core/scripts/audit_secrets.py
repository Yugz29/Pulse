"""Audit en lecture seule : des secrets sont-ils persistés dans les bases Pulse ?

Applique ``redact_command`` (la source de vérité de la rédaction) à chaque
texte stocké (commande, résumé, message de commit, corps de réponse des
dead-letters) : toute ligne où la sortie diffère contient une valeur en forme
de secret. N'affiche jamais la valeur elle-même — uniquement des comptes,
dates et producteurs.

LIMITE STRUCTURELLE (oracle circulaire) : cet audit détecte exactement ce que
``redact_command`` sait masquer, ni plus ni moins. Un secret d'une forme non
couverte par les motifs est invisible (exit 0 ≠ « aucun secret »), et un motif
sur-rédacteur ferait remonter des lignes bénignes. L'outil mesure « la
rédaction actuelle a-t-elle été appliquée partout », pas « la base est-elle
exempte de secrets ».

Usage :
    python -m scripts.audit_secrets [--trace CHEMIN] [--outbox CHEMIN]

Les chemins par défaut suivent la config du daemon : ``PULSE_V2_DB_PATH`` et
``PULSE_CORE_OUTBOX_PATH`` sont honorés, comme dans ``daemon_v2``.

Codes de sortie : 0 = aucune ligne suspecte ; 1 = lignes suspectes trouvées ;
2 = erreur d'infrastructure (base illisible, verrouillée, schéma inattendu) —
distinct pour que CI/cron ne confonde jamais « panne de l'audit » et
« secrets trouvés ».

Le nettoyage d'historique n'est volontairement pas implémenté : l'audit du
2026-08-29 n'a trouvé aucune ligne à nettoyer, et la base est append-only.
Si cet audit remonte un jour des lignes, construire alors la réécriture.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from daemon_v2.ingest import command_has_secret
from daemon_v2.producer_outbox import default_outbox_path
from daemon_v2.runtime_config import select_database_path


class AuditInfrastructureError(RuntimeError):
    """La base n'a pas pu être auditée (≠ « des secrets ont été trouvés »)."""


def _read_only(path: Path) -> sqlite3.Connection:
    # Chemin percent-encodé : un chemin contenant ? ou # ne peut pas altérer
    # les paramètres de l'URI (mode=ro reste effectif).
    connection = sqlite3.connect(
        f"file:{quote(str(path))}?mode=ro", uri=True, timeout=5.0
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _texts_from_details(details_json: str) -> list[str]:
    try:
        details = json.loads(details_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(details, dict):
        return []
    texts = []
    for key in ("command", "message"):
        if isinstance(details.get(key), str):
            texts.append(details[key])
    return texts


def _payload_texts(payload_json: str) -> list[str]:
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    texts = []
    details = payload.get("details")
    for source in (payload, details if isinstance(details, dict) else {}):
        for key in ("command", "message"):
            if isinstance(source.get(key), str):
                texts.append(source[key])
    return texts


def _is_suspicious(texts: list[str]) -> bool:
    # command_has_secret ignore la normalisation des continuations de ligne :
    # un texte historique qui ne diffère que par ce repli n'est pas un secret.
    return any(command_has_secret(text) for text in texts)


def audit_trace(path: Path) -> int:
    if not path.exists():
        print(f"trace absente : {path}")
        return 0
    suspicious: dict[str, list[str]] = {}
    total = 0
    try:
        with _read_only(path) as connection:
            for row in connection.execute(
                "SELECT occurred_at, producer_name, details_json, summary"
                " FROM activities"
            ):
                total += 1
                texts = [row["summary"] or ""]
                texts.extend(_texts_from_details(row["details_json"] or ""))
                if _is_suspicious(texts):
                    suspicious.setdefault(row["producer_name"], []).append(
                        row["occurred_at"][:10]
                    )
    except sqlite3.DatabaseError as exc:
        raise AuditInfrastructureError(f"trace inauditables ({path}): {exc}") from exc
    suspect_count = sum(len(dates) for dates in suspicious.values())
    print(f"trace {path} : {total} lignes, {suspect_count} suspecte(s)")
    for producer, dates in sorted(suspicious.items()):
        print(f"  {producer}: {len(dates)} ligne(s), "
              f"dates {min(dates)}..{max(dates)}")
    return suspect_count


def audit_outbox(path: Path) -> int:
    if not path.exists():
        print(f"outbox absente : {path}")
        return 0
    found = 0
    try:
        with _read_only(path) as connection:
            for table, columns in (
                ("events", ("payload_json",)),
                ("dead_letters", ("payload_json", "response_body")),
            ):
                try:
                    rows = connection.execute(
                        f"SELECT {', '.join(columns)} FROM {table}"
                    )
                except sqlite3.OperationalError:
                    # Table absente (vieille outbox) : rien à auditer ici.
                    continue
                count = 0
                hits = 0
                for row in rows:
                    count += 1
                    texts = _payload_texts(row["payload_json"] or "")
                    if "response_body" in row.keys() and row["response_body"]:
                        texts.append(row["response_body"])
                    if _is_suspicious(texts):
                        hits += 1
                found += hits
                print(f"outbox {path} [{table}] : {count} lignes, {hits} suspecte(s)")
    except sqlite3.DatabaseError as exc:
        raise AuditInfrastructureError(f"outbox inauditables ({path}): {exc}") from exc
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit de secrets Pulse (lecture seule)"
    )
    parser.add_argument("--trace", type=Path, default=select_database_path())
    parser.add_argument("--outbox", type=Path, default=default_outbox_path())
    args = parser.parse_args()
    try:
        found = audit_trace(args.trace.expanduser())
        found += audit_outbox(args.outbox.expanduser())
    except AuditInfrastructureError as exc:
        print(f"ERREUR AUDIT: {exc}")
        raise SystemExit(2) from exc
    raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
