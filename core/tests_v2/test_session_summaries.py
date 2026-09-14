"""Résumés stockés relus pour le journal : zones « Reprise » et « Résumés »."""

from datetime import date, datetime, timedelta, timezone

from daemon_v2.context_snapshot import build_context_snapshot, build_day_sessions
from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_html
from daemon_v2.main import create_app
from daemon_v2.models import Activity
from daemon_v2.session_summaries import build_summary_board
from tests_v2.test_context_snapshot import (
    PULSE,
    REFERENCE,
    at,
    make_store,
    terminal,
    working_session,
)


def summary(
    ended_minutes: int,
    *,
    session_id: str,
    started_minutes: int | None = None,
    prompt_version: str = "v6",
    doing: str = "Tu reconstruisais les sessions.",
    stopped_at: str = "Après le commit abc1234.",
    open_text: str = "Aucun point ouvert étayé par les faits de la session.",
    label: str = "work-1",
    open_items: list | None = None,
    generated_minutes: int | None = None,
) -> Activity:
    started = ended_minutes - 60 if started_minutes is None else started_minutes
    details = {
        "session_id": session_id,
        "source_event_ids_hash": session_id,
        "session_label": label,
        "session_date": at(started).date().isoformat(),
        "session_started_at": at(started).isoformat(),
        "session_ended_at": at(ended_minutes).isoformat(),
        "prompt_version": prompt_version,
        "model_id": "mlx-community/test-model",
        "generated_at": at(
            ended_minutes + 30 if generated_minutes is None else generated_minutes
        ).isoformat(),
        "reprise": {"doing": doing, "stopped_at": stopped_at, "open": open_text},
        "structured": {
            "project": "Pulse",
            "confidence": "medium",
            "central_files": ["core/daemon_v2/routes.py"],
        },
        "workspace": PULSE,
    }
    if open_items is not None:
        details["open_items"] = open_items
    return Activity("session_summary", at(ended_minutes), "intelligence", doing, details)


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def board(store, *, reference_at=REFERENCE):
    return build_summary_board(
        store, reference_at=reference_at, local_timezone=timezone.utc
    )


def closed_sessions(store, day: date) -> list[dict]:
    trace = build_daily_trace(store, day, timezone.utc, now=REFERENCE)
    return [
        session
        for session in trace["work_sessions"]
        if session["activity_kind"] == "work" and session["end_reason"] != "open"
    ]


def strong_session(start: int, *, minutes: int, activities: int) -> list[Activity]:
    """Des commandes seules, de ``start`` à ``start + minutes`` : une session
    de cette durée et de ce nombre d'activités exactement."""
    instants = [
        start + minutes * index / (activities - 1) for index in range(activities - 1)
    ]
    return [
        terminal(instant, f"echo {index}")
        for index, instant in enumerate([*instants, start + minutes])
    ]


YESTERDAY = (REFERENCE - timedelta(days=1)).date()


# --- Lecture du stockage --------------------------------------------------------


def test_activities_of_type_starts_with_what_latest_activity_of_type_returns(tmp_path):
    store = make_store(
        tmp_path,
        summary(-3000, session_id="aaaaaaaaaaaaaaaa"),
        summary(-1500, session_id="bbbbbbbbbbbbbbbb", prompt_version="v5"),
        summary(-1500, session_id="bbbbbbbbbbbbbbbb", prompt_version="v6"),
        summary(+30, session_id="cccccccccccccccc"),
    )

    listed = store.activities_of_type("session_summary", before=REFERENCE)
    latest = store.latest_activity_of_type("session_summary", before=REFERENCE)

    assert [item.details["prompt_version"] for item in listed] == ["v6", "v5", "v6"]
    assert listed[0].event_id == latest.event_id
    assert all(item.details["session_id"] != "cccccccccccccccc" for item in listed)


# --- Zone 1 : la même reprise que /context ---------------------------------------


