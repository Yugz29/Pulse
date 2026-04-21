import unittest
from pathlib import Path

from daemon.core.file_classifier import (
    classify_file_type,
    file_signal_significance,
    is_pulse_internal_path,
)


class TestIspulseInternalPath(unittest.TestCase):

    def test_pulse_db_est_interne(self):
        path = str(Path.home() / ".pulse" / "memory.db")
        self.assertTrue(is_pulse_internal_path(path))

    def test_pulse_facts_est_interne(self):
        path = str(Path.home() / ".pulse" / "facts.db")
        self.assertTrue(is_pulse_internal_path(path))

    def test_pulse_cooldown_est_interne(self):
        path = str(Path.home() / ".pulse" / "cooldown.json")
        self.assertTrue(is_pulse_internal_path(path))

    def test_projet_utilisateur_n_est_pas_interne(self):
        path = "/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"
        self.assertFalse(is_pulse_internal_path(path))

    def test_chemin_vide_n_est_pas_interne(self):
        self.assertFalse(is_pulse_internal_path(""))


class TestClassifyFileType(unittest.TestCase):

    # ── Source ────────────────────────────────────────────────────────────────

    def test_python(self):
        self.assertEqual(classify_file_type("/projet/daemon/main.py"), "source")

    def test_swift(self):
        self.assertEqual(classify_file_type("/App/App/PanelView.swift"), "source")

    def test_typescript(self):
        self.assertEqual(classify_file_type("/projet/src/index.ts"), "source")

    def test_rust(self):
        self.assertEqual(classify_file_type("/projet/src/lib.rs"), "source")

    # ── Test ──────────────────────────────────────────────────────────────────

    def test_fichier_test_python_prefix(self):
        self.assertEqual(classify_file_type("/projet/tests/test_main.py"), "test")

    def test_fichier_test_dossier(self):
        self.assertEqual(classify_file_type("/projet/tests/core/test_engine.py"), "test")

    def test_fichier_spec_ts(self):
        self.assertEqual(classify_file_type("/projet/src/app.spec.ts"), "test")

    def test_fichier_test_swift(self):
        self.assertEqual(classify_file_type("/AppTests/ViewTest.swift"), "test")

    # ── Config ────────────────────────────────────────────────────────────────

    def test_package_json_connu(self):
        self.assertEqual(classify_file_type("/projet/package.json"), "config")

    def test_tsconfig(self):
        self.assertEqual(classify_file_type("/projet/tsconfig.json"), "config")

    def test_yaml(self):
        self.assertEqual(classify_file_type("/projet/.github/workflows/ci.yml"), "config")

    def test_toml(self):
        self.assertEqual(classify_file_type("/projet/pyproject.toml"), "config")

    def test_json_generique(self):
        self.assertEqual(classify_file_type("/projet/config/settings.json"), "config")

    # ── Docs ──────────────────────────────────────────────────────────────────

    def test_markdown(self):
        self.assertEqual(classify_file_type("/projet/README.md"), "docs")

    def test_rst(self):
        self.assertEqual(classify_file_type("/projet/docs/guide.rst"), "docs")

    # ── Assets ────────────────────────────────────────────────────────────────

    def test_png(self):
        self.assertEqual(classify_file_type("/projet/assets/logo.png"), "assets")

    def test_svg(self):
        self.assertEqual(classify_file_type("/projet/assets/icon.svg"), "assets")

    # ── Other ─────────────────────────────────────────────────────────────────

    def test_extension_inconnue(self):
        self.assertEqual(classify_file_type("/projet/data/export.parquet"), "other")


