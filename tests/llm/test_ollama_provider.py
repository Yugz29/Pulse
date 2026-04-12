"""
Tests étendus pour OllamaProvider.

Couvre les chemins ajoutés récemment :
  - stream() : tokens normaux, chunk d'erreur, réponse vide
  - complete() : succès, erreur Ollama, réponse vide
  - warmup() / unload() : succès et échec Ollama
  - list_models() : cache TTL, cache stale sur erreur (existant)
"""

import json
import io
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from daemon.llm.ollama_provider import OllamaProvider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ndjson_response(*chunks: dict):
    """Simule une réponse HTTP streaming Ollama (newline-delimited JSON)."""
    body = b"\n".join(json.dumps(c).encode() for c in chunks)
    mock = MagicMock()
    mock.__enter__ = lambda s: io.BytesIO(body)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def _json_response(payload: dict):
    """Simule une réponse HTTP JSON simple (non-streaming)."""
    class _Resp:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self):
            yield json.dumps(payload).encode()
    return _Resp()


# ── Tests list_models (existants, conservés) ──────────────────────────────────

class TestListModels(unittest.TestCase):

    def test_uses_cache_within_ttl(self):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_json_response({"models": [{"name": "mistral"}]})) as up:
            with patch("daemon.llm.ollama_provider.time.monotonic", side_effect=[10.0, 10.1, 12.0]):
                self.assertEqual(provider.list_models(), ["mistral"])
                self.assertEqual(provider.list_models(), ["mistral"])
        self.assertEqual(up.call_count, 1)

    def test_returns_stale_cache_on_error(self):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_json_response({"models": [{"name": "mistral"}]})):
            with patch("daemon.llm.ollama_provider.time.monotonic", return_value=10.0):
                provider.list_models()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   side_effect=URLError("offline")):
            with patch("daemon.llm.ollama_provider.time.monotonic", return_value=50.0):
                self.assertEqual(provider.list_models(), ["mistral"])


# ── Tests stream() ────────────────────────────────────────────────────────────

class TestStream(unittest.TestCase):

    def _stream(self, *chunks):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            return list(provider.stream("test prompt"))

    def test_retourne_tokens_normaux(self):
        chunks = [
            {"response": "Bon", "done": False},
            {"response": "jour", "done": False},
            {"response": "",    "done": True},
        ]
        tokens = self._stream(*chunks)
        self.assertEqual(tokens, ["Bon", "jour"])

    def test_stoppe_sur_done_true(self):
        chunks = [
            {"response": "A", "done": False},
            {"response": "B", "done": True},
            {"response": "C", "done": False},  # ne doit pas apparaître
        ]
        tokens = self._stream(*chunks)
        self.assertNotIn("C", tokens)

    def test_leve_runtime_error_sur_chunk_erreur(self):
        chunks = [{"error": "model not found", "done": True}]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            with self.assertRaises(RuntimeError) as ctx:
                list(provider.stream("test"))
        self.assertIn("model not found", str(ctx.exception))

    def test_leve_runtime_error_si_ollama_indisponible(self):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   side_effect=URLError("connection refused")):
            with self.assertRaises(RuntimeError):
                list(provider.stream("test"))

    def test_ignore_lignes_json_invalides(self):
        """Les lignes non-JSON ne doivent pas faire planter le stream."""
        body = b"not-json\n" + json.dumps({"response": "ok", "done": True}).encode()
        mock = MagicMock()
        mock.__enter__ = lambda s: io.BytesIO(body)
        mock.__exit__ = MagicMock(return_value=False)
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen", return_value=mock):
            tokens = list(provider.stream("test"))
        self.assertEqual(tokens, ["ok"])


# ── Tests complete() ──────────────────────────────────────────────────────────

class TestComplete(unittest.TestCase):

    def test_retourne_texte_concatene(self):
        chunks = [
            {"response": "Bonjour ", "done": False},
            {"response": "monde",    "done": True},
        ]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            result = provider.complete("test")
        self.assertEqual(result, "Bonjour monde")

    def test_leve_error_si_reponse_vide(self):
        chunks = [{"response": "", "done": True}]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete("test")
        self.assertIn("empty", str(ctx.exception))

    def test_propage_erreur_ollama(self):
        chunks = [{"error": "model 'xyz' not found", "done": True}]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete("test")
        self.assertIn("xyz", str(ctx.exception))


# ── Tests warmup() / unload() ─────────────────────────────────────────────────

class TestKeepAlive(unittest.TestCase):

    def test_warmup_retourne_true_si_ok(self):
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen", return_value=mock_resp):
            self.assertTrue(provider.warmup())
        self.assertTrue(provider.is_operational)

    def test_warmup_retourne_false_si_ollama_down(self):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   side_effect=URLError("connection refused")):
            self.assertFalse(provider.warmup())
        self.assertFalse(provider.is_operational)

    def test_unload_retourne_true_si_ok(self):
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen", return_value=mock_resp):
            self.assertTrue(provider.unload())

    def test_unload_retourne_false_si_ollama_down(self):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   side_effect=URLError("timeout")):
            self.assertFalse(provider.unload())

    def test_warmup_envoie_keep_alive_30m(self):
        """Vérifie que warmup() envoie bien keep_alive='30m'."""
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=mock_resp) as urlopen:
            provider.warmup()
        call_args = urlopen.call_args[0][0]
        body = json.loads(call_args.data.decode())
        self.assertEqual(body["keep_alive"], "30m")

    def test_unload_envoie_keep_alive_0(self):
        """Vérifie que unload() envoie bien keep_alive='0'."""
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=mock_resp) as urlopen:
            provider.unload()
        call_args = urlopen.call_args[0][0]
        body = json.loads(call_args.data.decode())
        self.assertEqual(body["keep_alive"], "0")

    def test_list_models_error_ne_casse_pas_la_sante_operationnelle(self):
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("daemon.llm.ollama_provider.request.urlopen", return_value=mock_resp):
            self.assertTrue(provider.warmup())

        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_json_response({"models": [{"name": "mistral"}]})):
            provider.list_models()

        with patch("daemon.llm.ollama_provider.request.urlopen",
                   side_effect=URLError("api/tags offline")):
            self.assertEqual(provider.list_models(), ["mistral"])

        self.assertTrue(provider.is_operational)


if __name__ == "__main__":
    unittest.main()