def test_reprise_is_the_last_session_summary_of_the_context_api(tmp_path):
    store = make_store(
        tmp_path,
        summary(-3000, session_id="aaaaaaaaaaaaaaaa", doing="Ancien."),
        summary(-1500, session_id="bbbbbbbbbbbbbbbb", prompt_version="v5", doing="v5."),
        summary(-1500, session_id="bbbbbbbbbbbbbbbb", prompt_version="v6", doing="v6."),
        summary(+30, session_id="cccccccccccccccc", doing="Après maintenant."),
    )

    result = board(store)
    context = build_context_snapshot(
        store, reference_at=REFERENCE, local_timezone=timezone.utc
    )

    assert result["reprise"]["event_id"] == context["last_session_summary"]["event_id"]
    assert result["reprise"]["prompt_version"] == "v6"
    assert result["reprise"]["doing"] == "v6."
    assert result["reprise"]["age_minutes"] == context["last_session_summary"]["age_minutes"]
    assert result["summary_count"] == 3
    assert result["session_count"] == 2


def test_reprise_older_than_24_hours_is_marked_stale(tmp_path):
    fresh = make_store(tmp_path / "fresh", summary(-1439, session_id="aaaaaaaaaaaaaaaa"))
    stale = make_store(tmp_path / "stale", summary(-1441, session_id="aaaaaaaaaaaaaaaa"))

    assert board(fresh)["reprise"]["is_stale"] is False
    assert board(stale)["reprise"]["is_stale"] is True
    assert board(stale)["reprise"]["age_minutes"] == 1441


def test_every_prompt_generation_is_read_in_the_same_form(tmp_path):
    v1 = summary(-400, session_id="aaaaaaaaaaaaaaaa", prompt_version="v1")
    v7 = summary(
        -200,
        session_id="bbbbbbbbbbbbbbbb",
        prompt_version="v7",
        open_text="make test échoue encore.",
        open_items=[{"kind": "command_failure", "evidence": ["o7"], "scope": "session_end"}],
    )
    del v1.details["generated_at"]
    store = make_store(tmp_path, v1, v7)

    views = {
        view["prompt_version"]: view
        for day in board(store)["days"]
        for session in day["sessions"]
        for view in session["summaries"]
    }

    assert views["v1"]["open_items"] == []
    assert views["v1"]["generated_at"] is None
    assert views["v7"]["open"] == "make test échoue encore."
    assert views["v7"]["open_items"] == [{"kind": "command_failure", "evidence": ["o7"]}]
    assert views["v7"]["central_files"] == ["core/daemon_v2/routes.py"]
    assert views["v7"]["origin"] == "model_interpretation"


def test_without_any_summary_the_reprise_is_empty(tmp_path):
    result = board(make_store(tmp_path))

    assert result["reprise"] is None
    assert result["days"] == []
    assert result["unsummarized_sessions"] == []


# --- Zone 1 : sessions closes sans résumé ------------------------------------------


def test_every_unsummarized_closed_session_of_the_two_days_is_listed(tmp_path):
    store = make_store(
        tmp_path,
        *working_session(offset=-3 * 1440),  # hors des deux journées relues
        *working_session(offset=-1440),  # hier
        *working_session(offset=-300),  # aujourd'hui, 08:55
        *working_session(offset=-120),  # aujourd'hui, 11:55
        *working_session(offset=0),  # ouverte
    )
    yesterday = closed_sessions(store, (REFERENCE - timedelta(days=1)).date())
    today = closed_sessions(store, REFERENCE.date())
    assert len(yesterday) == 1 and len(today) == 2
    summarized_morning = today[0]
    store.append(
        summary(
            -305,
            session_id=summarized_morning["id"],
            started_minutes=-360,
        )
    )

    result = board(store)

    assert result["reprise"]["session_id"] == summarized_morning["id"]
    # Hier est antérieur au résumé affiché : listé quand même.
    assert [
        (item["id"], item["status"]) for item in result["unsummarized_sessions"]
    ] == [
        (today[1]["id"], "pending"),
        (yesterday[0]["id"], "missing"),
    ]
    listed = result["unsummarized_sessions"][0]
    assert listed["ended_at"] == at(-125).isoformat()
    # Du premier événement fort (pytest à -178) au dernier (fichier à -125).
    assert listed["started_at"] == at(-178).isoformat()
    assert listed["duration_minutes"] == 53
    assert listed["activity_count"] == len(today[1]["activities"])
    assert result["unsummarized_days"] == ["2026-09-02", "2026-09-01"]


