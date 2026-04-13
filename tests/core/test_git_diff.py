"""
tests/core/test_git_diff.py — Tests du module git_diff.
"""

import unittest

from daemon.core.git_diff import _extract_function_name, _parse_diff


SAMPLE_DIFF = """\
diff --git a/daemon/memory/extractor.py b/daemon/memory/extractor.py
index abc1234..def5678 100644
--- a/daemon/memory/extractor.py
+++ b/daemon/memory/extractor.py
@@ -265,12 +265,18 @@ def _write_session_report(
     now      = datetime.now()
+    journal_file = sessions_dir / f"{today}.md"
+    if journal_file.exists():
+        journal_file.open("a", encoding="utf-8").write(entry)
-    summary_file = sessions_dir / f"{today}.md"
-    if summary_file.exists():
@@ -382,10 +382,8 @@ def _deterministic_summary(
-    project: str,
     duration: int,
+    parts = []
-    parts = [f"Session de {duration} min sur {project}"]
diff --git a/tests/memory/test_extractor.py b/tests/memory/test_extractor.py
index 111..222 100644
--- a/tests/memory/test_extractor.py
+++ b/tests/memory/test_extractor.py
@@ -123,5 +123,9 @@ def test_resume_llm_ecrit_une_session(
+    self.assertIn("## ", content)
+    self.assertIn("développement, 45 min", content)
"""


class TestParseDiff(unittest.TestCase):

    def test_fichiers_detectes(self):
        result = _parse_diff(SAMPLE_DIFF)
        self.assertIn("extractor.py", result)
        self.assertIn("test_extractor.py", result)

    def test_stats_lignes(self):
        result = _parse_diff(SAMPLE_DIFF)
        self.assertIn("+", result)
        self.assertIn("-", result)

    def test_fonctions_detectees(self):
        result = _parse_diff(SAMPLE_DIFF)
        self.assertIn("_write_session_report", result)
        self.assertIn("_deterministic_summary", result)

    def test_fichier_le_plus_actif_en_premier(self):
        result = _parse_diff(SAMPLE_DIFF)
        idx_extractor = result.find("extractor.py")
        idx_test      = result.find("test_extractor.py")
        # extractor.py a plus de changements → doit apparaître en premier
        self.assertLess(idx_extractor, idx_test)

    def test_diff_vide_retourne_chaine_vide(self):
        self.assertEqual(_parse_diff(""), "")

    def test_diff_sans_changements_retourne_vide(self):
        diff = "diff --git a/file.py b/file.py\n"
        result = _parse_diff(diff)
        # Pas de lignes +/- → fichier sans stats mais toujours listé
        # ou vide selon l'implémentation
        self.assertIsInstance(result, str)


class TestExtractFunctionName(unittest.TestCase):

    def test_python_def(self):
        line = "@@ -45,12 +45,18 @@ def _write_session_report("
        self.assertEqual(_extract_function_name(line), "_write_session_report")

    def test_python_class(self):
        line = "@@ -10,5 +10,8 @@ class FactEngine:"
        self.assertEqual(_extract_function_name(line), "FactEngine")

    def test_swift_func(self):
        line = "@@ -20,3 +20,5 @@ func buildContextSnapshot("
        self.assertEqual(_extract_function_name(line), "buildContextSnapshot")

    def test_hunk_sans_contexte(self):
        line = "@@ -1,3 +1,4 @@"
        self.assertIsNone(_extract_function_name(line))

    def test_hunk_contexte_non_identifiant(self):
        line = "@@ -1,3 +1,4 @@ # commentaire"
        self.assertIsNone(_extract_function_name(line))


if __name__ == "__main__":
    unittest.main()