class TestFileSignalSignificance(unittest.TestCase):

    # ── Meaningful — doit passer ──────────────────────────────────────────────

    def test_source_python_projet(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/Pulse/daemon/main.py"),
            "meaningful",
        )

    def test_source_swift_projet(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/Pulse/App/App/PanelView.swift"),
            "meaningful",
        )

    def test_config_projet(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/package.json"),
            "meaningful",
        )

    def test_markdown_projet(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/README.md"),
            "meaningful",
        )

    def test_test_file(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/tests/test_main.py"),
            "meaningful",
        )

    # ── Technical noise — pip / Python env ────────────────────────────────────

    def test_past_json_site_packages(self):
        """past.json de pip — le déclencheur original du bug."""
        self.assertEqual(
            file_signal_significance("/opt/homebrew/lib/python3.13/site-packages/past.json"),
            "technical_noise",
        )

    def test_altgraph_site_packages(self):
        """altgraph metadata — autre cas réel signalé."""
        self.assertEqual(
            file_signal_significance("/usr/local/lib/python3.11/site-packages/altgraph/altgraph.json"),
            "technical_noise",
        )

    def test_site_packages_any_file(self):
        self.assertEqual(
            file_signal_significance("/usr/local/lib/python3.11/site-packages/requests/__init__.py"),
            "technical_noise",
        )

    def test_dist_packages(self):
        self.assertEqual(
            file_signal_significance("/usr/lib/python3/dist-packages/setuptools/command/install.py"),
            "technical_noise",
        )

    def test_venv_lib(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/.venv/lib/python3.11/site-packages/flask/__init__.py"),
            "technical_noise",
        )

    def test_venv_sans_point(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/venv/lib/python3.11/os.py"),
            "technical_noise",
        )

    # ── Technical noise — Homebrew ────────────────────────────────────────────

    def test_homebrew_cellar(self):
        self.assertEqual(
            file_signal_significance("/opt/homebrew/Cellar/python@3.13/3.13.2/lib/python3.13/os.py"),
            "technical_noise",
        )

    def test_homebrew_lib(self):
        self.assertEqual(
            file_signal_significance("/opt/homebrew/lib/python3.13/encodings/utf_8.py"),
            "technical_noise",
        )

    # ── Technical noise — librairies système ──────────────────────────────────

    def test_usr_local_lib(self):
        self.assertEqual(
            file_signal_significance("/usr/local/lib/python3.11/ssl.py"),
            "technical_noise",
        )

    def test_usr_lib(self):
        self.assertEqual(
            file_signal_significance("/usr/lib/python3/http/client.py"),
            "technical_noise",
        )

    def test_system_library(self):
        self.assertEqual(
            file_signal_significance("/System/Library/Frameworks/Python.framework/Versions/3.9/lib/python3.9/os.py"),
            "technical_noise",
        )

    def test_private_var(self):
        self.assertEqual(
            file_signal_significance("/private/var/folders/abc/tmp/file.py"),
            "technical_noise",
        )

    # ── Technical noise — patterns existants ─────────────────────────────────

    def test_sqlite(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/.pulse/session.db"),
            "technical_noise",
        )

    def test_wal(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/.pulse/memory.db-wal"),
            "technical_noise",
        )

    def test_log(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/daemon/pulse.log"),
            "technical_noise",
        )

    def test_pycache(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/daemon/__pycache__/main.cpython-311.pyc"),
            "technical_noise",
        )

    def test_git_interne(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/.git/refs/heads/main"),
            "technical_noise",
        )

    def test_commit_editmsg(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/.git/COMMIT_EDITMSG"),
            "technical_noise",
        )

    def test_xcuserdata(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/Pulse/App/App.xcodeproj/xcuserdata/yugz.xcuserdatad/UserInterfaceState.xcuserstate"),
            "technical_noise",
        )

    def test_pulse_interne(self):
        path = str(Path.home() / ".pulse" / "facts.db")
        self.assertEqual(file_signal_significance(path), "technical_noise")

    def test_fichier_cache_sb(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/.Trash/archive.sb-deadbeef-xyz"),
            "technical_noise",
        )

    def test_capture_ecran_macos_est_bruit_technique(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Desktop/Capture d’écran 2026-04-21 à 10.32.18.png"),
            "technical_noise",
        )

    def test_screenshot_anglais_est_bruit_technique(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Desktop/Screenshot 2026-04-21 at 10.32.18.png"),
            "technical_noise",
        )

    def test_asset_normal_reste_meaningful(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/assets/logo-final.png"),
            "meaningful",
        )

    def test_chemin_vide(self):
        self.assertEqual(file_signal_significance(""), "technical_noise")

    def test_none(self):
        self.assertEqual(file_signal_significance(None), "technical_noise")

    # ── Neutral ───────────────────────────────────────────────────────────────

    def test_lockfile(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/poetry.lock"),
            "neutral",
        )

    def test_csv(self):
        self.assertEqual(
            file_signal_significance("/Users/yugz/Projets/MonApp/data/export.csv"),
            "neutral",
        )

    def test_downloads_md_est_neutral(self):
        """Un .md téléchargé depuis un browser ne doit pas être meaningful."""
        self.assertEqual(
            file_signal_significance("/Users/yugz/Downloads/Untitled document.md"),
            "neutral",
        )

    def test_downloads_py_est_neutral(self):
        """Tout fichier dans ~/Downloads est neutral, quelle que soit l'extension."""
        self.assertEqual(
            file_signal_significance("/Users/yugz/Downloads/script.py"),
            "neutral",
        )

    # ── Plist système — neutral (pas technical_noise mais filtré du bus) ────────

    def test_plist_systeme_est_neutral(self):
        """Les plists système / app (bruit background) ne doivent PAS être meaningful."""
        system_plists = [
            "/Users/yugz/Library/Containers/com.openai.chat/appPrivateData.plist",
            "/Users/yugz/Library/Containers/com.apple.iCloud/syncstatus.plist",
            "/Users/yugz/Library/Preferences/metrics.plist",
            "/Users/yugz/Library/Caches/sharedAssetsPrefetchCount.plist",
        ]
        for path in system_plists:
            result = file_signal_significance(path)
            self.assertNotEqual(
                result, "meaningful",
                f"Plist système classé 'meaningful' à tort : {path}",
            )

    def test_info_plist_est_meaningful(self):
        """Info.plist dans un projet dev doit être meaningful via file_signal_significance."""
        result = file_signal_significance("/Users/yugz/Projets/MonApp/MonApp/Info.plist")
        self.assertEqual(result, "meaningful")

    def test_plist_generique_est_neutral(self):
        """Un .plist non référencé dans la liste de dev doit être neutral."""
        result = file_signal_significance("/Users/yugz/Projets/MonApp/foo.plist")
        self.assertNotEqual(result, "meaningful")


if __name__ == "__main__":
    unittest.main()
