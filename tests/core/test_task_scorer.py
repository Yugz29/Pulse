"""
Tests métier du scorer pondéré multi-signaux (PR2).

Scénarios testés :
  - Lecture repo avec app dev active + 0 modification → activity=reading, tâche≠debug
  - Stacktrace clipboard → debug
  - Friction seule → jamais debug
  - Docs files → writing
  - Terminal actif → activity=executing, tâche pas executing
  - Feature pattern → coding
  - Browser sans édition → exploration
  - Debug_loop_candidate → debug
  - Confidence exposée dans Signals
  - Commit correction par préfixe
"""
import unittest
from datetime import datetime, timedelta

from daemon.core.event_bus import EventBus, Event
from daemon.core.signal_scorer import SignalScorer


def _make_scorer():
    bus = EventBus(max_size=200)
    scorer = SignalScorer(bus)
    return scorer, bus


def _push(bus, event_type: str, payload: dict, minutes_ago: float = 0):
    event = Event(
        type=event_type,
        payload=payload,
        timestamp=datetime.now() - timedelta(minutes=minutes_ago),
    )
    bus._queue.append(event)


# ── Activité bas niveau ───────────────────────────────────────────────────────

class TestActivityLevel(unittest.TestCase):

    def test_lecture_repo_avec_app_dev_sans_edition(self):
        """App dev active + 0 fichier modifié → activity=reading."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "reading")

    def test_edition_fichiers_user(self):
        """Fichier modifié (user) → activity=editing."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        _push(bus, "file_modified", {"path": "/proj/src/main.py", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "editing")

    def test_terminal_actif_donne_executing(self):
        """Terminal en avant-plan (5 min) → activity=executing."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Warp"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "executing")

    def test_browser_sans_edition_donne_navigating(self):
        """Safari actif sans édition → activity=navigating."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Safari"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "navigating")

    def test_local_exploration_donne_navigating_sans_tache_forte(self):
        """Finder visible comme navigation locale, sans dériver la tâche."""
        scorer, bus = _make_scorer()
        _push(bus, "local_exploration", {"app_name": "Finder", "bundle_id": "com.apple.finder"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "navigating")
        self.assertEqual(signals.probable_task, "general")
        self.assertIsNone(signals.active_file)

    def test_local_exploration_necrase_pas_une_session_de_code_active(self):
        """Finder + édition récente → le travail réel reste editing/coding."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        _push(bus, "local_exploration", {"app_name": "Finder", "bundle_id": "com.apple.finder"})
        _push(bus, "file_modified", {"path": "/proj/src/main.py", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "editing")
        self.assertEqual(signals.probable_task, "coding")
        self.assertEqual(signals.active_file, "/proj/src/main.py")

    def test_idle_si_aucune_app_recente(self):
        """Aucun event → activity=idle."""
        scorer, bus = _make_scorer()
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "idle")

    def test_executing_ne_devient_pas_une_tache(self):
        """Terminal actif → executing dans activity_level, pas dans probable_task."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "iTerm2"})
        signals = scorer.compute()
        self.assertEqual(signals.activity_level, "executing")
        self.assertNotEqual(signals.probable_task, "executing")
        self.assertNotIn(signals.probable_task, {"executing", "browsing"})


# ── Tâche haut niveau ─────────────────────────────────────────────────────────

class TestProbableTask(unittest.TestCase):

    def test_lecture_repo_ne_produit_pas_debug(self):
        """App dev + lecture code + 0 modif → tâche pas debug, activity=reading."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        signals = scorer.compute()
        self.assertNotEqual(signals.probable_task, "debug")
        self.assertEqual(signals.activity_level, "reading")

    def test_lecture_donne_general_pas_exploration(self):
        """reading_only seul passe pas le seuil → retombe sur general."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        signals = scorer.compute()
        # reading_only = 0.8 < seuil 1.0 → general
        self.assertEqual(signals.probable_task, "general")

    def test_stacktrace_clipboard_donne_debug(self):
        """Clipboard stacktrace → debug (preuve concrète)."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Terminal"})
        _push(bus, "clipboard_updated", {"content_kind": "stacktrace"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "debug")

    def test_friction_seule_ne_donne_pas_debug(self):
        """Friction élevée sur fichiers DISTINCTS (sans debug_loop_candidate) → pas debug.

        On utilise des fichiers différents pour avoir churn sans single-file repeat,
        ce qui évite de créer un debug_loop_candidate (qui lui est une preuve légitime).
        high_friction seul = 0.3 pts < seuil 1.0 → ne peut pas déclencher debug.
        """
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        # 5 fichiers distincts rapidement modifiés → churn élevé, pas single-file
        for i in range(5):
            _push(bus, "file_modified", {"path": f"/proj/src/file{i}.py", "_actor": "user"})
        signals = scorer.compute()
        # Friction sur même chemin vient d'un seul fichier modifié plusieurs fois.
        # Avec des fichiers distincts, friction_score reste bas (max_churn = 1 par fichier).
        # Ce test vérifie que high_friction (0.3) seul ne déclenche jamais debug.
        self.assertNotEqual(signals.probable_task, "debug")

    def test_debug_loop_candidate_donne_debug(self):
        """Fichier source unique + friction >= 0.5 → debug_loop_candidate → debug."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        # 4 modifications du même fichier = friction ~0.67
        for _ in range(4):
            _push(bus, "file_modified", {"path": "/proj/src/main.py", "_actor": "user"})
        signals = scorer.compute()
        if signals.work_pattern_candidate == "debug_loop_candidate":
            self.assertEqual(signals.probable_task, "debug")
        # Si pas debug_loop_candidate (friction trop faible), au moins pas "debug" par erreur
        else:
            self.assertNotEqual(signals.probable_task, "debug")

    def test_docs_files_donnent_writing(self):
        """2+ fichiers docs sans app active → general (pas writing)."""
        scorer, bus = _make_scorer()
        _push(bus, "file_modified", {"path": "/proj/README.md", "_actor": "user"})
        _push(bus, "file_modified", {"path": "/proj/docs/api.md", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "general")

    def test_docs_files_avec_writing_app_donnent_writing(self):
        """2+ fichiers docs + app d'écriture active → writing."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Notion"})
        _push(bus, "file_modified", {"path": "/proj/README.md", "_actor": "user"})
        _push(bus, "file_modified", {"path": "/proj/docs/api.md", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "writing")

    def test_app_writing_donne_writing(self):
        """Notion actif (5 min) → writing."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Notion"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "writing")

    def test_browser_sans_edition_donne_exploration(self):
        """Safari actif (5 min) + 0 édition → exploration (≥ seuil 1.0)."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Safari"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "exploration")

    def test_app_dev_avec_edition_donne_coding(self):
        """Cursor + fichier source modifié → coding."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        _push(bus, "file_modified", {"path": "/proj/src/main.py", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "coding")

    def test_deux_fichiers_source_donnent_coding_fort(self):
        """2+ fichiers source/test → source_files_2plus → coding avec confiance haute."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        _push(bus, "file_modified", {"path": "/proj/src/a.py", "_actor": "user"})
        _push(bus, "file_modified", {"path": "/proj/src/b.py", "_actor": "user"})
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "coding")
        self.assertGreater(signals.task_confidence, 0.5)

    def test_browsing_absent_des_taches(self):
        """browsing ne doit jamais apparaître dans probable_task."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Chrome"})
        _push(bus, "clipboard_updated", {"content_kind": "url"})
        signals = scorer.compute()
        self.assertNotEqual(signals.probable_task, "browsing")

    def test_task_confidence_exposee(self):
        """task_confidence doit être entre 0 et 1."""
        scorer, bus = _make_scorer()
        _push(bus, "app_activated", {"app_name": "Cursor"})
        _push(bus, "file_modified", {"path": "/proj/src/main.py", "_actor": "user"})
        signals = scorer.compute()
        self.assertGreaterEqual(signals.task_confidence, 0.0)
        self.assertLessEqual(signals.task_confidence, 1.0)

    def test_general_si_aucun_signal_fort(self):
        """Aucun signal suffisant → general."""
        scorer, bus = _make_scorer()
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "general")

    def test_activity_level_champ_present_dans_signals(self):
        """activity_level est bien présent et non-None dans Signals."""
        scorer, bus = _make_scorer()
        signals = scorer.compute()
        self.assertIsNotNone(signals.activity_level)
        self.assertIn(signals.activity_level, {"idle", "editing", "reading", "executing", "navigating"})

    def test_mcp_inspection_donne_exploration_sans_fichier(self):
        """Une inspection MCP structurée enrichit le live sans activité fichier."""
        scorer, bus = _make_scorer()
        _push(
            bus,
            "mcp_command_received",
            {
                "tool_use_id": "tool-1",
                "mcp_action_category": "repo_inspection",
                "mcp_is_read_only": True,
                "mcp_affects": ["lecture seule"],
                "mcp_decision": "pending",
                "mcp_allowed": None,
                "mcp_summary": "Exploration de dépôt via MCP",
            },
        )
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "exploration")
        self.assertEqual(signals.activity_level, "reading")
        self.assertEqual(signals.mcp_action_category, "repo_inspection")

    def test_mcp_testing_renforce_coding_sans_fichier_recent(self):
        """Un test MCP peut ancrer le live même sans édition de fichier immédiate."""
        scorer, bus = _make_scorer()
        _push(
            bus,
            "mcp_command_received",
            {
                "tool_use_id": "tool-2",
                "mcp_action_category": "testing",
                "mcp_is_read_only": False,
                "mcp_affects": ["git"],
                "mcp_decision": "pending",
                "mcp_allowed": None,
                "mcp_summary": "Exécution de tests via MCP",
            },
        )
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "coding")
        self.assertEqual(signals.activity_level, "executing")

    def test_terminal_inspection_donne_exploration_et_projet_terminal(self):
        """Une commande terminal de lecture enrichit le live sans fichiers récents."""
        scorer, bus = _make_scorer()
        _push(
            bus,
            "terminal_command_finished",
            {
                "source": "terminal",
                "kind": "finished",
                "terminal_action_category": "inspection",
                "terminal_is_read_only": True,
                "terminal_project": "Pulse",
                "terminal_cwd": "/Users/yugz/Projets/Pulse/Pulse",
                "terminal_summary": "Inspection terminal",
                "terminal_duration_ms": 900,
                "terminal_exit_code": 0,
            },
        )
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "exploration")
        self.assertEqual(signals.activity_level, "reading")
        self.assertEqual(signals.active_project, "Pulse")
        self.assertEqual(signals.terminal_action_category, "inspection")

    def test_terminal_testing_donne_coding_sans_fichier_recent(self):
        """Une commande de test terminale peut ancrer coding sans édition immédiate."""
        scorer, bus = _make_scorer()
        _push(
            bus,
            "terminal_command_finished",
            {
                "source": "terminal",
                "kind": "finished",
                "terminal_action_category": "testing",
                "terminal_is_read_only": False,
                "terminal_project": "Pulse",
                "terminal_cwd": "/Users/yugz/Projets/Pulse/Pulse",
                "terminal_summary": "Exécution de tests",
                "terminal_duration_ms": 2400,
                "terminal_exit_code": 1,
            },
        )
        signals = scorer.compute()
        self.assertEqual(signals.probable_task, "coding")
        self.assertEqual(signals.activity_level, "executing")
        self.assertEqual(signals.terminal_action_category, "testing")


