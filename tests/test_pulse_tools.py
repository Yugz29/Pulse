import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from daemon.tools import pulse_tools


class _Raw:
    complexity = 22
    cognitive_complexity = 28
    function_size = 126
    depth = 6
    churn = 1
    fan_in = 1


class _Details:
    complexity_score = 100
    cognitive_complexity_score = 38
    function_size_score = 100
    churn_score = 0
    depth_score = 100


class _Result:
    def __init__(self, *, label="high", score=71.3, path="/tmp/cognitive.py"):
        self.file_path = path
        self.global_score = score
        self.label = label
        self.parser = "ast"
        self.language = "python"
        self.hotspot_score = 22.0
        self.raw = _Raw()
        self.details = _Details()


class TestPulseTools(unittest.TestCase):
    def test_score_file_includes_label_consistent_summary(self):
        with patch("daemon.scoring.engine.score_file", return_value=_Result(label="high")):
            text = pulse_tools.score_file("/tmp/cognitive.py")

        self.assertIn("Score global : 71.3/100 (high)", text)
        self.assertIn("zone sensible du code", text)
        self.assertNotIn("fichier stable", text)

    def test_score_project_marks_output_as_relative_ranking(self):
        fake_results = [
            _Result(label="low", score=32.0, path="/tmp/a.py"),
            _Result(label="safe", score=10.0, path="/tmp/b.py"),
        ]

        with patch("daemon.tools.pulse_tools._resolve_project_path", return_value="/tmp/project"), \
             patch("os.walk", return_value=[("/tmp/project", [], ["a.py", "b.py"])]), \
             patch("daemon.scoring.engine.score_file", side_effect=fake_results):
            text = pulse_tools.score_project("/tmp/project", top_n=2)

        self.assertIn("classement relatif uniquement", text.lower())
        self.assertIn("projet reste globalement peu risque", text.lower())

    def test_score_file_resolves_malformed_absolute_path_by_basename(self):
        with patch("daemon.scoring.engine.score_file", return_value=_Result(label="high")) as score:
            text = pulse_tools.score_file("/does/not/exist/cognitive.py")

        score.assert_called_once()
        self.assertIn("Score global : 71.3/100 (high)", text)

    def test_score_file_resolves_filename_from_workspace(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "Pulse"
            project.mkdir()
            target = project / "cognitive.py"
            target.write_text("def f():\n    return 1\n", encoding="utf-8")

            fake = _Result(label="safe", score=12.0, path=str(target))
            with patch("pathlib.Path.cwd", return_value=project), \
                 patch("daemon.scoring.engine.score_file", return_value=fake) as score:
                text = pulse_tools.score_file("cognitive.py")

        score.assert_called_once()
        self.assertIn("Score global : 12.0/100 (safe)", text)


if __name__ == "__main__":
    unittest.main()
