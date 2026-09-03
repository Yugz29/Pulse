"""pulse-intel : la commande avant le service (spec v2 §8, étape 1).

    pulse-intel list [--date YYYY-MM-DD] [--json]
    pulse-intel summarize <id> [--date YYYY-MM-DD] --dry-run --fake FICHIER

Le vrai modèle arrive à l'étape 3 ; d'ici là ``--fake`` lit la sortie du
modèle dans un fichier. Un Core arrêté donne un message et le code 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import Config, ConfigError, config_home, load_config
from .core_client import CoreClient, CoreError, CoreUnavailable
from .selection import Classified, classify_sessions, find_session
from .session_summary import summarize_session
from .state import JobState
from .summarizer import FakeSummarizer, Summarizer


EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INFRASTRUCTURE = 2


def _parse_day(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date attendue au format YYYY-MM-DD") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse-intel",
        description="Résumé de session — couche Intelligence de Pulse",
    )
    parser.add_argument("--config", type=Path, default=None, help="config.toml")
    parser.add_argument("--core-url", default=None, help="remplace core_url")
    parser.add_argument(
        "--state", type=Path, default=None, help="état local (défaut ~/.pulse_intelligence/state.json)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="sessions closes, candidates ou non, avec raison")
    listing.add_argument("--date", type=_parse_day, default=None)
    listing.add_argument("--json", action="store_true")

    summarize = commands.add_parser("summarize", help="résumer une session")
    summarize.add_argument("session_id")
    summarize.add_argument("--date", type=_parse_day, default=None)
    summarize.add_argument("--dry-run", action="store_true", help="tout sauf l'émission")
    summarize.add_argument(
        "--fake",
        type=Path,
        default=None,
        help="sortie du modèle lue dans ce fichier (pas de modèle réel avant l'étape 3)",
    )
    return parser


def _load(args: argparse.Namespace) -> tuple[Config, CoreClient, JobState]:
    config = load_config(args.config)
    if args.core_url:
        config = Config(**{**config.__dict__, "core_url": args.core_url})
    client = CoreClient(config.core_url)
    state_path = args.state or config_home() / "state.json"
    return config, client, JobState.load(state_path)


def _summarizer(args: argparse.Namespace, config: Config) -> Summarizer:
    if args.fake is not None:
        return FakeSummarizer(
            outputs=args.fake.read_text(encoding="utf-8"),
            model_id=config.model_id or "fake/summarizer",
        )
    raise ConfigError(
        "aucun modèle disponible dans cette version : passe --fake FICHIER "
        "(le modèle réel arrive à l'étape 3)"
    )


def _format_listing(items: list[Classified]) -> str:
    if not items:
        return "aucune session close sur la période"
    lines = []
    for item in items:
        session = item.session
        mark = "*" if item.candidate else " "
        lines.append(
            f"{mark} {session.label:<8} {session.id}  "
            f"{session.started_at.astimezone().strftime('%Y-%m-%d %H:%M')}–"
            f"{session.ended_at.astimezone().strftime('%H:%M')}  "
            f"{session.duration_minutes:>4} min  {session.activity_count:>4} act.  "
            f"{', '.join(session.projects) or '—':<12}  {item.reason}"
        )
    return "\n".join(lines)


def run_list(args: argparse.Namespace, config: Config, client: CoreClient, state: JobState) -> int:
    now = datetime.now(timezone.utc)
    days = [args.date] if args.date is not None else None
    items = classify_sessions(
        client,
        now=now,
        config=config,
        model_id=config.model_id or "fake/summarizer",
        state=state,
        days=days,
    )
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": item.session.id,
                        "label": item.session.label,
                        "date": item.session.day.isoformat(),
                        "started_at": item.session.raw["started_at"],
                        "ended_at": item.session.raw["last_activity_at"],
                        "duration_minutes": item.session.duration_minutes,
                        "activity_count": item.session.activity_count,
                        "projects": item.session.projects,
                        "candidate": item.candidate,
                        "reason": item.reason,
                    }
                    for item in items
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_format_listing(items))
    return EXIT_OK


def run_summarize(
    args: argparse.Namespace, config: Config, client: CoreClient, state: JobState
) -> int:
    now = datetime.now(timezone.utc)
    summarizer = _summarizer(args, config)
    session = find_session(client, args.session_id, now=now, config=config, day=args.date)
    if session is None:
        print(f"session introuvable sur la période : {args.session_id}", file=sys.stderr)
        return EXIT_USAGE
    outcome = summarize_session(
        session,
        client=client,
        summarizer=summarizer,
        config=config,
        state=state,
        dry_run=args.dry_run,
        now=now,
    )
    print(f"{outcome.status} {session.label} {session.id} event_id={outcome.event_id}")
    if outcome.detail:
        print(outcome.detail)
    if outcome.event is not None:
        print(json.dumps(outcome.event, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK if outcome.status in {"dry_run", "created", "duplicate", "already_known"} else EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config, client, state = _load(args)
        if args.command == "list":
            return run_list(args, config, client, state)
        return run_summarize(args, config, client, state)
    except ConfigError as exc:
        print(f"configuration : {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CoreUnavailable as exc:
        print(f"Core injoignable : {exc}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE
    except CoreError as exc:
        print(f"Core : {exc}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE


if __name__ == "__main__":
    raise SystemExit(main())