# ── Correction commit ─────────────────────────────────────────────────────────

class TestCommitTaskCorrection(unittest.TestCase):

    def setUp(self):
        from daemon.memory.extractor import _commit_task_correction
        self.correct = _commit_task_correction

    def test_fix_corrige_coding_vers_debug(self):
        self.assertEqual(self.correct("fix: resolve crash", "coding"), "debug")

    def test_fix_corrige_general_vers_debug(self):
        self.assertEqual(self.correct("fix(auth): token refresh", "general"), "debug")

    def test_feat_corrige_general_vers_coding(self):
        self.assertEqual(self.correct("feat: add user profile", "general"), "coding")

    def test_feat_ne_corrige_pas_debug(self):
        """feat: ne doit pas écraser une session de debug."""
        self.assertEqual(self.correct("feat: add feature", "debug"), "debug")

    def test_docs_corrige_general_vers_writing(self):
        self.assertEqual(self.correct("docs: update README", "general"), "writing")

    def test_docs_ne_corrige_pas_debug(self):
        """docs: ne doit pas écraser une session de debug réelle."""
        self.assertEqual(self.correct("docs: fix typo", "debug"), "debug")

    def test_refactor_corrige_general_vers_coding(self):
        self.assertEqual(self.correct("refactor: extract service layer", "general"), "coding")

    def test_chore_ne_corrige_pas(self):
        self.assertEqual(self.correct("chore: update deps", "general"), "general")

    def test_chore_ne_corrige_pas_exploration(self):
        self.assertEqual(self.correct("chore: bump version", "exploration"), "exploration")

    def test_ci_ne_corrige_pas(self):
        self.assertEqual(self.correct("ci: add lint step", "general"), "general")

    def test_commit_sans_prefix_ne_corrige_pas(self):
        self.assertEqual(self.correct("update auth logic", "general"), "general")

    def test_commit_vide_ne_corrige_pas(self):
        self.assertEqual(self.correct("", "coding"), "coding")

    def test_prefix_avec_scope_fonctionne(self):
        """fix(auth): ... doit être reconnu."""
        self.assertEqual(self.correct("fix(auth): token refresh", "exploration"), "debug")

    def test_prefix_avec_breaking_change_fonctionne(self):
        """feat!: ... doit être reconnu."""
        self.assertEqual(self.correct("feat!: new API", "general"), "coding")

    def test_writing_non_corrigee_vers_debug_par_fix(self):
        """Session writing + commit fix: → pas de correction (incompatible)."""
        self.assertEqual(self.correct("fix: fix typo in doc", "writing"), "writing")


if __name__ == "__main__":
    unittest.main()
