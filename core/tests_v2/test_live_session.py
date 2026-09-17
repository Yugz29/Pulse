"""Bloc « Session en cours » : les faits de la session ouverte, rangés sans modèle."""

from datetime import timezone

from daemon_v2.daily_trace import build_daily_trace, render_daily_trace_html
from daemon_v2.live_session import MAX_FAILURES, MAX_FILES, build_live_session
from tests_v2.test_context_snapshot import (
    PULSE,
    REFERENCE,
    agent_session,
    app,
    commit,
    file_changed,
    make_store,
    terminal,
    working_session,
)


def trace_of(store):
    return build_daily_trace(store, REFERENCE.date(), timezone.utc, now=REFERENCE)


def live(store):
    return build_live_session(trace_of(store))


def page(store, **options) -> str:
    return render_daily_trace_html(trace_of(store), **options)


def block(store) -> str:
    html = page(store)
    assert html.count('id="session-en-cours"') == 1
    return html.split('id="session-en-cours"', 1)[1].split("</section>", 1)[0]


# --- Présence du bloc ---------------------------------------------------------------


def test_no_open_session_means_no_block(tmp_path):
    # Une session d'hier soir, close depuis longtemps : rien d'ouvert.
    store = make_store(tmp_path, *working_session(offset=-600))

    assert live(store) is None
    html = page(store)
    assert 'id="session-en-cours"' not in html
    assert 'href="#session-en-cours"' not in html
    assert 'id="maintenant"' in html


def test_empty_store_has_no_block(tmp_path):
    store = make_store(tmp_path)

    assert live(store) is None
    assert 'id="session-en-cours"' not in page(store)


def test_archive_page_never_shows_the_block(tmp_path):
    store = make_store(tmp_path, *working_session())

    assert 'id="session-en-cours"' not in page(store, archive_mode=True)


def test_open_session_without_notable_facts_says_so(tmp_path):
    # Ouverte, mais ni commit, ni fichier, ni test, ni échec, ni agent.
    store = make_store(
        tmp_path,
        app(-20, "Terminal"),
        terminal(-18, "ls"),
        terminal(-10, "git status"),
    )

    view = live(store)
    assert view is not None
    assert view["commits"] == [] and view["files"] == [] and view["failures"] == []
    assert view["last_test"] is None and view["agent_sessions"] == []
    html = block(store)
    for sentence in (
        "Aucun commit dans cette session.",
        "Aucun fichier modifié dans cette session.",
        "Aucune commande de test observée.",
        "Aucune commande en échec observée.",
        "Aucune session d’agent terminée",
    ):
        assert sentence in html
    assert "summary-fact" not in html
    assert 'href="#session-en-cours"' in page(store)


# --- Chaque type de fait --------------------------------------------------------------


def test_commits_are_listed_with_their_anchor_and_first_line(tmp_path):
    store = make_store(tmp_path, *working_session())

    view = live(store)
    assert [c["hash"] for c in view["commits"]] == ["6264d1a5058b4fa3"]
    ref = view["commits"][0]["ref"]
    html = block(store)
    assert f'id="fait-live-{ref}"><code>{ref}</code> · commit · <code>6264d1a</code> · branche main' in html
    assert '<div class="fact-subject">chore: restructuration</div>' in html
    # Même affichage que les faits cités : message complet replié.
    assert '<details class="fact-message"><summary>message complet</summary>' in html


def test_files_are_grouped_by_path_most_touched_first(tmp_path):
    store = make_store(tmp_path, *working_session())

    view = live(store)
    assert [entry["path"] for entry in view["files"]][0] == "core/README.md"
    readme = view["files"][0]
    # Deux faits pour le même chemin (une commande les sépare) : réunis.
    assert readme["count"] == 2 and len(readme["refs"]) == 2
    assert view["file_count"] == 3
    html = block(store)
    assert "<h3>Fichiers les plus touchés (3)</h3>" in html
    first, second = readme["refs"]
    assert (
        f'id="fait-live-{first}"><code>{first}</code>, <code>{second}</code> · fichier · '
        "<code>core/README.md</code> · modifié ×2"
    ) in html
    assert "<code>docs/VISION.md</code> · créé ×1" in html


def test_only_the_most_touched_files_are_listed(tmp_path):
    events = [app(-30, "Code")] + [
        file_changed(-29 + index / 10, f"src/f{index}.py") for index in range(MAX_FILES + 3)
    ]
    store = make_store(tmp_path, terminal(-31, "ls"), *events)

    view = live(store)
    assert len(view["files"]) == MAX_FILES and view["file_count"] == MAX_FILES + 3
    assert "et 3 autre(s) fichier(s), moins touché(s)." in block(store)


