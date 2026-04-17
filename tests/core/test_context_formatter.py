import unittest

from daemon.core.context_formatter import (
    format_file_activity_summary,
    format_file_work_reading,
    has_informative_file_reading,
)
from daemon.core.signal_scorer import Signals


def _signals(**kwargs) -> Signals:
    """Construit un Signals minimal avec des valeurs par défaut neutres."""
    defaults = dict(
        active_project="Pulse",
        active_file="/tmp/main.py",
        probable_task="coding",
        friction_score=0.0,
        focus_level="normal",
        session_duration_min=20,
        recent_apps=["Cursor"],
        clipboard_context=None,
        edited_file_count_10m=0,
        file_type_mix_10m={},
        rename_delete_ratio_10m=0.0,
        dominant_file_mode="none",
        work_pattern_candidate=None,
    )
    defaults.update(kwargs)
    return Signals(**defaults)


class TestHasInformativeFileReading(unittest.TestCase):

    def test_work_pattern_candidate_suffit(self):
        s = _signals(work_pattern_candidate="refactor_candidate")
        self.assertTrue(has_informative_file_reading(s))

    def test_rename_delete_ratio_suffisant(self):
        s = _signals(rename_delete_ratio_10m=0.2)
        self.assertTrue(has_informative_file_reading(s))

    def test_ratio_insuffisant(self):
        s = _signals(rename_delete_ratio_10m=0.19)
        self.assertFalse(has_informative_file_reading(s))

    def test_plusieurs_fichiers_mode_few(self):
        s = _signals(edited_file_count_10m=2, dominant_file_mode="few_files")
        self.assertTrue(has_informative_file_reading(s))

    def test_single_file_ne_suffit_pas(self):
        s = _signals(edited_file_count_10m=2, dominant_file_mode="single_file")
        self.assertFalse(has_informative_file_reading(s))

    def test_aucun_signal(self):
        s = _signals()
        self.assertFalse(has_informative_file_reading(s))


class TestFormatFileActivitySummary(unittest.TestCase):

    def test_pas_de_fichiers(self):
        s = _signals(edited_file_count_10m=0)
        self.assertEqual(format_file_activity_summary(s), "")

    def test_un_seul_fichier(self):
        s = _signals(edited_file_count_10m=1, file_type_mix_10m={"source": 1})
        self.assertEqual(
            format_file_activity_summary(s),
            "1 fichier(s) touché(s) sur 10 min",
        )

    def test_plusieurs_fichiers_avec_mix(self):
        s = _signals(
            edited_file_count_10m=5,
            file_type_mix_10m={"source": 3, "test": 1, "docs": 1},
        )
        result = format_file_activity_summary(s)
        self.assertIn("5 fichier(s) touché(s) sur 10 min", result)
        self.assertIn("code source (3)", result)
        self.assertIn("tests (1)", result)

    def test_other_exclue_du_mix(self):
        """'other' ne doit pas apparaître dans le résumé."""
        s = _signals(
            edited_file_count_10m=7,
            file_type_mix_10m={"other": 5, "source": 2},
        )
        result = format_file_activity_summary(s)
        self.assertNotIn("other", result)
        self.assertIn("code source (2)", result)

    def test_mix_entierement_other(self):
        """Si tout est 'other', pas de précision de type."""
        s = _signals(
            edited_file_count_10m=13,
            file_type_mix_10m={"other": 13},
        )
        self.assertEqual(
            format_file_activity_summary(s),
            "13 fichier(s) touché(s) sur 10 min",
        )

    def test_max_trois_types_dans_mix(self):
        """Au plus 3 types affichés même si le mix en contient plus."""
        s = _signals(
            edited_file_count_10m=10,
            file_type_mix_10m={"source": 4, "test": 3, "config": 2, "docs": 1},
        )
        result = format_file_activity_summary(s)
        # Les 3 premiers types (par fréquence) apparaissent
        self.assertIn("code source", result)
        self.assertIn("tests", result)
        self.assertIn("configuration", result)
        # Le 4e type (docs, count=1) ne doit pas apparaître
        self.assertNotIn("documentation", result)

    def test_ordre_decroissant_par_count(self):
        """Le type le plus fréquent apparaît en premier."""
        s = _signals(
            edited_file_count_10m=6,
            file_type_mix_10m={"test": 1, "source": 4, "config": 1},
        )
        result = format_file_activity_summary(s)
        idx_source = result.index("code source")
        idx_test = result.index("tests")
        self.assertLess(idx_source, idx_test)


class TestFormatFileWorkReading(unittest.TestCase):

    def test_aucun_signal_retourne_vide(self):
        s = _signals()
        self.assertEqual(format_file_work_reading(s), "")

    def test_single_file_avec_friction(self):
        s = _signals(
            edited_file_count_10m=1,
            dominant_file_mode="single_file",
            work_pattern_candidate="debug_loop_candidate",
        )
        result = format_file_work_reading(s)
        self.assertIn("concentré sur un seul fichier", result)
        self.assertIn("boucle de correction", result)

    def test_few_files_avec_pattern_refactor(self):
        s = _signals(
            edited_file_count_10m=4,
            dominant_file_mode="few_files",
            work_pattern_candidate="refactor_candidate",
        )
        result = format_file_work_reading(s)
        self.assertIn("petit lot cohérent de 4 fichiers", result)
        self.assertIn("refactor", result)

    def test_multi_file_avec_changements_structure(self):
        s = _signals(
            edited_file_count_10m=6,
            dominant_file_mode="multi_file",
            rename_delete_ratio_10m=0.3,
        )
        result = format_file_work_reading(s)
        self.assertIn("plusieurs fichiers", result)
        self.assertIn("changements de structure", result)

    def test_ratio_eleve_changements_marques(self):
        s = _signals(
            edited_file_count_10m=5,
            dominant_file_mode="multi_file",
            rename_delete_ratio_10m=0.4,
        )
        result = format_file_work_reading(s)
        self.assertIn("marqués", result)

    def test_feature_candidate(self):
        s = _signals(
            edited_file_count_10m=3,
            dominant_file_mode="few_files",
            work_pattern_candidate="feature_candidate",
        )
        result = format_file_work_reading(s)
        self.assertIn("évolution de fonctionnalité", result)

    def test_setup_candidate(self):
        s = _signals(
            edited_file_count_10m=3,
            dominant_file_mode="few_files",
            work_pattern_candidate="setup_candidate",
        )
        result = format_file_work_reading(s)
        self.assertIn("configuration", result)

    def test_pattern_inconnu_ne_plante_pas(self):
        s = _signals(
            edited_file_count_10m=3,
            dominant_file_mode="few_files",
            work_pattern_candidate="unknown_future_pattern",
        )
        # Ne doit pas lever d'exception
        result = format_file_work_reading(s)
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