def test_a_session_refused_before_the_displayed_summary_is_listed(tmp_path):
    # Le lot du matin résume la veille : il a refusé la session de 10 h et
    # résumé celle de 15 h.
    store = make_store(
        tmp_path,
        *working_session(offset=-1440 - 300),  # 10 h du cas réel : pas de résumé
        *working_session(offset=-1440 - 120),  # 15 h du cas réel : résumée
    )
    refused, summarized = closed_sessions(store, YESTERDAY)
    store.append(
        summary(-1440 - 125, session_id=summarized["id"], started_minutes=-1440 - 178)
    )

    result = board(store)
    reprise = reprise_zone(store)

    assert result["reprise"]["session_id"] == summarized["id"]
    assert _instant(refused["ended_at"]) < _instant(result["reprise"]["session_ended_at"])
    assert [
        (item["id"], item["status"]) for item in result["unsummarized_sessions"]
    ] == [(refused["id"], "missing")]
    assert "1 session(s) éligible(s) sans résumé" in reprise
    assert refused["id"] in reprise


def test_an_eligible_session_of_today_waits_for_the_morning_batch(tmp_path):
    store = make_store(tmp_path, *working_session(offset=-120))
    [session] = closed_sessions(store, REFERENCE.date())

    result = board(store)
    reprise = reprise_zone(store)

    assert [
        (item["id"], item["status"]) for item in result["unsummarized_sessions"]
    ] == [(session["id"], "pending")]
    assert 'class="summary-alert"' not in reprise
    assert session["id"] not in reprise
    assert "1 session(s) éligible(s) d’aujourd’hui, pas encore résumée(s)." in reprise


def test_a_session_is_set_aside_only_below_both_thresholds(tmp_path):
    # Spec du 2026-09-03, §7 : candidate si 10 min ou 30 activités.
    store = make_store(
        tmp_path,
        *strong_session(-1440 - 600, minutes=9, activities=29),
        *strong_session(-1440 - 400, minutes=9, activities=30),
        *strong_session(-1440 - 200, minutes=10, activities=29),
    )

    listed = board(store)["unsummarized_sessions"]
    served = build_day_sessions(
        store, day=YESTERDAY, reference_at=REFERENCE, local_timezone=timezone.utc
    )["sessions"]

    assert [
        (item["duration_minutes"], item["activity_count"], item["status"])
        for item in listed
    ] == [(10, 29, "missing"), (9, 30, "missing"), (9, 29, "below_threshold")]
    # Classées sur les grandeurs que /context/sessions sert à Intelligence.
    assert sorted(
        (item["id"], item["duration_minutes"], item["activity_count"])
        for item in listed
    ) == sorted(
        (session["id"], session["duration_minutes"], session["activity_count"])
        for session in served
    )


def test_without_summary_every_closed_session_of_the_two_days_is_listed(tmp_path):
    store = make_store(
        tmp_path,
        *working_session(offset=-3 * 1440),
        *working_session(offset=-1440),
        *working_session(offset=-120),
    )

    result = board(store)

    assert result["reprise"] is None
    assert [
        (item["date"], item["status"]) for item in result["unsummarized_sessions"]
    ] == [("2026-09-02", "pending"), ("2026-09-01", "missing")]


