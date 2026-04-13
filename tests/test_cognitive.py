"""
Tests pour daemon/cognitive.py

Couvre :
  - build_system_prompt : présence du contexte, mémoire vide
  - ask() : réponse ok, message vide, LLM None, erreur offline, erreur inconnue
  - ask_stream() : tokens SSE, done final, erreur SSE
"""

import json
import unittest


# ── Faux LLM pour les tests ───────────────────────────────────────────────────

class _FakeLLM:
    """LLM bouchon qui retourne une réponse fixe."""
    def __init__(self, response="Réponse test", model="fake/model", raise_exc=None):
        self._response  = response
        self._model     = model
        self._raise_exc = raise_exc

    def complete(self, prompt, system="", max_tokens=600):
        if self._raise_exc:
            raise self._raise_exc
        return self._response

    def get_model(self):
        return self._model

    def stream(self, prompt, system="", max_tokens=600):
        if self._raise_exc:
            raise self._raise_exc
        for token in self._response.split():
            yield token + " "

    def stream_messages(self, messages, max_tokens=600):
        if self._raise_exc:
            raise self._raise_exc
        self.last_messages = messages
        for token in self._response.split():
            yield token + " "

    # Permet à ask_stream d'accéder au provider via .default
    @property
    def default(self):
        return self


from daemon.cognitive import ask, ask_stream, build_system_prompt


# ── Tests build_system_prompt ─────────────────────────────────────────────────

class TestBuildSystemPrompt(unittest.TestCase):

    def test_contient_contexte(self):
        prompt = build_system_prompt("## État\n- Projet: Pulse")
        self.assertIn("Pulse", prompt)

    def test_contient_memoire(self):
        prompt = build_system_prompt("ctx", frozen_memory="§ Focus deep work [il y a 2h]")
        self.assertIn("deep work", prompt)

    def test_preserve_contexte_long_sans_troncature_artificielle(self):
        long_ctx = "x" * 5_000
        prompt = build_system_prompt(long_ctx)
        self.assertIn(long_ctx[:200], prompt)
        self.assertGreater(len(prompt), 5_000)

    def test_sans_contexte_fallback(self):
        prompt = build_system_prompt("")
        self.assertIn("aucun contexte", prompt)

    def test_memoire_vide_pas_de_section_vide(self):
        prompt = build_system_prompt("ctx", frozen_memory="")
        # Ne doit pas ajouter de section mémoire vide
        self.assertNotIn("§", prompt)


# ── Tests ask() ───────────────────────────────────────────────────────────────

class TestAsk(unittest.TestCase):

    def setUp(self):
        self.llm = _FakeLLM("Bonjour, je suis Pulse.")

    def test_reponse_ok(self):
        res = ask("Quel est mon projet actif ?", self.llm, context_snapshot="Projet: Pulse")
        self.assertTrue(res["ok"])
        self.assertIn("response", res)
        self.assertIn("Pulse", res["response"])

    def test_retourne_nom_du_modele(self):
        res = ask("Test", self.llm)
        self.assertTrue(res["ok"])
        self.assertEqual(res["model"], "fake/model")

    def test_message_vide_ko(self):
        res = ask("", self.llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "empty_message")

    def test_message_espaces_ko(self):
        res = ask("   ", self.llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "empty_message")

    def test_llm_none_ko(self):
        res = ask("Question ?", llm=None)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "no_llm")

    def test_llm_offline_ko(self):
        llm = _FakeLLM(raise_exc=RuntimeError("Ollama unavailable"))
        res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "llm_offline")

    def test_erreur_llm_generique(self):
        llm = _FakeLLM(raise_exc=RuntimeError("modèle introuvable"))
        res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "llm_error")

    def test_erreur_inattendue(self):
        llm = _FakeLLM(raise_exc=ValueError("bug interne"))
        res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unknown")

    def test_contexte_injecte_dans_prompt(self):
        """Le LLM reçoit bien le contexte — on vérifie via le système."""
        captured = {}

        class CaptureLLM:
            model = "capture/model"
            default = None

            def complete(self, prompt, system="", max_tokens=600):
                captured["system"] = system
                return "ok"

            def get_model(self):
                return self.model

        llm = CaptureLLM()
        llm.default = llm
        ask("Test", llm, context_snapshot="PROJET_UNIQUE_XYZ")
        self.assertIn("PROJET_UNIQUE_XYZ", captured.get("system", ""))


# ── Tests ask_stream() ────────────────────────────────────────────────────────

class TestAskStream(unittest.TestCase):

    def _collect(self, gen) -> list[dict]:
        """Collecte et parse tous les événements SSE d'un générateur."""
        events = []
        for line in gen:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def test_stream_emet_tokens(self):
        llm    = _FakeLLM("Bonjour monde")
        events = self._collect(ask_stream("Salut", llm))
        tokens = [e["token"] for e in events if not e.get("done")]
        self.assertTrue(len(tokens) >= 1)
        # Le texte reconstruit doit contenir les mots originaux
        full = "".join(tokens)
        self.assertIn("Bonjour", full)

    def test_stream_termine_par_done(self):
        llm    = _FakeLLM("Test streaming")
        events = self._collect(ask_stream("Test", llm))
        last   = events[-1]
        self.assertTrue(last.get("done"))
        self.assertIn("model", last)

    def test_stream_message_vide_emet_erreur(self):
        llm    = _FakeLLM()
        events = self._collect(ask_stream("", llm))
        self.assertEqual(len(events), 1)
        self.assertIn("error", events[0])
        self.assertEqual(events[0]["code"], "empty_message")

    def test_stream_llm_none_emet_erreur(self):
        events = self._collect(ask_stream("Test", llm=None))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["code"], "no_llm")

    def test_stream_llm_offline_emet_erreur(self):
        llm    = _FakeLLM(raise_exc=RuntimeError("Ollama unavailable"))
        events = self._collect(ask_stream("Test", llm))
        self.assertTrue(any(e.get("code") == "llm_offline" for e in events))

    def test_stream_format_sse_valide(self):
        """Chaque ligne émise doit être au format 'data: {...}\\n\\n'."""
        llm   = _FakeLLM("Token1 Token2")
        lines = list(ask_stream("Test", llm))
        for line in lines:
            self.assertTrue(
                line.startswith("data: "),
                f"Ligne SSE invalide : {line!r}"
            )
            self.assertTrue(line.endswith("\n\n"))
            # Le JSON doit être parsable
            json.loads(line[6:])

    def test_stream_inclut_historique_dans_messages(self):
        llm = _FakeLLM("Réponse")
        history = [
            {"role": "user", "content": "Question précédente"},
            {"role": "assistant", "content": "Réponse précédente"},
        ]

        self._collect(ask_stream("Nouvelle question", llm, history=history))

        self.assertEqual(llm.last_messages[1]["content"], "Question précédente")
        self.assertEqual(llm.last_messages[2]["content"], "Réponse précédente")
        self.assertEqual(llm.last_messages[-1]["content"], "Nouvelle question")


if __name__ == "__main__":
    unittest.main(verbosity=2)
