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


class MarkdownLLM:

    def complete(self, prompt, max_tokens=200):
        return "*   **Analyse :**\n6.  **\n<channel|>Résumé *court* avec **markdown** parasite."


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

    def test_update_memories_prefers_latest_recent_session_for_consolidation(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 48,
                "probable_task": "general",
                "recent_apps": ["Cursor", "Terminal"],
                "files_changed": 3,
                "top_files": ["runtime_orchestrator.py", "episode_fsm.py"],
                "max_friction": 0.2,
                "recent_sessions": [
                    {
                        "id": "ep-older",
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
                        "id": "ep-latest",
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
        self.assertIn("- Sessions récentes :", projects)
        self.assertIn("2026-04-23 10:36 | debug | executing | 15 min | commit | ep-latest", projects)

    def test_update_memories_falls_back_to_session_when_no_recent_session_exists(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 22,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 2,
                "top_files": ["main.py"],
                "max_friction": 0.1,
                "recent_sessions": [],
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
        self.assertNotIn("- Sessions récentes :", projects)

    def test_commit_sans_work_block_n_herite_pas_d_une_session_fermee(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 19,
                "probable_task": "coding",
                "recent_apps": ["Codex", "Code"],
                "files_changed": 4,
                "top_files": ["DashboardViewModel.swift", "daydream.py"],
                "started_at": "2026-04-28T11:46:01",
                "updated_at": "2026-04-28T12:04:55",
                "recent_sessions": [
                    {
                        "id": "ep-commit",
                        "session_id": "sess-2",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "executing",
                        "task_confidence": 0.92,
                        "started_at": "2026-04-28T12:04:48",
                        "ended_at": "2026-04-28T12:04:55",
                        "duration_sec": 7,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat(daydream): add robust execution state",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertNotIn("11:46 → 12:04", journal)
        self.assertIn("12:04 — développement (1 min)", journal)
        self.assertIn("développement (1 min)", journal)

    def test_commit_sans_work_block_ignore_recent_session_ancienne_et_reste_pres_de_delivered_at(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 79,
                "probable_task": "coding",
                "activity_level": "executing",
                "recent_apps": ["Codex", "ChatGPT", "Code"],
                "files_changed": 2,
                "top_files": ["work_episode_builder.py", "test_work_episode_builder.py"],
                "started_at": "2026-05-05T12:29:25",
                "updated_at": "2026-05-05T13:48:29",
                "delivered_at": "2026-05-05T13:46:38",
                "recent_sessions": [
                    {
                        "id": "session-old",
                        "session_id": "sess-old",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "executing",
                        "started_at": "2026-05-05T11:16:09",
                        "ended_at": "2026-05-05T12:29:14",
                        "duration_sec": 4385,
                        "boundary_reason": "session_end",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat(memory): introduce pure work episode builder",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertNotIn("11:16 → 12:29", journal)
        self.assertNotIn("développement (73 min)", journal)
        self.assertIn("13:46 — développement (1 min)", journal)
        self.assertIn("développement (1 min)", journal)
        self.assertNotIn("Livré à 13:46.", journal)

    def test_commit_prefere_work_block_explicite_aux_sessions_techniques(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 18,
                "probable_task": "coding",
                "recent_apps": ["Codex", "Pulse", "Code"],
                "files_changed": 4,
                "top_files": ["daydream.py", "DashboardViewModel.swift"],
                "started_at": "2026-04-28T12:04:48.365316",
                "updated_at": "2026-04-28T12:04:55.324833",
                "work_block_started_at": "2026-04-28T11:46:01",
                "work_block_ended_at": "2026-04-28T12:04:55.324833",
                "recent_sessions": [
                    {
                        "id": "ep-commit",
                        "session_id": "sess-2",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "executing",
                        "task_confidence": 0.92,
                        "started_at": "2026-04-28T12:04:48.365316",
                        "ended_at": "2026-04-28T12:04:55.324833",
                        "duration_sec": 7,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat(daydream): add robust execution state",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertIn("11:46 → 12:04", journal)
        self.assertIn("développement (18 min)", journal)

    def test_commit_accepte_encore_work_window_et_closed_episodes_legacy(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 18,
                "probable_task": "coding",
                "recent_apps": ["Codex", "Pulse", "Code"],
                "files_changed": 4,
                "top_files": ["daydream.py", "DashboardViewModel.swift"],
                "started_at": "2026-04-28T12:04:48.365316",
                "updated_at": "2026-04-28T12:04:55.324833",
                "work_window_started_at": "2026-04-28T11:46:01",
                "work_window_ended_at": "2026-04-28T12:04:55.324833",
                "closed_episodes": [
                    {
                        "episode_id": "ep-commit",
                        "session_id": "sess-2",
                        "active_project": "Pulse",
                        "probable_task": "coding",
                        "activity_level": "executing",
                        "task_confidence": 0.92,
                        "started_at": "2026-04-28T12:04:48.365316",
                        "ended_at": "2026-04-28T12:04:55.324833",
                        "duration_sec": 7,
                        "boundary_reason": "commit",
                    },
                ],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat(daydream): add robust execution state",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()

        self.assertIn("11:46 → 12:04", journal)
        self.assertIn("développement (18 min)", journal)

    def test_projection_projet_conserve_un_historique_roulant_de_sessions(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 30,
                "probable_task": "coding",
                "recent_apps": ["Cursor"],
                "files_changed": 3,
                "top_files": ["main.py", "state.py"],
                "recent_sessions": [
                    {
                        "id": "ep-1",
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
                "recent_sessions": [
                    {
                        "id": "ep-2",
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

    def test_parse_project_sections_lit_l_ancien_titre_episodes_recents(self):
        projects_file = self.memory_dir / "projects.md"
        projects_file.write_text(
            "# Projets\n\n"
            "## Pulse\n\n"
            "- Première session : 2026-04-23\n"
            "- Dernière session : 2026-04-23 (15 min, debug)\n"
            "- Type de travail détecté : debug\n"
            "- Épisodes récents :\n"
            "  - 2026-04-23 10:36 | debug | executing | 15 min | commit | ep-latest\n",
            encoding="utf-8",
        )

        parsed = extractor_module._parse_project_sections(projects_file)

        self.assertEqual(parsed["Pulse"]["recent_sessions"][0]["record_id"], "ep-latest")

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
        # Livraison dans le body, portée rendue séparément par le renderer.
        self.assertIn("Livraison", content)
        self.assertIn("wip", content)
        self.assertIn("Portée estimée : main.py.", content)

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
        self.assertNotIn("999 min", content)
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
            "commit_activity_started_at": "2026-04-29T10:00:00",
            "commit_activity_ended_at": "2026-04-29T10:10:00",
        }
        update_memories_from_session(
            base_session,
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: premier bloc",
        )
        update_memories_from_session(
            dict(
                base_session,
                top_files=["runtime.py"],
                commit_activity_started_at="2026-04-29T10:10:00",
                commit_activity_ended_at="2026-04-29T10:20:00",
            ),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: second bloc",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertEqual(journal.count("### "), 1)
        self.assertIn("développement (20 min)", journal)
        self.assertIn("premier bloc", journal)
        self.assertIn("second bloc", journal)

    def test_journal_ne_fusionne_pas_deux_blocs_separes_par_un_long_gap(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 48,
                "probable_task": "coding",
                "activity_level": "executing",
                "recent_apps": ["Pulse", "Xcode"],
                "top_files": ["runtime_orchestrator.py"],
                "files_changed": 1,
                "started_at": "2026-04-29T01:51:06",
                "ended_at": "2026-04-29T02:39:23",
            },
            memory_dir=self.memory_dir,
            trigger="restart_repair",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 27,
                "probable_task": "coding",
                "activity_level": "executing",
                "recent_apps": ["Pulse", "Codex"],
                "top_files": ["DashboardContentView.swift"],
                "files_changed": 1,
                "started_at": "2026-04-29T10:33:04",
                "ended_at": "2026-04-29T11:00:21",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: reprise de contexte",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertNotIn("01:51 → 11:00", journal)
        self.assertNotIn("549 min", journal)
        self.assertIn("01:51 → 02:39", journal)
        self.assertIn("10:33 → 11:00", journal)

    def test_commit_utilise_l_activite_fichier_et_affiche_l_heure_de_livraison(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 69,
                "probable_task": "coding",
                "activity_level": "executing",
                "recent_apps": ["Pulse", "Codex"],
                "top_files": ["DashboardContentView.swift"],
                "files_changed": 1,
                "work_block_started_at": "2026-04-29T10:00:00",
                "work_block_ended_at": "2026-04-29T11:42:00",
                "commit_activity_started_at": "2026-04-29T10:33:04",
                "commit_activity_ended_at": "2026-04-29T10:48:12",
                "delivered_at": "2026-04-29T11:42:00",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: reprise de contexte",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("10:33 → 10:48", journal)
        self.assertIn("développement (15 min)", journal)
        self.assertIn("Livré à 11:42.", journal)
        self.assertNotIn("10:00 → 11:42", journal)

    def test_journal_decoupe_les_commits_livres_qui_se_chevauchent(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 3,
                "probable_task": "coding",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["daemon/memory/session.py", "tests/memory/test_session.py"],
                "files_changed": 2,
                "commit_activity_started_at": "2026-04-29T16:19:43",
                "commit_activity_ended_at": "2026-04-29T16:23:29",
                "delivered_at": "2026-04-29T16:32:54",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="refactor(session): derive context from events",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 11,
                "probable_task": "coding",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["App/App/DashboardRootView.swift"],
                "files_changed": 1,
                "commit_activity_started_at": "2026-04-29T16:23:29",
                "commit_activity_ended_at": "2026-04-29T16:34:53",
                "delivered_at": "2026-04-29T16:38:36",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="refactor(app): simplify live context card",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 24,
                "probable_task": "debug",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["daemon/memory/session.py", "App/App/DashboardRootView.swift"],
                "files_changed": 2,
                "commit_activity_started_at": "2026-04-29T16:19:43",
                "commit_activity_ended_at": "2026-04-29T16:43:47",
                "delivered_at": "2026-04-29T16:47:18",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="fix(session): clarify live and daily activity",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        rendered = journal.split("<!-- pulse-journal-data:start", 1)[0]

        self.assertIn("16:19 → 16:34", rendered)
        self.assertIn("16:34 → 16:43", rendered)
        self.assertNotIn("16:19 → 16:43", rendered)
        self.assertLess(rendered.index("16:19 → 16:34"), rendered.index("16:34 → 16:43"))

    def test_journal_decoupe_les_commits_chevauchants_avant_fusion(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 33,
                "probable_task": "debug",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": [],
                "files_changed": 0,
                "started_at": "2026-04-28T23:41:21",
                "ended_at": "2026-04-29T00:14:46",
            },
            memory_dir=self.memory_dir,
            trigger="screen_lock",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 2,
                "probable_task": "debug",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["SystemObserver.swift", "runtime_orchestrator.py"],
                "files_changed": 2,
                "commit_activity_started_at": "2026-04-29T00:16:05",
                "commit_activity_ended_at": "2026-04-29T00:18:08",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat(context): observe Claude Desktop sessions via FSEvents",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 12,
                "probable_task": "debug",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["event_actor.py"],
                "files_changed": 1,
                "commit_activity_started_at": "2026-04-29T00:21:06",
                "commit_activity_ended_at": "2026-04-29T00:33:06",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="fix(scorer): system path short-circuits actor scoring",
        )
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 22,
                "probable_task": "debug",
                "activity_level": "editing",
                "recent_apps": ["Codex", "Xcode"],
                "top_files": ["extractor.py", "test_extractor.py"],
                "files_changed": 2,
                "commit_activity_started_at": "2026-04-29T00:21:06",
                "commit_activity_ended_at": "2026-04-29T00:43:16",
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="fix(journal): remove portée from body",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        rendered = journal.split("<!-- pulse-journal-data:start", 1)[0]

        self.assertIn("28/04 23:41 → 29/04 00:43", rendered)
        self.assertIn("débogage (61 min)", rendered)
        self.assertNotIn("débogage (69 min)", rendered)

    def test_journal_ne_fusionne_pas_un_commit_livre_beaucoup_plus_tard(self):
        rendered = extractor_module._render_journal_document(
            "2026-04-29",
            [
                {
                    "entry_id": "first",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "duration_min": 20,
                    "body": "Premier bloc.",
                    "commit_message": "refactor(app): read session context aliases",
                    "recent_apps": ["Codex"],
                    "top_files": ["DaemonBridgeModels.swift"],
                    "files_count": 1,
                    "started_at": "2026-04-29T21:35:26",
                    "ended_at": "2026-04-29T21:55:14",
                    "delivered_at": "2026-04-29T21:58:57",
                    "scope_source": "commit_diff",
                },
                {
                    "entry_id": "late",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "duration_min": 24,
                    "body": "Commit livre plus tard.",
                    "commit_message": "refactor(runtime): rename session context dto",
                    "recent_apps": ["Codex"],
                    "top_files": ["contracts.py", "runtime_orchestrator.py"],
                    "files_count": 2,
                    "started_at": "2026-04-29T21:50:00",
                    "ended_at": "2026-04-29T22:14:00",
                    "delivered_at": "2026-04-29T23:36:02",
                    "scope_source": "commit_diff",
                },
            ],
        )

        self.assertIn("21:35 → 21:55 — développement (20 min)", rendered)
        self.assertIn("21:55 → 22:14 — développement (18 min)", rendered)
        self.assertNotIn("21:35 → 22:14 — développement", rendered)

    def test_commit_work_block_court_vaut_au_moins_une_minute(self):
        frame = extractor_module._build_consolidation_frame(
            {
                "active_project": "Pulse",
                "probable_task": "coding",
                "duration_min": 0,
                "commit_activity_started_at": "2026-04-29T23:41:56",
                "commit_activity_ended_at": "2026-04-29T23:42:20",
            },
            trigger="commit",
            commit_message="fix(journal): keep late commits separate",
        )

        self.assertEqual(frame["duration_min"], 1)

    def test_journal_affiche_une_heure_unique_pour_un_bloc_inferieur_a_une_minute(self):
        rendered = extractor_module._render_journal_document(
            "2026-04-29",
            [
                {
                    "entry_id": "short-commit",
                    "active_project": "Pulse",
                    "duration_min": 1,
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "body": "Livraison courte.",
                    "commit_message": "fix: short commit",
                    "recent_apps": ["Codex"],
                    "top_files": ["extractor.py"],
                    "files_count": 1,
                    "started_at": "2026-04-29T11:05:16",
                    "ended_at": "2026-04-29T11:05:50",
                    "scope_source": "commit_files",
                },
            ],
        )

        self.assertIn("### 11:05 — développement (1 min)", rendered)
        self.assertNotIn("11:05 → 11:05", rendered)

    def test_journal_n_additionne_pas_les_doublons_sans_commit_qui_se_chevauchent(self):
        base_session = {
            "active_project": "Pulse",
            "duration_min": 48,
            "probable_task": "coding",
            "activity_level": "executing",
            "recent_apps": ["Pulse", "Xcode"],
            "top_files": ["runtime_orchestrator.py"],
            "files_changed": 1,
            "started_at": "2026-04-29T01:51:06",
            "ended_at": "2026-04-29T02:39:23",
        }
        update_memories_from_session(
            base_session,
            memory_dir=self.memory_dir,
            trigger="restart_repair",
        )
        update_memories_from_session(
            dict(base_session),
            memory_dir=self.memory_dir,
            trigger="restart_repair",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("01:51 → 02:39", journal)
        self.assertIn("développement (48 min)", journal)
        self.assertNotIn("développement (96 min)", journal)

    def test_journal_masque_les_anciens_blocs_codex_metadata_sans_commit(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 48,
                "probable_task": "coding",
                "activity_level": "executing",
                "recent_apps": ["Pulse", "Codex"],
                "top_files": ["openai.yaml", "SKILL.md", "plugin.json"],
                "files_changed": 3,
                "started_at": "2026-04-29T01:51:06",
                "ended_at": "2026-04-29T02:39:23",
            },
            memory_dir=self.memory_dir,
            trigger="restart_repair",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertNotIn("01:51 → 02:39", journal)
        self.assertNotIn("openai.yaml", journal.split("<!-- pulse-journal-data:start", 1)[0])

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
                "commit_activity_started_at": "2026-04-24T10:00:00",
                "commit_activity_ended_at": "2026-04-24T11:00:00",
                "recent_sessions": [
                    {
                        "id": "ep-strong",
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
                "recent_sessions": [
                    {
                        "id": "ep-weak",
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
        self.assertNotIn("10:15 → 10:45", journal)

    def test_journal_declasse_un_episode_projet_faible_quand_hors_projet_est_plus_plausible(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 30,
                "probable_task": "general",
                "recent_apps": ["Safari"],
                "files_changed": 1,
                "top_files": ["models_cache.json"],
                "recent_sessions": [
                    {
                        "id": "ep-project-weak",
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
                "recent_sessions": [
                    {
                        "id": "ep-off-project",
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
        visible = journal.split("<!-- pulse-journal-data:start", 1)[0]
        self.assertIn("## Hors projet", visible)
        self.assertNotIn("## Pulse", visible)
        self.assertNotIn("## Activité faible / bruit", visible)
        self.assertNotIn("models_cache.json", visible)

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
        self.assertIn("feat: commit enrichi", before)
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
        self.assertIn("feat: commit enrichi", after)

    def test_enrich_pending_journal_summaries_enrichit_failed_et_ignore_current_ou_sans_commit(self):
        journal_date = "2026-05-05"
        sessions_dir = self.memory_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        journal_file = sessions_dir / f"{journal_date}.md"
        extractor_module._write_journal_document(
            journal_file,
            journal_date,
            [
                {
                    "entry_id": "failed-commit",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "duration_min": 18,
                    "body": "Fallback failed.",
                    "commit_message": "fix: enrich later",
                    "recent_apps": ["Codex"],
                    "top_files": ["extractor.py"],
                    "files_count": 1,
                    "started_at": "2026-05-05T10:00:00",
                    "ended_at": "2026-05-05T10:18:00",
                    "boundary_reason": "commit",
                    "scope_source": "commit_diff",
                    "summary_source": "deterministic_fallback",
                    "summary_status": "failed",
                    "summary_error": "offline",
                },
                {
                    "entry_id": "current-entry",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "duration_min": 20,
                    "body": "Current fallback.",
                    "commit_message": "feat: current commit",
                    "recent_apps": ["Codex"],
                    "top_files": ["runtime.py"],
                    "files_count": 1,
                    "started_at": "2026-05-05T11:00:00",
                    "ended_at": "2026-05-05T11:20:00",
                    "boundary_reason": "commit",
                    "scope_source": "commit_diff",
                    "summary_source": "deterministic_fallback",
                    "summary_status": "failed",
                    "summary_error": "offline",
                },
                {
                    "entry_id": "no-commit",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "activity_level": "editing",
                    "duration_min": 21,
                    "body": "No commit fallback.",
                    "commit_message": "",
                    "recent_apps": ["Codex"],
                    "top_files": ["session.py"],
                    "files_count": 1,
                    "started_at": "2026-05-05T12:00:00",
                    "ended_at": "2026-05-05T12:21:00",
                    "boundary_reason": "screen_lock",
                    "scope_source": "snapshot",
                    "summary_source": "deterministic_fallback",
                    "summary_status": "failed",
                    "summary_error": "offline",
                },
            ],
        )

        result = extractor_module.enrich_pending_journal_summaries(
            memory_dir=self.memory_dir,
            llm=FakeLLM(),
            journal_date=journal_date,
            exclude_entry_ids={"current-entry"},
        )
        entries = {
            entry["entry_id"]: entry
            for entry in extractor_module._load_journal_entries(journal_file)
        }

        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["enriched"], 1)
        self.assertEqual(entries["failed-commit"]["summary_source"], "llm")
        self.assertEqual(entries["failed-commit"]["summary_status"], "generated")
        self.assertIsNone(entries["failed-commit"]["summary_error"])
        self.assertEqual(entries["failed-commit"]["body"], "Résumé court de la session.")
        self.assertEqual(entries["current-entry"]["summary_status"], "failed")
        self.assertEqual(entries["current-entry"]["body"], "Current fallback.")
        self.assertEqual(entries["no-commit"]["summary_status"], "failed")
        self.assertEqual(entries["no-commit"]["body"], "No commit fallback.")

    def test_resume_llm_est_nettoye_avant_rendu_journal(self):
        session = {
            "active_project": "Pulse",
            "duration_min": 45,
            "probable_task": "coding",
            "recent_apps": ["Cursor"],
            "files_changed": 5,
        }

        report_ref = update_memories_from_session(
            session,
            llm=MarkdownLLM(),
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: commit markdown",
            defer_llm_enrichment=True,
        )

        ok = enrich_session_report(
            report_ref,
            session,
            MarkdownLLM(),
            commit_message="feat: commit markdown",
        )
        self.assertTrue(ok)

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        visible = journal.split("<!-- pulse-journal-data:start", 1)[0]
        self.assertIn("**feat: commit markdown**", visible)
        self.assertIn("Résumé court avec markdown parasite.", visible)
        self.assertNotIn("6.  **", visible)
        self.assertNotIn("*   **Analyse", visible)

    def test_journal_garde_les_commits_groupes_en_gras(self):
        rendered = extractor_module._render_journal_document(
            "2026-05-05",
            [
                {
                    "entry_id": "a",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "duration_min": 12,
                    "started_at": "2026-05-05T10:00:00",
                    "ended_at": "2026-05-05T10:12:00",
                    "body": "Résumé commun.",
                    "commit_messages": ["feat: premier", "fix: second"],
                    "top_files": ["extractor.py"],
                }
            ],
        )

        self.assertIn("**feat: premier**", rendered)
        self.assertIn("**fix: second**", rendered)
        self.assertNotIn("Commits : feat: premier", rendered)

    def test_journal_met_seulement_le_sujet_du_commit_en_gras(self):
        full_commit_message = (
            "fix(memory): pass full commit message body to LLM summary prompt\n\n"
            "_llm_summary was only using the first line of the commit message,\n"
            "discarding the body which contains the problem description and solution."
        )
        rendered = extractor_module._render_journal_document(
            "2026-05-05",
            [
                {
                    "entry_id": "a",
                    "active_project": "Pulse",
                    "probable_task": "coding",
                    "duration_min": 12,
                    "started_at": "2026-05-05T10:00:00",
                    "ended_at": "2026-05-05T10:12:00",
                    "body": "Résumé du commit.",
                    "commit_messages": [full_commit_message],
                    "top_files": ["extractor.py"],
                }
            ],
        )

        self.assertIn("**fix(memory): pass full commit message body to LLM summary prompt**", rendered)
        self.assertNotIn("_llm_summary was only using the first line", rendered)
        self.assertNotIn("solution.**", rendered)

    def test_commit_prefere_les_fichiers_du_diff_a_ceux_du_snapshot(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 12,
                "probable_task": "coding",
                "recent_apps": ["Codex"],
                "files_changed": 20,
                "top_files": ["daydream.py", "runtime.py"],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: dashboard state",
            diff_summary="Diff en cours : DashboardViewModel.swift (+10 -2), DashboardRootView.swift (+22 -4)",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("DashboardViewModel.swift", journal)
        self.assertIn("DashboardRootView.swift", journal)
        self.assertNotIn("daydream.py, runtime.py", journal)

    def test_commit_marque_la_portee_comme_estimee_en_dernier_recours_snapshot(self):
        update_memories_from_session(
            {
                "active_project": "Pulse",
                "duration_min": 12,
                "probable_task": "coding",
                "recent_apps": ["Codex"],
                "files_changed": 2,
                "top_files": ["daydream.py", "runtime.py"],
            },
            memory_dir=self.memory_dir,
            trigger="commit",
            commit_message="feat: fallback snapshot",
        )

        journal = next((self.memory_dir / "sessions").glob("*.md")).read_text()
        self.assertIn("Portée estimée : daydream.py, runtime.py", journal)

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
