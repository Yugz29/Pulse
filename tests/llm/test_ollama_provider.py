"""
Tests étendus pour OllamaProvider.

Couvre les chemins ajoutés récemment :
  - stream() : tokens normaux, chunk d'erreur, réponse vide  [/api/chat format]
  - complete() : succès, erreur Ollama, réponse vide
  - warmup() / unload() : succès et échec Ollama             [/api/generate conservé]
  - list_models() : cache TTL, cache stale sur erreur (existant)

Format /api/chat streaming (depuis la migration phase 1) :
  chunk normal : {"message": {"role": "assistant", "content": "token"}, "done": false}
  chunk final  : {"message": {"role": "assistant", "content": ""},      "done": true}
  chunk erreur : {"error": "...", "done": true}
"""

import json
import io
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from daemon.llm.ollama_provider import OllamaProvider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chat_chunk(content: str = "", done: bool = False) -> dict:
    """Construit un chunk au format /api/chat."""
    return {"message": {"role": "assistant", "content": content}, "done": done}

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


# ── Tests stream() ── format /api/chat ────────────────────────────────────────

class TestStream(unittest.TestCase):

    def _stream(self, *chunks):
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            return list(provider.stream("test prompt"))

    def test_retourne_tokens_normaux(self):
        chunks = [
            _chat_chunk("Bon",  done=False),
            _chat_chunk("jour", done=False),
            _chat_chunk("",     done=True),
        ]
        tokens = self._stream(*chunks)
        self.assertEqual(tokens, ["Bon", "jour"])

    def test_stoppe_sur_done_true(self):
        chunks = [
            _chat_chunk("A", done=False),
            _chat_chunk("B", done=True),
            _chat_chunk("C", done=False),  # ne doit pas apparaître
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
        valid = _chat_chunk("ok", done=True)
        body = b"not-json\n" + json.dumps(valid).encode()
        mock = MagicMock()
        mock.__enter__ = lambda s: io.BytesIO(body)
        mock.__exit__ = MagicMock(return_value=False)
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen", return_value=mock):
            tokens = list(provider.stream("test"))
        self.assertEqual(tokens, ["ok"])

    def test_utilise_endpoint_api_chat(self):
        """stream() doit appeler /api/chat, pas /api/generate."""
        chunks = [_chat_chunk("ok", done=True)]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)) as urlopen:
            list(provider.stream("test", system="sys"))
        req_obj = urlopen.call_args[0][0]
        self.assertIn("/api/chat", req_obj.full_url)

    def test_construit_messages_avec_system(self):
        """stream() doit envoyer system + user dans le tableau messages."""
        chunks = [_chat_chunk("ok", done=True)]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)) as urlopen:
            list(provider.stream("ma question", system="tu es Pulse"))
        body = json.loads(urlopen.call_args[0][0].data.decode())
        self.assertIn("messages", body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user"])
        contents = [m["content"] for m in body["messages"]]
        self.assertIn("tu es Pulse", contents)
        self.assertIn("ma question", contents)

    def test_construit_messages_sans_system(self):
        """Sans system, le tableau messages ne contient que le message user."""
        chunks = [_chat_chunk("ok", done=True)]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)) as urlopen:
            list(provider.stream("question seule"))
        body = json.loads(urlopen.call_args[0][0].data.decode())
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["user"])

    def test_num_ctx_inclus_dans_options(self):
        """num_ctx doit être présent dans les options envoyées à Ollama."""
        chunks = [_chat_chunk("ok", done=True)]
        provider = OllamaProvider(num_ctx=4096)
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)) as urlopen:
            list(provider.stream("test"))
        body = json.loads(urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["options"]["num_ctx"], 4096)


# ── Tests complete() ──────────────────────────────────────────────────────────

class TestComplete(unittest.TestCase):

    def test_retourne_texte_concatene(self):
        chunks = [
            _chat_chunk("Bonjour ", done=False),
            _chat_chunk("monde",    done=True),
        ]
        provider = OllamaProvider()
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=_ndjson_response(*chunks)):
            result = provider.complete("test")
        self.assertEqual(result, "Bonjour monde")

    def test_leve_error_si_reponse_vide(self):
        chunks = [_chat_chunk("", done=True)]
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

    def test_warmup_envoie_keep_alive_30m_via_api_generate(self):
        """warmup() doit rester sur /api/generate avec keep_alive='30m'."""
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=mock_resp) as urlopen:
            provider.warmup()
        req_obj = urlopen.call_args[0][0]
        # Doit appeler /api/generate, pas /api/chat
        self.assertIn("/api/generate", req_obj.full_url)
        body = json.loads(req_obj.data.decode())
        self.assertEqual(body["keep_alive"], "30m")

    def test_unload_envoie_keep_alive_0_via_api_generate(self):
        """unload() doit rester sur /api/generate avec keep_alive='0'."""
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("daemon.llm.ollama_provider.request.urlopen",
                   return_value=mock_resp) as urlopen:
            provider.unload()
        req_obj = urlopen.call_args[0][0]
        self.assertIn("/api/generate", req_obj.full_url)
        body = json.loads(req_obj.data.decode())
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