def test_a_session_whose_identity_changed_is_covered_by_an_overlapping_summary(tmp_path):
    store = make_store(tmp_path, *working_session(offset=-120))
    [session] = closed_sessions(store, REFERENCE.date())
    # Résumé produit sous une reconstruction antérieure : autre identifiant,
    # bornes qui recouvrent la session d'aujourd'hui. Il est plus ancien
    # (fin à -130) que la session : sans le chevauchement, elle serait listée.
    store.append(summary(-130, session_id="ffffffffffffffff", started_minutes=-175))

    result = board(store)

    assert result["reprise"]["session_id"] != session["id"]
    assert result["unsummarized_sessions"] == []


# --- Zone 2 : tous les résumés -----------------------------------------------------


def test_summaries_are_grouped_by_day_then_session_latest_generation_first(tmp_path):
    store = make_store(
        tmp_path,
        summary(-1500, session_id="aaaaaaaaaaaaaaaa", prompt_version="v2", label="work-3"),
        summary(-1500, session_id="aaaaaaaaaaaaaaaa", prompt_version="v5", label="work-3"),
        summary(-1500, session_id="aaaaaaaaaaaaaaaa", prompt_version="v6", label="work-3"),
        summary(-1700, session_id="bbbbbbbbbbbbbbbb", label="work-2"),
        summary(-200, session_id="cccccccccccccccc", label="work-1"),
    )

    days = board(store)["days"]

    assert [day["date"] for day in days] == ["2026-09-02", "2026-09-01"]
    assert [s["session_id"] for s in days[1]["sessions"]] == [
        "aaaaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbbbb",
    ]
    versions = [view["prompt_version"] for view in days[1]["sessions"][0]["summaries"]]
    assert versions == ["v6", "v5", "v2"]


# --- Rendu -------------------------------------------------------------------------


def render(store, trace_day=None):
    trace = build_daily_trace(
        store, trace_day or REFERENCE.date(), timezone.utc, now=REFERENCE
    )
    return render_daily_trace_html(trace, summary_board=board(store))


def reprise_zone(store) -> str:
    return render(store).split('id="reprise"', 1)[1].split("</section>", 1)[0]


def test_rendering_escapes_model_text_and_shows_every_prompt_version(tmp_path):
    store = make_store(
        tmp_path,
        summary(
            -1500,
            session_id="aaaaaaaaaaaaaaaa",
            prompt_version="v5",
            doing="<script>alert(1)</script> & co",
        ),
        summary(-1500, session_id="aaaaaaaaaaaaaaaa", prompt_version="v6"),
    )

    html = render(store)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html
    resumes = html.split('id="resumes"', 1)[1].split("</section>", 1)[0]
    assert resumes.count('<span class="prompt-version">v6</span>') == 2
    assert resumes.count('<span class="prompt-version">v5</span>') == 2
    assert "2 versions coexistantes" in resumes
    assert "<details " in resumes and "<details open" not in resumes
    assert 'id="resume-session-aaaaaaaaaaaaaaaa"' in resumes


def test_rendering_of_the_reprise_zone(tmp_path):
    store = make_store(
        tmp_path,
        *working_session(offset=-120),
        summary(
            -1500,
            session_id="aaaaaaaaaaaaaaaa",
            open_text="Relancer make test.",
            open_items=[{"kind": "requested", "evidence": ["agent_request:0"]}],
        ),
    )

    html = render(store)
    reprise = html.split('id="reprise"', 1)[1].split("</section>", 1)[0]

    assert "<dt>En cours</dt><dd>Tu reconstruisais les sessions.</dd>" in reprise
    assert "<dt>Arrêté à</dt><dd>Après le commit abc1234.</dd>" in reprise
    assert "<dt>Reste ouvert</dt><dd>Relancer make test.</dd>" in reprise
    assert "<code>requested</code> (agent_request:0)" in reprise
    assert "Résumé de plus de 24 h" in reprise
    assert "il y a 1 j 1 h" in reprise
    assert "1 session(s) éligible(s) d’aujourd’hui, pas encore résumée(s)." in reprise
    assert "mlx-community/test-model" in reprise
    assert "interprétation du modèle" in reprise


