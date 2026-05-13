import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from daemon.memory.embedding_policy import embeddings_enabled, embeddings_offline_only
from daemon.memory import vector_store


class TestEmbeddingPolicy(unittest.TestCase):
    def setUp(self):
        vector_store._model = None

    def tearDown(self):
        vector_store._model = None

    def test_embeddings_desactivees_par_defaut(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(embeddings_enabled())
            self.assertTrue(embeddings_offline_only())

    def test_get_model_ne_force_jamais_transformers_offline_zero(self):
        fake_module = MagicMock()
        fake_module.SentenceTransformer.return_value = object()
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), \
             patch.dict("os.environ", {"PULSE_EMBEDDINGS_ENABLED": "1"}, clear=True):
            model = vector_store._get_model()
            self.assertIsNotNone(model)
            self.assertNotEqual(os.environ.get("TRANSFORMERS_OFFLINE"), "0")
            self.assertEqual(os.environ.get("TRANSFORMERS_OFFLINE"), "1")
            self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")

    def test_offline_only_missing_model_skip_cleanly(self):
        fake_module = MagicMock()
        fake_module.SentenceTransformer.side_effect = OSError("missing local cache")
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), \
             patch.dict("os.environ", {"PULSE_EMBEDDINGS_ENABLED": "1"}, clear=True):
            model = vector_store._get_model()

        self.assertIsNone(model)


if __name__ == "__main__":
    unittest.main()
