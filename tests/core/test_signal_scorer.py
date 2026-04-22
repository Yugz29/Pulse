import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from daemon.core.event_bus import EventBus, Event
from daemon.core.signal_scorer import SignalScorer


class TestSignalScorer(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus(max_size=50)
        self.scorer = SignalScorer(self.bus)

    def _push(self, event_type: str, payload: dict, minutes_ago: int = 0):
        event = Event(
            type=event_type,
            payload=payload,
            timestamp=datetime.now() - timedelta(minutes=minutes_ago),
        )
        self.bus._queue.append(event)

    def test_compute_retourne_signaux_de_base(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("clipboard_updated", {"content_kind": "code"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_project, "Pulse")
        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.probable_task, "coding")
        self.assertEqual(signals.clipboard_context, "code")
        self.assertEqual(signals.edited_file_count_10m, 1)
        self.assertEqual(signals.file_type_mix_10m["source"], 1)
        self.assertEqual(signals.dominant_file_mode, "single_file")

    def test_detecte_debug_si_stacktrace(self):
        self._push("app_activated", {"app_name": "Terminal"})
        self._push("clipboard_updated", {"content_kind": "stacktrace"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "debug")
        self.assertGreaterEqual(signals.friction_score, 0.3)

    def test_focus_deep_si_peu_de_switchs_et_plusieurs_edits(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/a.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/b.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "deep")

    def test_focus_scattered_si_beaucoup_de_switchs(self):
        apps = ["Cursor", "Safari", "Terminal", "Notion", "Chrome", "Arc"]
        for app in apps:
            self._push("app_activated", {"app_name": app})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "scattered")

    def test_compat_anciens_noms_devents(self):
        self._push("app_switch", {"app_name": "Xcode"})
        self._push("file_change", {"path": "/Users/yugz/Developer/MonApp/src/main.py"})
        self._push("clipboard_update", {"content_type": "text"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_project, "MonApp")
        self.assertIn("Xcode", signals.recent_apps)
        self.assertEqual(signals.clipboard_context, "text")

    def test_idle_prioritaire_si_evenement_idle_recent(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("user_idle", {"seconds": 420})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "idle")

    def test_forte_activite_fichiers_empeche_idle_et_retombe_a_normal(self):
        self._push("app_activated", {"app_name": "Cursor"}, minutes_ago=2)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/a.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/b.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/c.py"}, minutes_ago=1)
        self._push("user_idle", {"seconds": 420})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "normal")

    def test_idle_reste_possible_si_activite_fichiers_est_trop_faible(self):
        self._push("app_activated", {"app_name": "Cursor"}, minutes_ago=2)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/a.py"}, minutes_ago=1)
        self._push("user_idle", {"seconds": 420})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "idle")

    def test_ignore_fichiers_bruites_xcode(self):
        self._push("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/App/App.xcodeproj/project.xcworkspace/xcuserdata/yugz.xcuserdatad/UserInterfaceState.xcuserstate"
        })
        self._push("file_modified", {
            "path": "/Users/yugz/Projets/Pulse/Pulse/App/App/SystemObserver.swift"
        })

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/App/App/SystemObserver.swift")

    def test_derive_file_type_mix_and_feature_candidate(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/tests/test_main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/README.md"})

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 3)
        self.assertEqual(signals.file_type_mix_10m["source"], 1)
        self.assertEqual(signals.file_type_mix_10m["test"], 1)
        self.assertEqual(signals.file_type_mix_10m["docs"], 1)
        self.assertEqual(signals.dominant_file_mode, "few_files")
        self.assertEqual(signals.work_pattern_candidate, "feature_candidate")

    def test_detecte_refactor_candidate_avec_renommages(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/a.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/b.py"})
        self._push("file_renamed", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/c.py"})
        self._push("file_deleted", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/d.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 4)
        self.assertGreaterEqual(signals.rename_delete_ratio_10m, 0.5)
        self.assertEqual(signals.dominant_file_mode, "few_files")
        self.assertEqual(signals.work_pattern_candidate, "refactor_candidate")

    def test_detecte_setup_candidate_sur_fichiers_config(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/package.json"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/pyproject.toml"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/.env"})

        signals = self.scorer.compute()

        self.assertEqual(signals.file_type_mix_10m["config"], 2)
        self.assertEqual(signals.work_pattern_candidate, "setup_candidate")

    def test_setup_candidate_sans_ancrage_fort_retombe_sur_general(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._push("app_activated", {"app_name": "ChatGPT"})
            self._push("file_modified", {"path": f"{tmpdir}/package.json"})
            self._push("file_modified", {"path": f"{tmpdir}/pyproject.toml"})
            self._push("file_modified", {"path": f"{tmpdir}/.env"})

            signals = self.scorer.compute()

        self.assertIsNone(signals.active_project)
        self.assertEqual(signals.work_pattern_candidate, "setup_candidate")
        self.assertEqual(signals.probable_task, "general")

    def test_setup_candidate_avec_ancrage_projet_reste_coding(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/package.json"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/pyproject.toml"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/.env"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_project, "Pulse")
        self.assertEqual(signals.work_pattern_candidate, "setup_candidate")
        self.assertEqual(signals.probable_task, "coding")

    def test_reduit_other_avec_extensions_config_et_source_courantes(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/config/settings.yaml"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/tsconfig.base.json"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/db/migrate.sql"})

        signals = self.scorer.compute()

        self.assertEqual(signals.file_type_mix_10m["config"], 2)
        self.assertEqual(signals.file_type_mix_10m["source"], 1)
        self.assertNotIn("other", signals.file_type_mix_10m)

    def test_notes_transitoire_ne_force_pas_writing_si_activite_code_forte(self):
        self._push("app_activated", {"app_name": "Cursor"}, minutes_ago=2)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/a.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/b.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/tests/test_a.py"}, minutes_ago=1)
        self._push("app_activated", {"app_name": "Notes"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "coding")

    def test_activite_code_multi_fichiers_promeut_coding_meme_sans_app_dev(self):
        self._push("app_activated", {"app_name": "Notes"}, minutes_ago=3)
        for index in range(8):
            self._push(
                "file_modified",
                {"path": f"/Users/yugz/Projets/Pulse/Pulse/daemon/module_{index}.py"},
                minutes_ago=1,
            )

        signals = self.scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 8)
        self.assertEqual(signals.probable_task, "coding")

    def test_general_reste_fallback_si_activite_est_trop_faible(self):
        self._push("app_activated", {"app_name": "Notes"})

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "writing")
        self.bus._queue.clear()

        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/misc/data.json"})
        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "general")

    def test_active_project_detecte_depuis_racine_git_hors_chemins_marqueurs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "clients" / "workspace-app"
            (repo_root / ".git").mkdir(parents=True)
            file_path = repo_root / "src" / "handler.py"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("print('ok')\n")

            self._push("file_modified", {"path": str(file_path)})

            signals = self.scorer.compute()

            self.assertEqual(signals.active_project, "workspace-app")
            self.assertEqual(signals.active_file, str(file_path))

    def test_file_deleted_ne_devient_pas_le_fichier_actif(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("file_deleted", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/obsolete.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.active_project, "Pulse")

    def test_ignore_les_fichiers_internes_pulse_dans_les_signaux(self):
        pulse_db = str(Path.home() / ".pulse" / "session.db")
        pulse_journal = str(Path.home() / ".pulse" / "session.db-journal")

        self._push("file_modified", {"path": pulse_db})
        self._push("file_modified", {"path": pulse_journal})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.active_project, "Pulse")
        self.assertEqual(signals.edited_file_count_10m, 1)

    def test_ignore_les_fichiers_techniques_pour_les_signaux_de_session(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/tmp/build.log"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/tmp/dev.sqlite"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/tmp/cache.db"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/tmp/session.db-journal"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.edited_file_count_10m, 1)
        self.assertEqual(signals.file_type_mix_10m, {"source": 1})

    def test_ignore_models_cache_json_dans_les_signaux(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/build/models_cache.json"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.edited_file_count_10m, 1)
        self.assertEqual(signals.file_type_mix_10m, {"source": 1})
        self.assertEqual(signals.probable_task, "coding")

    def test_cache_json_seul_ne_pese_pas_sur_la_tache_probable(self):
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/build/models_cache.json"})

        signals = self.scorer.compute()

        self.assertIsNone(signals.active_file)
        self.assertEqual(signals.edited_file_count_10m, 0)
        self.assertEqual(signals.file_type_mix_10m, {})
        self.assertEqual(signals.probable_task, "general")

    def test_capture_ecran_seule_ne_pese_pas_sur_la_tache_probable(self):
        self._push("file_created", {"path": "/Users/yugz/Desktop/Capture d’écran 2026-04-21 à 10.32.18.png"})

        signals = self.scorer.compute()

        self.assertIsNone(signals.active_file)
        self.assertEqual(signals.edited_file_count_10m, 0)
        self.assertEqual(signals.file_type_mix_10m, {})
        self.assertEqual(signals.probable_task, "general")

    def test_capture_ecran_n_ecrase_pas_un_vrai_fichier_de_travail(self):
        self._push("app_activated", {"app_name": "Cursor"})
        self._push("file_created", {"path": "/Users/yugz/Desktop/Screenshot 2026-04-21 at 10.32.18.png"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.active_file, "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py")
        self.assertEqual(signals.edited_file_count_10m, 1)
        self.assertEqual(signals.file_type_mix_10m, {"source": 1})
        self.assertEqual(signals.probable_task, "coding")

    def test_trash_seul_ne_pese_pas_sur_la_tache_probable(self):
        self._push("file_modified", {"path": "/Users/yugz/.Trash/logo-final.png"})

        signals = self.scorer.compute()

        self.assertIsNone(signals.active_file)
        self.assertEqual(signals.edited_file_count_10m, 0)
        self.assertEqual(signals.file_type_mix_10m, {})
        self.assertEqual(signals.probable_task, "general")

    def test_long_burst_ne_tronque_pas_les_signaux_fichier_dans_la_fenetre_10m(self):
        bus = EventBus()
        scorer = SignalScorer(bus)
        timestamp = datetime.now() - timedelta(minutes=5)

        for index in range(220):
            bus._queue.append(Event(
                type="file_modified",
                payload={"path": f"/Users/yugz/Projets/Pulse/Pulse/daemon/module_{index}.py"},
                timestamp=timestamp,
            ))

        signals = scorer.compute()

        self.assertEqual(signals.edited_file_count_10m, 220)
        self.assertEqual(signals.dominant_file_mode, "multi_file")
        self.assertEqual(signals.file_type_mix_10m, {"source": 220})


    # ── I1 : recent_apps — dernière occurrence gagne ────────────────────────────

    def test_i1_retour_app_dev_apres_browser_detecte_comme_app_courante(self):
        """
        Xcode → Chrome → Xcode : la dernière app activée doit être Xcode.
        Avec l'ancienne impl (set dedup), Chrome était la "dernière" car
        Xcode était déjà dans le set et ignoré à la deuxième occurrence.
        """
        self._push("app_activated", {"app_name": "Xcode"})
        self._push("app_activated", {"app_name": "Chrome"})
        self._push("app_activated", {"app_name": "Xcode"})  # retour dans l'IDE
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.recent_apps[-1], "Xcode",
            "La dernière app activée doit être la dernière dans recent_apps")
        self.assertEqual(signals.probable_task, "coding",
            "Retour dans Xcode + fichier modifié doit être détecté comme coding, pas browsing")

    def test_i1_ordre_reflète_dernière_activation(self):
        """
        A → B → A : la liste doit être [B, A] (pas [A, B]).
        A → B → C → A : la liste doit être [B, C, A].
        """
        self._push("app_activated", {"app_name": "Xcode"})
        self._push("app_activated", {"app_name": "Terminal"})
        self._push("app_activated", {"app_name": "Arc"})
        self._push("app_activated", {"app_name": "Xcode"})  # retour dans l'IDE

        signals = self.scorer.compute()

        self.assertEqual(signals.recent_apps, ["Terminal", "Arc", "Xcode"],
            "Xcode doit apparaître en dernière position, pas en première")

    def test_i1_apps_uniques_pas_de_doublons_dans_la_liste(self):
        """Chaque app n'apparaît qu'une seule fois, même si activée plusieurs fois."""
        for _ in range(3):
            self._push("app_activated", {"app_name": "Xcode"})
            self._push("app_activated", {"app_name": "Terminal"})

        signals = self.scorer.compute()

        self.assertEqual(signals.recent_apps.count("Xcode"), 1)
        self.assertEqual(signals.recent_apps.count("Terminal"), 1)

    def test_i1_browsing_court_ne_masque_pas_app_dev_active(self):
        """
        Cas réel : Xcode → Chrome (recherche rapide) → Xcode.
        Sans le fix, probable_task pouvait tomber sur 'browsing'.
        """
        self._push("app_activated", {"app_name": "Xcode"}, minutes_ago=5)
        self._push("file_modified",
            {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"}, minutes_ago=4)
        self._push("app_activated", {"app_name": "Chrome"}, minutes_ago=2)
        self._push("app_activated", {"app_name": "Xcode"}, minutes_ago=1)  # retour

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "browsing",
            "Un aller-retour sur Chrome ne doit pas écraser la détection d'activité de dev")
        self.assertEqual(signals.recent_apps[-1], "Xcode")


    # ── 4A : clipboard context borné dans le temps ──────────────────────────────

    def test_4a_stacktrace_recent_maintient_debug(self):
        """Une stacktrace copiee il y a < 5 min → probable_task = debug. Comportement preserve."""
        self._push("app_activated", {"app_name": "Terminal"})
        self._push("clipboard_updated", {"content_kind": "stacktrace"}, minutes_ago=2)

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "debug")
        self.assertEqual(signals.clipboard_context, "stacktrace")

    def test_4a_stacktrace_ancien_ne_force_pas_debug(self):
        """
        Bug original : une stacktrace copiee il y a > 5 min maintenait
        probable_task='debug' indefiniment, ecrasant toute activite de code.
        """
        self._push("clipboard_updated", {"content_kind": "stacktrace"}, minutes_ago=10)
        self._push("app_activated", {"app_name": "Cursor"}, minutes_ago=5)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"}, minutes_ago=1)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/session.py"}, minutes_ago=1)

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "debug",
            "Une stacktrace > 5 min ne doit plus forcer debug. "
            f"probable_task obtenu : {signals.probable_task}")
        self.assertIsNone(signals.clipboard_context,
            "clipboard_context doit etre None si le dernier clipboard a > 5 min")
        self.assertEqual(signals.probable_task, "coding")


    # ── Faux positif "rédaction" sur téléchargements (Phase 1 terrain) ───────────

    def test_md_telecharge_depuis_chrome_ne_produit_pas_writing(self):
        """
        Scénario réel : Google Docs exporté → ~/Downloads/Untitled document.md
        depuis Chrome. Le fichier doit être neutral (pas dans edited_file_count)
        et la tâche ne doit pas être writing.
        """
        for _ in range(4):
            self._push("file_modified", {"path": "/Users/yugz/Downloads/Untitled document.md"})
        self._push("app_activated", {"app_name": "Google Chrome"})

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "writing",
            f"Un .md dans Downloads + Chrome ne doit pas produire writing, got: {signals.probable_task}")
        self.assertEqual(signals.edited_file_count_10m, 0,
            "Les fichiers dans ~/Downloads doivent être neutral → pas comptés dans edited_file_count")

    def test_browser_actif_bloque_docs_only_meme_hors_downloads(self):
        """
        Guard browser sur docs_only : si le browser est l'app active,
        plusieurs events sur un .md de projet ne doivent pas produire writing.
        """
        for _ in range(4):
            self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/NOTES.md"})
        self._push("app_activated", {"app_name": "Google Chrome"})

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "writing",
            f"Browser actif + .md projet ne doit pas produire writing, got: {signals.probable_task}")

    def test_4a_clipboard_context_none_si_hors_fenetre(self):
        """clipboard_context est None si tous les events clipboard ont > 5 min."""
        self._push("clipboard_updated", {"content_kind": "code"}, minutes_ago=8)
        self._push("clipboard_updated", {"content_kind": "url"}, minutes_ago=6)

        signals = self.scorer.compute()

        self.assertIsNone(signals.clipboard_context)

    def test_4a_clipboard_le_plus_recent_dans_fenetre_est_retenu(self):
        """Si plusieurs clipboards dont certains dans la fenetre, on retient le plus recent."""
        self._push("clipboard_updated", {"content_kind": "stacktrace"}, minutes_ago=15)
        self._push("clipboard_updated", {"content_kind": "code"}, minutes_ago=3)  # dans la fenetre

        signals = self.scorer.compute()

        self.assertEqual(signals.clipboard_context, "code",
            "Le clipboard recent (code, 3 min) doit primer sur l'ancien (stacktrace, 15 min)")
        self.assertNotEqual(signals.probable_task, "debug",
            "Une stacktrace ancienne ne doit pas influencer probable_task")

    def test_4a_friction_stacktrace_non_appliquee_si_hors_fenetre(self):
        """
        Le bonus friction +0.3 pour stacktrace ne doit pas s'appliquer
        si la stacktrace a ete copiee il y a > 5 min.
        """
        # Aucun fichier churn : friction de base = 0
        self._push("clipboard_updated", {"content_kind": "stacktrace"}, minutes_ago=10)

        signals = self.scorer.compute()

        self.assertEqual(signals.friction_score, 0.0,
            "Une stacktrace ancienne ne doit pas ajouter +0.3 au friction_score")

    def test_4a_friction_stacktrace_appliquee_si_recente(self):
        """Le bonus friction +0.3 est applique si la stacktrace est dans la fenetre."""
        self._push("clipboard_updated", {"content_kind": "stacktrace"}, minutes_ago=2)

        signals = self.scorer.compute()

        self.assertGreaterEqual(signals.friction_score, 0.3,
            "Une stacktrace recente doit ajouter +0.3 au friction_score")


    # ── 4B : browsing/writing uniquement si l'app est vraiment recente ────────────

    def test_4b_browsing_recent_detecte_normalement(self):
        """Un switch browser il y a < 5 min sans fichiers → exploration (browsing supprimé des tâches)."""
        self._push("app_activated", {"app_name": "Chrome"}, minutes_ago=2)

        signals = self.scorer.compute()

        # browsing n'est plus une tâche valide — remplacé par exploration
        self.assertEqual(signals.probable_task, "exploration")

    def test_4b_browsing_ancien_ne_force_pas_browsing(self):
        """
        Bug original : un switch browser il y a 20 min maintenait probable_task='browsing'
        alors que l'utilisateur avait repris le travail.
        """
        self._push("app_activated", {"app_name": "Chrome"}, minutes_ago=20)
        # Pas de nouvelle activite app dans les 5 dernieres minutes

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "browsing",
            "Un switch browser il y a 20 min ne doit plus forcer browsing. "
            f"probable_task obtenu : {signals.probable_task}")
        self.assertEqual(signals.probable_task, "general")

    def test_4b_coding_stable_apres_browser_court(self):
        """
        Scenario reel : Xcode (travail) -> Chrome (10s) -> retour Xcode.
        A t+6 min, le Chrome est hors fenetre 5 min. Pulse doit dire 'coding'.
        """
        self._push("app_activated", {"app_name": "Xcode"}, minutes_ago=15)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"}, minutes_ago=12)
        self._push("app_activated", {"app_name": "Chrome"}, minutes_ago=10)
        self._push("app_activated", {"app_name": "Xcode"}, minutes_ago=8)
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/scorer.py"}, minutes_ago=7)
        # Maintenant : aucune app active dans les 5 derniere min (Xcode actif il y a 8 min)

        signals = self.scorer.compute()

        self.assertNotEqual(signals.probable_task, "browsing")
        # 2 fichiers source modifies -> strong_coding_evidence -> coding
        self.assertEqual(signals.probable_task, "coding")

    def test_4b_writing_recent_detecte_normalement(self):
        """Une app writing active il y a < 5 min sans fichiers -> writing. Comport. preserve."""
        self._push("app_activated", {"app_name": "Notion"}, minutes_ago=2)

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "writing")

    def test_4b_writing_ancien_tombe_sur_general(self):
        """Une app writing active il y a > 5 min sans fichiers -> general (pas writing)."""
        self._push("app_activated", {"app_name": "Notion"}, minutes_ago=15)

        signals = self.scorer.compute()

        self.assertEqual(signals.probable_task, "general")


    # ── 4C : scattered ne doit pas ecraser une vraie activite fichiers ───────────

    def test_4c_scattered_sans_fichiers_reste_scattered(self):
        """Beaucoup de switches, peu de fichiers -> scattered. Comportement preserve."""
        apps = ["Cursor", "Safari", "Terminal", "Notion", "Chrome", "Arc"]
        for app in apps:
            self._push("app_activated", {"app_name": app})
        # 0 fichier edite -> scattered

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "scattered")

    def test_4c_switches_nombreux_avec_fichiers_retourne_normal(self):
        """
        6+ switches en 10 min mais 3+ fichiers modifies en parallele -> normal.
        Workflow dev actif (Xcode/Terminal/Chrome) ne doit pas etre classe scattered.
        """
        apps = ["Xcode", "Terminal", "Chrome", "Xcode", "Terminal", "Xcode"]
        for app in apps:
            self._push("app_activated", {"app_name": app})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/scorer.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/session.py"})

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "normal",
            "6 switches + 3 fichiers modifies doit etre 'normal', pas 'scattered'")

    def test_4c_seuil_2_fichiers_insuffisant_pour_annuler_scattered(self):
        """2 fichiers ne suffisent pas pour annuler scattered (seuil = 3)."""
        apps = ["Xcode", "Terminal", "Chrome", "Xcode", "Terminal", "Xcode"]
        for app in apps:
            self._push("app_activated", {"app_name": app})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"})
        self._push("file_modified", {"path": "/Users/yugz/Projets/Pulse/Pulse/daemon/scorer.py"})
        # 2 fichiers < seuil de 3

        signals = self.scorer.compute()

        self.assertEqual(signals.focus_level, "scattered")


if __name__ == "__main__":
    unittest.main()