def test_last_test_is_the_latest_test_command(tmp_path):
    store = make_store(
        tmp_path,
        terminal(-40, "pytest -q", exit_code=1),
        terminal(-30, "make build"),
        terminal(-20, "pytest -q", exit_code=0),
    )

    view = live(store)
    assert view["last_test"]["exit_code"] == 0 and view["test_count"] == 2
    assert view["failed_test_count"] == 1
    html = block(store).split("<h3>Dernier test</h3>", 1)[1].split("<h3>", 1)[0]
    assert "commande · code 0" in html and "<pre>pytest -q</pre>" in html
    assert "2 commande(s) de test dans la session, dont 1 en échec." in html


def test_failures_are_raw_latest_first_and_never_called_resolved(tmp_path):
    # Le même test échoue puis réussit : l'échec reste listé, tel quel.
    store = make_store(
        tmp_path,
        terminal(-40, "pytest -q", exit_code=1),
        terminal(-30, "make lint", exit_code=2),
        terminal(-20, "pytest -q", exit_code=0),
        terminal(-10, "make dev", exit_code=130),
    )

    view = live(store)
    assert [f["command"] for f in view["failures"]] == ["make lint", "pytest -q"]
    assert view["failure_count"] == 2  # 130 est une interruption, pas un échec
    html = block(store).split("<h3>Commandes en échec (2)</h3>", 1)[1].split("<h3>", 1)[0]
    assert html.index("make lint") < html.index("pytest -q")
    assert "code 2" in html and "code 1" in html and f"cwd <code>{PULSE}</code>" in html
    assert "Core ne dit pas si un échec a été corrigé depuis." in html
    lowered = html.lower()
    for word in ("résolu", "dépassé", "resolved", "superseded"):
        assert word not in lowered


def test_older_failures_are_counted_not_listed(tmp_path):
    store = make_store(
        tmp_path,
        *[terminal(-15 + index, f"false {index}", exit_code=1) for index in range(MAX_FAILURES + 2)],
    )

    view = live(store)
    assert len(view["failures"]) == MAX_FAILURES and view["failure_count"] == MAX_FAILURES + 2
    assert "et 2 échec(s) plus ancien(s)." in block(store)


def test_agent_sessions_ended_since_the_session_started_are_listed(tmp_path):
    store = make_store(
        tmp_path,
        agent_session(-300, ended_minutes=-280, first_prompt="Avant la session"),
        *working_session(),
        agent_session(-55, ended_minutes=-35, first_prompt="Pendant la session"),
    )

    view = live(store)
    assert [a["summary"] for a in view["agent_sessions"]] == [
        "Agent session (claude-code): Pendant la session"
    ]
    html = block(store)
    assert "<h3>Sessions d’agent terminées (1)</h3>" in html
    assert "Pendant la session" in html and "Avant la session" not in html
    assert "elles ne composent pas la session de travail" in html


def test_every_listed_fact_has_a_unique_anchor_and_no_script(tmp_path):
    store = make_store(
        tmp_path,
        *working_session(),
        agent_session(-55, ended_minutes=-35),
    )

    html = block(store)
    anchors = [chunk.split('"', 1)[0] for chunk in html.split(' id="fait-live-')[1:]]
    assert len(anchors) >= 6 and len(anchors) == len(set(anchors))
    # Le dernier test a échoué : listé deux fois, sous deux ancres distinctes.
    assert sum(anchor.startswith("test-") for anchor in anchors) == 1
    assert "<script" not in html and "onclick" not in html
    # Le bloc renvoie à la chronologie entière de la même session.
    index = live(store)["session_index"]
    assert f'href="#session-{index}"' in html and f'id="session-{index}"' in page(store)


# --- Échappement ------------------------------------------------------------------------


def test_block_escapes_every_observed_text(tmp_path):
    store = make_store(
        tmp_path,
        terminal(-40, "echo '<img src=x onerror=1>' && false", exit_code=1),
        file_changed(-30, "docs/<b>gras</b>.md"),
        commit(-20, "abc1234", "fix: <script>alert(1)</script>\n\nCorps & suite.", branch="<i>b</i>"),
        agent_session(-15, ended_minutes=-12, first_prompt="<u>demande</u>"),
    )

    html = block(store)

    for raw in ("<img src=x", "<b>gras</b>", "<script>alert(1)</script>", "<i>b</i>", "<u>demande</u>"):
        assert raw not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "docs/&lt;b&gt;gras&lt;/b&gt;.md" in html
    assert "&lt;u&gt;demande&lt;/u&gt;" in html


# --- Rien n'est écrit, rien d'autre ne change -----------------------------------------


def test_building_the_block_writes_nothing(tmp_path):
    store = make_store(tmp_path, *working_session())
    before = store.latest_activity_id()

    page(store)

    assert store.latest_activity_id() == before
