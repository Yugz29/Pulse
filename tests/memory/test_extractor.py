import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta
from flask import Flask

from daemon.memory.extractor import (
    enrich_session_report,
    load_memory_context,
    update_memories_from_session,
)
import daemon.memory.extractor as extractor_module
from daemon.routes.facts import register_facts_routes


class FakeLLM:

    def complete(self, prompt, max_tokens=200):
        return "Résumé court de la session."


class FailingLLM:

    def complete(self, prompt, max_tokens=200):
        raise RuntimeError("offline")


class TestExtractor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory_dir = Path(self.tmpdir.name)
        # Réinitialise le curseur et l'état de chargement entre chaque test
        extractor_module.reset_cooldown_for_tests()
        extractor_module.reset_fact_engine_for_tests()
        extractor_module._fact_engine = extractor_module.FactEngine(
            db_path=Path(self.tmpdir.name) / "facts.db",
            md_path=Path(self.tmpdir.name) / "facts.md",
        )
        # Redirige cooldown.json vers un fichier temporaire isolé
        # pour éviter que le vrai ~/.pulse/cooldown.json ne bloque les tests
        self._orig_cooldown_file = extractor_module._COOLDOWN_FILE
        extractor_module._COOLDOWN_FILE = Path(self.tmpdir.name) / "cooldown.json"

    def tearDown(self):
        extractor_module.reset_fact_engine_for_tests()
        extractor_module._COOLDOWN_FILE = self._orig_cooldown_file
        self.tmpdir.cleanup()

    def test_update_memories_cree_projects_et_index(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 25,
                "probable_task": "coding",
                "recent_apps": ["Cursor", "Terminal"],
                "files_changed": 3,
                "max_friction": 0.4,
            },
            memory_dir=self.memory_dir,
        )

        projects = (self.memory_dir / "projects.md").read_text()
        index = (self.memory_dir / "MEMORY.md").read_text()

        self.assertIn("## Pulse", projects)
        self.assertIn("Type de travail détecté : coding", projects)
        self.assertIn("[projects](projects.md)", index)
        # habits.md n'est plus écrit — remplacé par facts.md
        self.assertFalse((self.memory_dir / "habits.md").exists())

    def test_update_projects_met_a_jour_un_projet_existant(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 12,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
            },
            memory_dir=self.memory_dir,
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 40,
                "probable_task": "debug",
                "recent_apps": ["Terminal"],
            },
            memory_dir=self.memory_dir,
        )

        projects = (self.memory_dir / "projects.md").read_text()

        self.assertEqual(projects.count("## Pulse"), 1)
        self.assertIn("Type de travail détecté : debug", projects)
        self.assertIn("(40 min, debug)", projects)

    def test_update_memories_prefers_latest_closed_episode_for_consolidation(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 48,
                "probable_task": "general",
                "recent_apps": ["Cursor", "Terminal"],
                "files_changed": 3,
                "top_files": ["runtime_orchestrator.py", "episode_fsm.py"],
                "max_friction": 0.2,
                "closed_episodes": [
                    {
                        "episode_id": "ep-older",
                        "session_id": "sess-1",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "editing",
                        "task_confidence": 0.7,
                        "started_at": "2026-04-23T10:00:00",
                        "ended_at": "2026-04-23T10:20:00",
                        "duration_sec": 1200,
                        "boundary_reason": "idle_timeout",
                    },
                    {
                        "episode_id": "ep-latest",
                        "session_id": "sess-1",
                        "active_project": "Pulse",
                        "probable_task": "debug",
                        "activity_level": "executing",
                        "task_confidence": 0.91,
                        "started_at": "2026-04-23T10:21:00",
                        "ended_at": "2026-04-23T10:36:00",
                        "duration_sec": 900,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        projects = (self.memory_dir / "projects.md").read_text()
        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertIn("Type de travail détecté : debug", projects)
        self.assertIn("(15 min, debug)", projects)
        self.assertIn("## Pulse", journal)
        self.assertIn("débogage (15 min)", journal)
        self.assertIn("- Épisodes récents :", projects)
        self.assertIn("2026-04-23 10:36 | debug | executing | 15 min | commit | ep-latest", projects)

    def test_update_memories_falls_back_to_session_when_no_closed_episode_exists(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 22,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 2,
                "top_files": ["main.py"],
                "max_friction": 0.1,
                "closed_episodes": [],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        projects = (self.memory_dir / "projects.md").read_text()
        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertIn("Type de travail détecté : coding", projects)
        self.assertIn("(22 min, coding)", projects)
        self.assertIn("## Pulse", journal)
        self.assertIn("développement (22 min)", journal)
        self.assertNotIn("- Épisodes récents :", projects)

    def test_projection_projet_conserve_un_historique_roulant_d_episodes(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 30,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 3,
                "top_files": ["main.py", "state.py"],
                "closed_episodes": [
                    {
                        "episode_id": "ep-1",
                        "session_id": "sess-1",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "editing",
                        "task_confidence": 0.82,
                        "started_at": "2026-04-23T09:00:00",
                        "ended_at": "2026-04-23T09:20:00",
                        "duration_sec": 1200,
                        "boundary_reason": "idle_timeout",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 18,
                "probable_task": "debug",
                "recent_apps": ["Terminal"],
                "files_changed": 2,
                "top_files": ["runtime_orchestrator.py"],
                "closed_episodes": [
                    {
                        "episode_id": "ep-2",
                        "session_id": "sess-2",
                        "active_project": "Pulse",
                        "probable_task": "debug",
                        "activity_level": "executing",
                        "task_confidence": 0.9,
                        "started_at": "2026-04-24T10:00:00",
                        "ended_at": "2026-04-24T10:18:00",
                        "duration_sec": 1080,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        projects = (self.memory_dir / "projects.md").read_text()

        self.assertIn("2026-04-24 10:18 | debug | executing | 18 min | commit | ep-2", projects)
        self.assertIn("2026-04-23 09:20 | coding | editing | 20 min | idle_timeout | ep-1", projects)
        self.assertIn("Type de travail détecté : debug", projects)

    def test_load_memory_context_concatene_les_fichiers(self):
        # load_memory_context() lit projects.md + preferences.md uniquement.
        # habits.md est exclu volontairement (bruit non structuré).
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 18,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
            },
            memory_dir=self.memory_dir,
        )
        (self.memory_dir / "preferences.md").write_text("# Préférences\n\n- Réponses courtes\n")

        context = load_memory_context(memory_dir=self.memory_dir)

        self.assertIn("# Projets", context)
        self.assertIn("# Préférences", context)
        # habits.md est exclu de load_memory_context (remplacé par facts.md à terme)
        self.assertNotIn("# Habitudes", context)

    def test_resume_llm_ecrit_une_session_si_duree_suffisante(self):
        # trigger='commit' pour que le LLM soit effectivement appelé
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 5,
                "max_friction": 0.7,
            },
            llm=FakeLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertIn("Résumé court de la session.", content)
        self.assertIn("## Pulse", content)
        self.assertIn("### ", content)
        self.assertIn("développement (45 min)", content)

    def test_commit_leger_et_court_ne_genere_pas_de_journal(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 5,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 1,
            },
            llm=FakeLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="wip",
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(session_files, [])

    def test_commit_peu_substantiel_reste_deterministe_meme_avec_llm(self):
        call_count = {"n": 0}

        class CountingLLM:
            def complete(self, prompt, max_tokens=200):
                call_count["n"] += 1
                return "Ne devrait pas apparaître."

        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 1,
                "top_files": ["main.py"],
            },
            llm=CountingLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="wip",
        )

        self.assertEqual(call_count["n"], 0)
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertIn("Livraison : « wip ». Portée : main.py.", content)

    def test_llm_desactive_pour_screen_lock(self):
        """Le LLM ne doit PAS être appelé pour screen_lock — fallback déterministe uniquement."""
        call_count = {"n": 0}

        class CountingLLM:
            def complete(self, prompt, max_tokens=200):
                call_count["n"] += 1
                return "Ne devrait pas apparaître."

        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 3,
                "max_friction": 0.2,
            },
            llm=CountingLLM(),
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        self.assertEqual(call_count["n"], 0, "LLM ne doit pas être appelé pour screen_lock")
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        content = session_files[0].read_text()
        self.assertIn("## Pulse", content)
        self.assertIn("45 min", content)

    def test_llm_desactive_pour_manual(self):
        """Le LLM ne doit PAS être appelé pour manual non plus — seul commit l'active."""
        call_count = {"n": 0}

        class CountingLLM:
            def complete(self, prompt, max_tokens=200):
                call_count["n"] += 1
                return "Ne devrait pas apparaître."

        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 3,
                "max_friction": 0.2,
            },
            llm=CountingLLM(),
            memory_dir=self.memory_dir,
            trigger="manual",
        )

        self.assertEqual(call_count["n"], 0, "LLM ne doit pas être appelé pour manual")

    def test_curseur_empeche_doublon_dans_cooldown(self):
        """Deux appels en moins de REPORT_COOLDOWN_MIN ne produisent qu'un seul rapport."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1, "Le curseur doit bloquer le deuxième rapport")

    def test_commit_ignore_le_cooldown(self):
        """Un trigger commit bypasse toujours le cooldown."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        update_memories_from_session(
            session, memory_dir=self.memory_dir,
            trigger="commit", commit_message="fix: correction critique"
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        # Un seul fichier journal, mais deux sections
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertGreaterEqual(content.count("### "), 2, "Le commit doit ajouter une deuxième entrée")
        self.assertIn("correction critique", content)

    def test_curseur_expire_apres_cooldown(self):
        """Après REPORT_COOLDOWN_MIN, un nouveau rapport peut être généré."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
            "files_changed": 5,
            "max_friction": 0.3,
        }
        # Simule un curseur vieux de 31 minutes
        past = datetime.now() - timedelta(minutes=31)
        extractor_module._cooldown.last_report_at["Pulse"] = past

        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1, "Le curseur expiré doit autoriser un nouveau rapport")

    def test_habits_plus_ecrit(self):
        """habits.md n'est plus écrit depuis la migration vers facts.md."""
        session = {
            "active_project": "Pulse",
            "duration_min": 25,
            "probable_task": "coding",
            "recent_apps": ["Cursor", "Terminal"],
        }
        update_memories_from_session(session, memory_dir=self.memory_dir)
        update_memories_from_session(session, memory_dir=self.memory_dir)

        self.assertFalse((self.memory_dir / "habits.md").exists())

    def test_resume_llm_ecrit_un_fallback_si_ollama_echoue(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 45,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 5,
                "max_friction": 0.7,
            },
            llm=FailingLLM(),
            memory_dir=self.memory_dir,
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertIn("## Pulse", content)
        self.assertIn("45 min", content)
        self.assertIn("Pulse", content)
        self.assertIn("5 fichier", content)


    def test_duration_cap(self):
        """Les sessions aberrantes (>480 min) sont plafonnées à MAX_SESSION_DURATION_MIN."""
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 999,
                "probable_task": "coding",
                "recent_apps": ["Xcode"],
                "files_changed": 2,
                "max_friction": 0.1,
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertNotIn("999", content)
        self.assertIn("480", content)

    def test_cooldown_persiste_apres_restart(self):
        """Le curseur survit à une réinitialisation de _cooldown_loaded (simule un restart)."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
        }
        # Premier daemon : écrit un rapport, persiste le curseur
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        self.assertTrue(extractor_module._COOLDOWN_FILE.exists())

        # Simule un restart : remet le cooldown à zéro
        extractor_module.reset_cooldown_for_tests()

        # Deuxième daemon : doit lire le curseur et bloquer le rapport
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")
        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1, "Le curseur persisté doit bloquer le deuxième rapport")

    def test_clean_files_filtre_images(self):
        """Les captures d'écran et images sont exclues des top_files."""
        from daemon.memory.extractor import _clean_files
        files = [
            "main.py",
            "Capture d'écran 2026-04-12 à 16.15.png",
            "Screenshot 2026.jpg",
            "PanelView.swift",
            "archive.zip",
        ]
        result = _clean_files(files)
        self.assertIn("main.py", result)
        self.assertIn("PanelView.swift", result)
        self.assertNotIn("Screenshot 2026.jpg", result)
        self.assertNotIn("archive.zip", result)

    def test_clean_files_filtre_systeme(self):
        """Les fichiers système macOS sont exclus."""
        from daemon.memory.extractor import _clean_files
        files = ["loginwindow", "Desktop", "cognitive.py", "Downloads"]
        result = _clean_files(files)
        self.assertIn("cognitive.py", result)
        self.assertNotIn("loginwindow", result)
        self.assertNotIn("Desktop", result)
        self.assertNotIn("Downloads", result)


    def test_journal_append_meme_fichier(self):
        """Deux sessions le même jour s'accumulent dans le même fichier."""
        session = {
            "active_project": "Pulse",
            "duration_min": 30,
            "probable_task": "coding",
            "recent_apps": ["Xcode"],
        }
        update_memories_from_session(session, memory_dir=self.memory_dir, trigger="screen_lock")

        # Deuxième session — cooldown bypass via commit
        session2 = dict(session, probable_task="debug")
        update_memories_from_session(
            session2, memory_dir=self.memory_dir,
            trigger="commit", commit_message="fix: correction bug"
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        # Un seul fichier pour la journée
        self.assertEqual(len(session_files), 1)
        content = session_files[0].read_text()
        self.assertGreaterEqual(content.count("### "), 2)
        self.assertIn("correction bug", content)

    def test_journal_regroupe_les_entrees_par_projet(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 20,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "top_files": ["runtime_orchestrator.py"],
                "files_changed": 1,
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )
        extractor_module._cooldown.last_report_at["Docs"] = datetime.now() - timedelta(minutes=31)
        update_memories_from_session(
            {
                "active_project": "Docs",
                "duration_min": 18,
                "probable_task": "writing",
                "recent_apps": ["Notes"],
                "top_files": ["plan.md"],
                "files_changed": 1,
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Pulse", journal)
        self.assertIn("## Docs", journal)
        self.assertIn("développement (20 min)", journal)
        self.assertIn("rédaction (18 min)", journal)

    def test_journal_fusionne_les_entrees_consecutives_meme_projet_meme_tache(self):
        base_session = {
            "active_project": "Pulse",
            "duration_min": 10,
            "probable_task": "coding",
            "recent_apps": ["Cursor"],
            "top_files": ["main.py"],
            "files_changed": 1,
        }
        update_memories_from_session(
            base_session,
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: premier bloc",
        )
        update_memories_from_session(
            dict(base_session, top_files=["runtime.py"]),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: second bloc",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertEqual(journal.count("### "), 1)
        self.assertIn("développement (20 min)", journal)
        self.assertIn("premier bloc", journal)
        self.assertIn("second bloc", journal)

    def test_journal_isole_le_bruit_dans_une_section_dediee(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 15,
                "probable_task": "general",
                "recent_apps": ["Cursor"],
                "top_files": ["models_cache.json"],
                "files_changed": 1,
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Activité faible / bruit", journal)
        self.assertIn("models_cache.json", journal)

    def test_journal_rend_un_episode_sans_projet_clair_dans_hors_projet(self):
        update_memories_from_session(
            {
                "active_project": None,
                "duration_min": 40,
                "probable_task": "general",
                "recent_apps": ["Safari", "zoom.us"],
                "files_changed": 0,
                "top_files": [],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Hors projet", journal)
        self.assertNotIn("## Pulse", journal)

    def test_journal_conserve_un_episode_projet_fort_avec_commit(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 35,
                "probable_task": "coding",
                "recent_apps": ["Cursor", "Terminal"],
                "top_files": ["runtime_orchestrator.py", "episode_fsm.py"],
                "files_changed": 2,
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: split sémantique des épisodes",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Pulse", journal)
        self.assertIn("feat: split sémantique des épisodes", journal)

    def test_journal_declasse_un_episode_inconnu_general_qui_chevauche_un_projet_fort(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 60,
                "probable_task": "coding",
                "recent_apps": ["Cursor", "Terminal"],
                "top_files": ["runtime_orchestrator.py", "episode_fsm.py"],
                "files_changed": 2,
                "closed_episodes": [
                    {
                        "episode_id": "ep-strong",
                        "session_id": "sess-1",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "editing",
                        "task_confidence": 0.91,
                        "started_at": "2026-04-24T10:00:00",
                        "ended_at": "2026-04-24T11:00:00",
                        "duration_sec": 3600,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: bloc fort",
        )
        update_memories_from_session(
            {
                "active_project": None,
                "duration_min": 30,
                "probable_task": "general",
                "recent_apps": ["Safari"],
                "files_changed": 0,
                "top_files": [],
                "closed_episodes": [
                    {
                        "episode_id": "ep-weak",
                        "session_id": "sess-2",
                        "active_project": None,
                        "probable_task": "general",
                        "activity_level": "unknown",
                        "task_confidence": 0.0,
                        "started_at": "2026-04-24T10:15:00",
                        "ended_at": "2026-04-24T10:45:00",
                        "duration_sec": 1800,
                        "boundary_reason": "idle_timeout",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Pulse", journal)
        self.assertIn("## Activité faible / bruit", journal)
        self.assertIn("10:15 → 10:45", journal)

    def test_journal_declasse_un_episode_projet_faible_quand_hors_projet_est_plus_plausible(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 30,
                "probable_task": "general",
                "recent_apps": ["Safari"],
                "files_changed": 1,
                "top_files": ["models_cache.json"],
                "closed_episodes": [
                    {
                        "episode_id": "ep-project-weak",
                        "session_id": "sess-1",
                        "active_project": "Pulse",
                        "probable_task": "general",
                        "activity_level": "unknown",
                        "task_confidence": 0.0,
                        "started_at": "2026-04-24T09:30:00",
                        "ended_at": "2026-04-24T10:00:00",
                        "duration_sec": 1800,
                        "boundary_reason": "idle_timeout",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )
        update_memories_from_session(
            {
                "active_project": None,
                "duration_min": 35,
                "probable_task": "general",
                "recent_apps": ["Safari", "zoom.us"],
                "files_changed": 0,
                "top_files": [],
                "closed_episodes": [
                    {
                        "episode_id": "ep-off-project",
                        "session_id": "sess-2",
                        "active_project": None,
                        "probable_task": "general",
                        "activity_level": "unknown",
                        "task_confidence": 0.0,
                        "started_at": "2026-04-24T09:35:00",
                        "ended_at": "2026-04-24T10:10:00",
                        "duration_sec": 2100,
                        "boundary_reason": "idle_timeout",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("## Hors projet", journal)
        self.assertNotIn("## Pulse", journal)
        self.assertIn("## Activité faible / bruit", journal)
        self.assertIn("models_cache.json", journal)

    def test_commit_peut_etre_enrichi_apres_ecriture_initiale(self):
        session = {
            "active_project": "Pulse",
            "duration_min": 45,
            "probable_task": "coding",
            "recent_apps": ["Cursor"],
            "files_changed": 5,
            "max_friction": 0.2,
        }

        report_ref = update_memories_from_session(
            session,
            llm=FakeLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: commit enrichi",
            defer_llm_enrichment=True,
        )

        session_files = list((self.memory_dir / "sessions").glob("*.md"))
        self.assertEqual(len(session_files), 1)
        before = session_files[0].read_text()
        self.assertIn("Commit : feat: commit enrichi", before)
        self.assertNotIn("Résumé court de la session.", before)

        ok = enrich_session_report(
            report_ref,
            session,
            FakeLLM(),
            commit_message="feat: commit enrichi",
        )
        self.assertTrue(ok)

        after = session_files[0].read_text()
        self.assertIn("Résumé court de la session.", after)
        self.assertIn("Commit : feat: commit enrichi", after)

    def test_fact_engine_structural_error_is_logged_and_exposed_via_facts_route(self):
        class ReadOnlyFailingFactEngine(extractor_module.FactEngine):
            def observe_session(self, session_data):
                raise sqlite3.OperationalError("attempt to write a readonly database")

        failing_engine = ReadOnlyFailingFactEngine(
            db_path=Path(self.tmpdir.name) / "facts-readonly.db",
            md_path=Path(self.tmpdir.name) / "facts-readonly.md",
        )
        extractor_module._fact_engine = failing_engine

        with self.assertLogs("pulse", level="ERROR") as captured:
            update_memories_from_session(
                {
                    "active_project": "Pulse",
                    "duration_min": 25,
                    "probable_task": "coding",
                    "recent_apps": ["Cursor"],
                },
                memory_dir=self.memory_dir,
            )

        self.assertTrue(any("Readonly" in line or "readonly database" in line for line in captured.output))

        app = Flask(__name__)
        app.config["TESTING"] = True
        register_facts_routes(app, get_fact_engine=lambda: failing_engine)
        client = app.test_client()

        resp = client.get("/facts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "degraded")
        self.assertIn("readonly database", data["reason"])
        self.assertEqual(data["facts"], [])


if __name__ == "__main__":
    unittest.main()
