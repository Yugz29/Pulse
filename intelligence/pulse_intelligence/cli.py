"""pulse-intel : la commande avant le service (spec v2 §8, étapes 1 et 2).

    pulse-intel list [--date YYYY-MM-DD] [--json]
    pulse-intel summarize <id> [--date YYYY-MM-DD] [--dry-run] --fake FICHIER
    pulse-intel run [--once] --fake FICHIER
    pulse-intel show <id>|latest [--all] [--md|--json]

Le modèle est choisi par ``llm_provider`` dans la configuration — vide par
défaut, parce que le choix du modèle est une décision écrite. ``--fake
FICHIER`` court-circuite la couche modèle en lisant sa sortie dans un fichier.
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
from .evaluation import evaluate
from .llm.fake import FakeProvider
from .llm.openai_compatible import OpenAICompatibleProvider
from .llm.provider import LLMProvider, ProviderError
from .provider_summarizer import ProviderSummarizer, prompt_path_for
from .selection import Classified, classify_sessions, find_session
from .session_summary import run_pass, summarize_session
from .state import JobState, StateLocked
from .summarizer import FakeSummarizer, Summarizer


EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INFRASTRUCTURE = 2
# `run --once` : le passage s'est fait mais au moins une candidate est restée
# en `failed` (réessayable au prochain passage) ou en `given_up` (abandonnée,
# une intervention est nécessaire). Le code le plus grave gagne : l'exit
# code sert au monitoring humain, la reprise rejoue les `failed` de toute
# façon. Jusqu'au défaut 5 de l'audit, 3 couvre aussi bien une sortie modèle
# invalide qu'un provider indisponible.
EXIT_PARTIAL = 3
EXIT_GIVEN_UP = 4
# `run` et `summarize` : un autre passage tient déjà l'état (décision
# 2026-09-06, exécution unique). Sortie immédiate, rien n'est attendu.
EXIT_LOCKED = 5
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

    show = commands.add_parser("show", help="afficher le dernier résumé d'une session")
    show.add_argument("target", help="identifiant de session (un préfixe suffit), ou « latest »")
    show.add_argument(
        "--all", action="store_true", help="tous les résumés coexistants de la session, du plus ancien au plus récent"
    )
    show.add_argument("--md", action="store_true", help="la reprise seule, en trois lignes")
    show.add_argument("--json", action="store_true", help="l'événement complet, en JSON")

    ev = commands.add_parser("eval", help="passer le modèle courant sur le corpus gelé")
    ev.add_argument("--provider", default=None, help="remplace llm_provider pour ce passage")
    ev.add_argument("--corpus", type=Path, default=None, help="dossier du corpus (défaut eval/corpus)")
    ev.add_argument("--out", type=Path, default=None, help="dossier de sortie (défaut eval/out)")
    return parser


def _load(args: argparse.Namespace) -> tuple[Config, CoreClient, JobState]:
    config = load_config(args.config)
    if args.core_url:
        config = Config(**{**config.__dict__, "core_url": args.core_url})
    client = CoreClient(config.core_url)
    state_path = args.state or config_home() / "state.json"
    # Les commandes qui écrivent l'état prennent le verrou dès le chargement
    # et le gardent jusqu'à la fin ; `list` et `show` lisent sans verrou.
    lock = args.command in {"run", "summarize"}
    return config, client, JobState.load(state_path, lock=lock)


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

    L'implémentation locale arrive à la PR suivante ; le message dit laquelle
    manque plutôt que de laisser tomber sur un défaut silencieux.
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
    if choice == "openai-compatible":
        return OpenAICompatibleProvider.from_environment(
            fallback_base_url=config.llm_base_url,
            fallback_model=config.model_id,
            timeout_s=config.generation_timeout_s,
        )
    if choice == "mlx":
        from .llm.mlx import DEFAULT_MODEL, MLXProvider

        return MLXProvider(
            model=config.model_id or DEFAULT_MODEL,
            max_input_tokens=config.llm_max_input_tokens,
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
        # `config.model_id` sert de repli AU provider (voir `_provider`) ; ce
        # qui est enregistré est le modèle qui a réellement servi, sinon deux
        # modèles distants différents partageraient un même event_id.
        model_id=provider.model,
        prompt_path=prompt_path_for(config.prompt_version),
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperature,
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
            if outcome.status in {"failed", "given_up"}:
                # Bruyant : un refus (plafond d'entrée, modèle injoignable) ne
                # doit pas se fondre dans la liste — sur stderr, donc visible en
                # terminal et dans run.log sous launchd.
                print(f"  ⚠ {line.strip()}", file=sys.stderr)
            else:
                print(line)
        if report.error:
            print(f"Core injoignable : {report.error}", file=sys.stderr)
            return EXIT_INFRASTRUCTURE
        if args.once:
            if report.count("given_up"):
                return EXIT_GIVEN_UP
            if report.count("failed"):
                return EXIT_PARTIAL
            return EXIT_OK
        try:
            time.sleep(max(1, config.tick_minutes) * 60)
        except KeyboardInterrupt:
            return EXIT_OK


def _reprise_markdown(reprise: dict[str, Any]) -> str:
    return "\n".join(str(reprise.get(key, "—")) for key in ("doing", "stopped_at", "open"))


def _local_stamp(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not isinstance(value, str) or not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime(fmt)
    except ValueError:
        return value


def _card(
    details: dict[str, Any],
    *,
    previous_summary: dict[str, Any] | None,
    previous_known: bool,
) -> str:
    """Un résumé en fiche : la reprise, ce qui la qualifie, et le ``open``
    reçu en annexe juste sous le ``open`` produit — D1 se juge d'un coup d'œil.

    ``details`` est soit ``event["details"]`` de la copie locale, soit le
    ``last_session_summary`` de Core (moins de champs : « — » là où il manque).
    """
    reprise = details.get("reprise") or {}
    structured = details.get("structured") or {}
    session_id = details.get("session_id") or details.get("id") or "—"
    label = details.get("session_label") or details.get("label") or "—"
    started = _local_stamp(details.get("session_started_at"))
    ended = _local_stamp(details.get("session_ended_at"), "%H:%M")
    confidence = structured.get("confidence") or details.get("confidence") or "—"
    central = structured.get("central_files")

    lines = [
        f"session         {session_id}  {label}  {started}–{ended}",
        f"résumé          {details.get('prompt_version') or '—'}  {details.get('model_id') or '—'}"
        f"  généré {_local_stamp(details.get('generated_at'))}",
        f"confidence      {confidence}",
        f"doing           {reprise.get('doing', '—')}",
        f"stopped_at      {reprise.get('stopped_at', '—')}",
        f"open            {reprise.get('open', '—')}",
    ]
    if not previous_known:
        lines.append("  ↳ reçu        (annexe previous_summary inconnue : résumé antérieur à son enregistrement)")
    elif previous_summary is None:
        lines.append("  ↳ reçu        (aucune annexe previous_summary)")
    else:
        received = (previous_summary.get("reprise") or {}).get("open", "—")
        lines.append(
            f"  ↳ reçu        {received}"
            f"  [previous_summary {previous_summary.get('id') or '—'} {previous_summary.get('label') or ''}]".rstrip()
        )
    if isinstance(central, list):
        lines.append(f"central_files   {', '.join(central) if central else '[]'}")
    else:
        lines.append("central_files   —")
    return "\n".join(lines)


def _resolve_target(state: JobState, target: str) -> tuple[str | None, list[str]]:
    """L'identifiant complet visé par ``target`` (exact ou préfixe), ou les
    candidats si le préfixe est ambigu."""
    known = state.session_ids()
    if target in known:
        return target, []
    matches = [session_id for session_id in known if session_id.startswith(target)]
    if len(matches) == 1:
        return matches[0], []
    return None, matches


def _print_entries(args: argparse.Namespace, entries: list[dict[str, Any]]) -> None:
    if args.json:
        events = [entry["event"] for entry in entries]
        print(json.dumps(events if args.all else events[-1], ensure_ascii=False, indent=2, sort_keys=True))
        return
    selected = entries if args.all else entries[-1:]
    blocks = []
    for entry in selected:
        details = entry["event"].get("details", {})
        if args.md:
            blocks.append(_reprise_markdown(details.get("reprise", {})))
        else:
            blocks.append(
                _card(
                    details,
                    previous_summary=entry.get("previous_summary"),
                    previous_known="previous_summary" in entry,
                )
            )
    if args.all and not args.md:
        session_id = entries[-1]["event"].get("details", {}).get("session_id", "?")
        print(f"{len(entries)} résumé(s) pour {session_id}, du plus ancien au plus récent\n")
    print("\n\n".join(blocks))


def _print_core_summary(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.md:
        print(_reprise_markdown(summary.get("reprise", {})))
    else:
        # Core ne conserve pas l'annexe : on ne sait pas ce que le modèle a reçu.
        print(_card(summary, previous_summary=None, previous_known=False))


def run_show(args: argparse.Namespace, config: Config, client: CoreClient, state: JobState) -> int:
    if args.target == "latest":
        # Core est la vérité : le dernier résumé qu'il connaît, quel que soit
        # le processus qui l'a produit.
        latest = client.get_context().get("last_session_summary")
        if not isinstance(latest, dict):
            print("aucun résumé de session dans Core", file=sys.stderr)
            return EXIT_USAGE
        if args.md or args.json or not args.all:
            # Compatibilité : `show latest` sans option rend l'événement Core en JSON.
            if args.md:
                print(_reprise_markdown(latest.get("reprise", {})))
            else:
                print(json.dumps(latest, ensure_ascii=False, indent=2, sort_keys=True))
            return EXIT_OK
        entries = state.summaries_for(str(latest.get("id")))
        if not entries:
            _print_core_summary(args, latest)
            return EXIT_OK
        _print_entries(args, entries)
        return EXIT_OK

    session_id, ambiguous = _resolve_target(state, args.target)
    if ambiguous:
        print(
            f"préfixe ambigu : {args.target} désigne {len(ambiguous)} sessions "
            f"({', '.join(ambiguous)})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if session_id is not None:
        _print_entries(args, state.summaries_for(session_id))
        return EXIT_OK

    latest = client.get_context().get("last_session_summary")
    latest_id = str(latest.get("id", "")) if isinstance(latest, dict) else ""
    if not latest_id or not latest_id.startswith(args.target):
        print(f"aucun résumé connu pour la session {args.target}", file=sys.stderr)
        return EXIT_USAGE
    _print_core_summary(args, latest)
    return EXIT_OK


def run_eval(args: argparse.Namespace, config: Config) -> int:
    """Passe le modèle courant sur le corpus gelé. Ne touche pas Core."""
    if args.provider:
        config = Config(**{**config.__dict__, "llm_provider": args.provider})
    summarizer = _summarizer(argparse.Namespace(fake=None), config)
    if not isinstance(summarizer, ProviderSummarizer):
        print("eval exige un provider (llm_provider), pas --fake", file=sys.stderr)
        return EXIT_USAGE

    kwargs: dict[str, Any] = {"provider_name": summarizer.provider.name}
    if args.corpus is not None:
        kwargs["corpus_dir"] = args.corpus
    if args.out is not None:
        kwargs["out_dir"] = args.out
    outcomes, run_dir = evaluate(summarizer, now=_now(), **kwargs)

    for o in outcomes:
        mark = {"ok": "✓", "rejected": "✗", "failed": "!"}[o.status]
        dropped = f" [temp retirée]" if o.dropped_parameters else ""
        print(
            f"  {mark} {o.entry.label:<8} {o.entry.id}  "
            f"{(str(o.prompt_tokens) + 'tok') if o.prompt_tokens is not None else '—':>9}  "
            f"{(str(o.duration_ms) + 'ms') if o.duration_ms is not None else '—':>7}"
            f"{dropped}  {o.detail or o.entry.why[:38]}"
        )
    ok = sum(o.status == "ok" for o in outcomes)
    print(f"\n{ok}/{len(outcomes)} valides -> {run_dir}")
    return EXIT_OK if ok == len(outcomes) else EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(PRIVATE_UMASK)
    parser = _build_parser()
    args = parser.parse_args(argv)
    state: JobState | None = None
    try:
        if args.command == "eval":
            return run_eval(args, load_config(args.config))
        config, client, state = _load(args)
        if args.command == "list":
            return run_list(args, config, client, state)
        if args.command == "summarize":
            return run_summarize(args, config, client, state)
        if args.command == "run":
            return run_run(args, config, client, state)
        return run_show(args, config, client, state)
    except StateLocked as exc:
        print(f"état : {exc}", file=sys.stderr)
        return EXIT_LOCKED
    except ConfigError as exc:
        print(f"configuration : {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ProviderError as exc:
        # Une ProviderError n'arrive ici qu'à la construction du provider :
        # pendant un passage, ProviderSummarizer la traduit en SummarizerError
        # et summarize_session la traite session par session.
        print(f"modèle : {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CoreUnavailable as exc:
        print(f"Core injoignable : {exc}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE
    except CoreError as exc:
        print(f"Core : {exc}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE
    finally:
        if state is not None:
            state.release()


if __name__ == "__main__":
    raise SystemExit(main())