def test_the_reprise_comes_before_the_health_signals(tmp_path):
    store = make_store(
        tmp_path,
        *strong_session(-1440 - 600, minutes=4, activities=10),  # hier, sous les seuils
        *working_session(offset=-1440 - 120),  # hier, éligible, sans résumé
        *working_session(offset=-120),  # aujourd'hui, éligible
        summary(-300, session_id="aaaaaaaaaaaaaaaa", started_minutes=-360),
    )

    listed = board(store)["unsummarized_sessions"]
    reprise = reprise_zone(store)
    alert = reprise.split('class="summary-alert"', 1)[1].split("</div>", 1)[0]

    assert [item["status"] for item in listed] == ["pending", "missing", "below_threshold"]
    assert (
        reprise.index("<dt>En cours</dt>")
        < reprise.index('class="summary-alert"')
        < reprise.index('<p class="meta">')
    )
    assert "1 session(s) éligible(s) sans résumé" in alert
    assert listed[1]["id"] in alert
    assert listed[0]["id"] not in reprise and listed[2]["id"] not in reprise
    assert (
        '<p class="meta">1 session(s) éligible(s) d’aujourd’hui, pas encore résumée(s). '
        "1 session(s) close(s) sous les seuils de candidature (moins de 10 min et "
        "moins de 30 activités), sans résumé prévu. "
        "Journées relues : 2026-09-02 et 2026-09-01.</p>"
    ) in reprise


def test_sessions_below_the_thresholds_never_raise_the_alert(tmp_path):
    # Page du 2026-09-14 : des sessions de la veille de 0 à 4 min et de 4 à 19
    # activités, en rouge avant « En cours », jamais résumables.
    store = make_store(
        tmp_path,
        *strong_session(-1440 - 600, minutes=0, activities=4),
        *strong_session(-1440 - 400, minutes=4, activities=10),
        *strong_session(-1440 - 200, minutes=3, activities=19),
        summary(-300, session_id="aaaaaaaaaaaaaaaa", started_minutes=-360),
    )

    html = render(store)
    reprise = reprise_zone(store)

    assert [item["status"] for item in board(store)["unsummarized_sessions"]] == [
        "below_threshold"
    ] * 3
    assert 'class="summary-alert"' not in html
    assert reprise.index("<dt>En cours</dt>") < reprise.index('<p class="meta">')
    assert "3 session(s) close(s) sous les seuils de candidature" in reprise


def test_zones_come_first_and_the_deterministic_resume_is_renamed(tmp_path):
    app = create_app(tmp_path / "trace.db")
    client = app.test_client()
    client.post(
        "/activities",
        json={
            "type": "terminal_finished",
            "command": "pytest -q",
            "exit_code": 0,
            "cwd": "/project",
        },
    )

    html = client.get("/").get_data(as_text=True)

    assert html.index('id="reprise"') < html.index('id="resumes"')
    assert html.index('id="resumes"') < html.index('id="maintenant"')
    assert html.index('id="maintenant"') < html.index('id="faits-de-reprise"')
    assert "Aucun résumé de session stocké." in html
    nav = html.split("</nav>", 1)[0]
    assert nav.index('href="#reprise"') < nav.index('href="#resumes"')
    assert nav.index('href="#resumes"') < nav.index('href="#maintenant"')


def test_archive_day_renders_no_summary_zone(tmp_path):
    store = make_store(tmp_path, summary(-200, session_id="aaaaaaaaaaaaaaaa"))
    trace = build_daily_trace(store, REFERENCE.date(), timezone.utc, now=REFERENCE)

    html = render_daily_trace_html(trace, archive_mode=True, summary_board=board(store))

    assert 'id="reprise"' not in html
    assert 'id="resumes"' not in html
