"""pulse-intel : la commande avant le service (spec v2 §8, étapes 1 et 2).

    pulse-intel list [--date YYYY-MM-DD] [--json]
    pulse-intel summarize <id> [--date YYYY-MM-DD] [--dry-run] --fake FICHIER
    pulse-intel run [--once] --fake FICHIER
    pulse-intel show <id>|latest [--md]

Le vrai modèle arrive à l'étape 3 ; d'ici là ``--fake`` lit la sortie du
modèle dans un fichier et reste obligatoire pour ``summarize`` et ``run``.
Un Core arrêté donne un message et le code 2. Tout ce que la commande écrit
sous ``~/.pulse_intelligence`` est privé (umask 077).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import Config, ConfigError, config_home, load_config
from .core_client import CoreClient, CoreError, CoreUnavailable
from .llm.fake import FakeProvider
from .llm.provider import LLMProvider
from .provider_summarizer import ProviderSummarizer, prompt_path_for
from .selection import Classified, classify_sessions, find_session
from .session_summary import run_pass, summarize_session
from .state import JobState
from .summarizer import FakeSummarizer, Summarizer


EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INFRASTRUCTURE = 2
PRIVATE_UMASK = 0o077


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

    fake_help = "sortie du modèle lue dans ce fichier (pas de modèle réel avant l'étape 3)"

    summarize = commands.add_parser("summarize", help="résumer une session")
    summarize.add_argument("session_id")
    summarize.add_argument("--date", type=_parse_day, default=None)
    summarize.add_argument("--dry-run", action="store_true", help="tout sauf l'émission")
    summarize.add_argument("--fake", type=Path, default=None, help=fake_help)

    run = commands.add_parser("run", help="résumer toutes les candidates")
    run.add_argument("--once", action="store_true", help="un seul passage (sinon un passage toutes les tick_minutes)")
    run.add_argument("--fake", type=Path, default=None, help=fake_help)

    show = commands.add_parser("show", help="afficher un résumé")
    show.add_argument("target", help="identifiant de session, ou « latest »")
    show.add_argument("--md", action="store_true", help="la reprise seule, en trois lignes")
    return parser


def _load(args: argparse.Namespace) -> tuple[Config, CoreClient, JobState]:
    config = load_config(args.config)
    if args.core_url:
        config = Config(**{**config.__dict__, "core_url": args.core_url})
    client = CoreClient(config.core_url)
    state_path = args.state or config_home() / "state.json"
    return config, client, JobState.load(state_path)


def _now() -> datetime:
    """L'unique horloge de la CLI.

    Tout ce qui est sous la CLI accepte déjà un `now` explicite — `lookback_days`,
    `classify_sessions`, `find_session`, `run_pass`. Seule la CLI lisait l'heure
    en quatre endroits, dont un qui ne la transmettait pas à `run_pass`. La
    fenêtre de sélection valant « aujourd'hui plus la veille », une suite dont
    les fixtures portent une date fixe passait le jour où elle a été écrite puis
    échouait deux jours plus tard, sans qu'une ligne de code ait bougé. Une
    seule source, remplaçable par les tests, referme la couture.
    """
    return datetime.now(timezone.utc)


def _provider(config: Config) -> LLMProvider:
    """Le provider désigné par `llm_provider`, et rien d'autre.

    Les deux implémentations réseau et locale arrivent aux PR suivantes ; le
    message dit laquelle manque plutôt que de laisser tomber sur un défaut
    silencieux.
    """
    choice = config.llm_provider.strip()
    if not choice:
        raise ConfigError(
            "aucun modèle disponible : passe --fake FICHIER, ou choisis un "
            "provider dans config.toml (llm_provider = \"fake\" | "
            '"openai-compatible" | "mlx")'
        )
    if choice == "fake":
        return FakeProvider()
    if choice in {"openai-compatible", "mlx"}:
        raise ConfigError(
            f"llm_provider = {choice!r} n'est pas encore implémenté "
            "(spec 2026-09-05-llm-provider v2, §13) ; "
            'utilise "fake" en attendant'
        )
    raise ConfigError(
        f"llm_provider inconnu : {choice!r} "
        '(attendu : "fake", "openai-compatible" ou "mlx")'
    )


def _summarizer(args: argparse.Namespace, config: Config) -> Summarizer:
    # `--fake FICHIER` court-circuite la couche modèle : le test fournit
    # directement la sortie. Chemin livré à l'étape 2, inchangé.
    if args.fake is not None:
        return FakeSummarizer(
            outputs=args.fake.read_text(encoding="utf-8"),
            model_id=config.model_id or "fake/summarizer",
        )
    provider = _provider(config)
    return ProviderSummarizer(
        provider=provider,
        model_id=config.model_id or f"{provider.name}/provider",
        prompt_path=prompt_path_for(config.prompt_version),
        max_tokens=config.llm_max_tokens,
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
    now = _now()
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
    now = _now()
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


def run_run(args: argparse.Namespace, config: Config, client: CoreClient, state: JobState) -> int:
    summarizer = _summarizer(args, config)
    while True:
        report = run_pass(client, summarizer, config, state, now=_now())
        stamp = _now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{stamp}] candidates={report.candidates} created={report.count('created')} "
            f"duplicate={report.count('duplicate')} failed={report.count('failed')} "
            f"given_up={report.count('given_up')}"
        )
        for outcome in report.outcomes:
            line = f"  {outcome.status} {outcome.session_id} event_id={outcome.event_id}"
            if outcome.detail:
                line += f" — {outcome.detail}"
            print(line)
        if report.error:
            print(f"Core injoignable : {report.error}", file=sys.stderr)
            return EXIT_INFRASTRUCTURE
        if args.once:
            return EXIT_OK
        try:
            time.sleep(max(1, config.tick_minutes) * 60)
        except KeyboardInterrupt:
            return EXIT_OK


def _reprise_markdown(reprise: dict[str, Any]) -> str:
    return "\n".join(str(reprise.get(key, "—")) for key in ("doing", "stopped_at", "open"))


def run_show(args: argparse.Namespace, config: Config, client: CoreClient, state: JobState) -> int:
    if args.target == "latest":
        # Core est la vérité : le dernier résumé qu'il connaît, quel que soit
        # le processus qui l'a produit.
        latest = client.get_context().get("last_session_summary")
        if not isinstance(latest, dict):
            print("aucun résumé de session dans Core", file=sys.stderr)
            return EXIT_USAGE
        if args.md:
            print(_reprise_markdown(latest.get("reprise", {})))
        else:
            print(json.dumps(latest, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_OK

    events = state.events_for(args.target)
    if events:
        event = events[-1]
        reprise = event.get("details", {}).get("reprise", {})
    else:
        latest = client.get_context().get("last_session_summary")
        if not isinstance(latest, dict) or latest.get("id") != args.target:
            print(f"aucun résumé connu pour la session {args.target}", file=sys.stderr)
            return EXIT_USAGE
        event = latest
        reprise = latest.get("reprise", {})
    if args.md:
        print(_reprise_markdown(reprise))
    else:
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(PRIVATE_UMASK)
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config, client, state = _load(args)
        if args.command == "list":
            return run_list(args, config, client, state)
        if args.command == "summarize":
            return run_summarize(args, config, client, state)
        if args.command == "run":
            return run_run(args, config, client, state)
        return run_show(args, config, client, state)
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
