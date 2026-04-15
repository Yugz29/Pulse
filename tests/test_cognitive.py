"""
Tests pour daemon/cognitive.py

Couvre :
  - build_system_prompt : présence du contexte, mémoire vide
  - ask() : réponse ok, message vide, LLM None, erreur offline, erreur inconnue
  - ask_stream() : tokens SSE, done final, erreur SSE
"""

import json
import unittest
from unittest.mock import patch


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


from daemon.cognitive import (
    MAX_SYSTEM_CONTEXT_CHARS,
    ask,
    ask_stream,
    ask_stream_with_tools,
    build_system_prompt,
)


# ── Tests build_system_prompt ─────────────────────────────────────────────────

class TestBuildSystemPrompt(unittest.TestCase):

    def test_contient_contexte(self):
        prompt = build_system_prompt("## État\n- Projet: Pulse")
        self.assertIn("Pulse", prompt)

    def test_contient_memoire(self):
        prompt = build_system_prompt("ctx", frozen_memory="§ Focus deep work [il y a 2h]")
        self.assertIn("deep work", prompt)

    def test_contexte_sous_budget_reste_inchange(self):
        long_ctx = "x" * 5_000
        prompt = build_system_prompt(long_ctx)
        self.assertIn(long_ctx[:200], prompt)
        self.assertIn(long_ctx[-200:], prompt)

    def test_sans_contexte_fallback(self):
        prompt = build_system_prompt("")
        self.assertIn("aucun contexte", prompt)

    def test_memoire_vide_pas_de_section_vide(self):
        prompt = build_system_prompt("ctx", frozen_memory="")
        # Ne doit pas ajouter de section mémoire vide
        self.assertNotIn("§", prompt)

    def test_contexte_long_est_tronque_au_budget(self):
        long_ctx = ("x" * (MAX_SYSTEM_CONTEXT_CHARS + 200)) + "TAIL_UNIQUE_CONTEXT"
        prompt = build_system_prompt(long_ctx)
        self.assertIn(long_ctx[:200], prompt)
        self.assertNotIn("TAIL_UNIQUE_CONTEXT", prompt)
        self.assertIn("contexte tronqué", prompt)

    def test_memoire_figee_reste_prioritaire_quand_budget_serre(self):
        frozen_memory = "M" * (MAX_SYSTEM_CONTEXT_CHARS - 100)
        context_snapshot = "C" * 500
        prompt = build_system_prompt(context_snapshot, frozen_memory=frozen_memory)
        self.assertIn(frozen_memory[:200], prompt)
        self.assertIn(frozen_memory[-200:], prompt)
        self.assertIn(context_snapshot[:50], prompt)
        self.assertNotIn(context_snapshot[-200:], prompt)

    def test_memoire_tronquee_en_dernier_recours_si_elle_depasse_seule_le_budget(self):
        frozen_memory = ("M" * (MAX_SYSTEM_CONTEXT_CHARS + 200)) + "TAIL_UNIQUE_MEMORY"
        prompt = build_system_prompt("ctx", frozen_memory=frozen_memory)
        self.assertIn(frozen_memory[:200], prompt)
        self.assertNotIn("TAIL_UNIQUE_MEMORY", prompt)
        self.assertNotIn("ctx", prompt)
        self.assertIn("contexte tronqué", prompt)

    def test_log_unique_quand_troncature_appliquee(self):
        frozen_memory = "memoire"
        context_snapshot = "x" * (MAX_SYSTEM_CONTEXT_CHARS + 200)
        with patch("daemon.cognitive.log") as log:
            prompt = build_system_prompt(context_snapshot, frozen_memory=frozen_memory)
        self.assertIn("contexte tronqué", prompt)
        log.warning.assert_called_once()
        message = log.warning.call_args[0][0]
        self.assertIn("llm_context_truncated", message)

    def test_prompt_met_en_avant_les_reperes_de_contexte_courants(self):
        snapshot = "\n".join([
            "# Contexte session",
            "- Projet : Pulse",
            "- Fichier actif : /tmp/main.py",
            "- Tâche probable : coding",
            "- Activité fichiers : 4 fichier(s) touché(s) sur 10 min, surtout code source (3), tests (1)",
            "- Lecture de la session : petit lot cohérent de 4 fichiers, ça ressemble à une évolution de fonctionnalité",
        ])

        prompt = build_system_prompt(snapshot)

        self.assertIn("Repères de contexte à privilégier", prompt)
        self.assertIn("Projet courant à privilégier : Pulse", prompt)
        self.assertIn("Fichier actif à considérer en premier : /tmp/main.py", prompt)
        self.assertIn("Activité récente utile : 4 fichier(s) touché(s)", prompt)
        self.assertIn("Lecture prudente de la session : petit lot cohérent de 4 fichiers", prompt)

    def test_prompt_demande_de_ne_pas_reposer_les_questions_deja_visibles(self):
        prompt = build_system_prompt("## État\n- Projet : Pulse")
        self.assertIn("utilise-les directement au lieu de redemander", prompt)
        self.assertIn("Traite les signaux dérivés comme des indices utiles", prompt)


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

    def test_reponse_invalide_ko(self):
        llm = _FakeLLM(raise_exc=RuntimeError("invalid_final_response: empty_final"))
        res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "invalid_response")

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

    def test_log_terminal_success(self):
        with patch("daemon.cognitive.log") as log:
            res = ask("Bonjour", self.llm)
        self.assertTrue(res["ok"])
        log.info.assert_called_once()
        message = log.info.call_args[0][0]
        self.assertIn("llm_request_terminal", message)
        self.assertIn("request_kind=ask", message)
        self.assertIn("status=success", message)

    def test_log_terminal_invalid(self):
        llm = _FakeLLM(raise_exc=RuntimeError("invalid_final_response: empty_final"))
        with patch("daemon.cognitive.log") as log:
            res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        log.warning.assert_called_once()
        message = log.warning.call_args[0][0]
        self.assertIn("request_kind=ask", message)
        self.assertIn("status=invalid", message)
        self.assertIn("reason=invalid_final_response", message)

    def test_log_terminal_error(self):
        llm = _FakeLLM(raise_exc=RuntimeError("Ollama unavailable"))
        with patch("daemon.cognitive.log") as log:
            res = ask("Question ?", llm)
        self.assertFalse(res["ok"])
        log.error.assert_called_once()
        message = log.error.call_args[0][0]
        self.assertIn("request_kind=ask", message)
        self.assertIn("status=error", message)
        self.assertIn("reason=llm_offline", message)


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

    def test_stream_reponse_invalide_emet_etat_invalid(self):
        llm = _FakeLLM(raise_exc=RuntimeError("invalid_final_response: empty_final"))
        events = self._collect(ask_stream("Test", llm))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["state"], "invalid")
        self.assertEqual(events[0]["code"], "invalid_response")

    def test_stream_partiel_puis_erreur_emet_etat_degraded(self):
        class PartialThenErrorLLM:
            @property
            def default(self):
                return self

            def get_model(self):
                return "partial/model"

            def stream_messages(self, messages, max_tokens=600):
                self.last_messages = messages
                yield "Réponse "
                raise RuntimeError("Ollama unavailable")

        events = self._collect(ask_stream("Test", PartialThenErrorLLM()))
        self.assertEqual(events[0]["token"], "Réponse ")
        self.assertFalse(events[0]["done"])
        self.assertEqual(events[1]["state"], "degraded")
        self.assertEqual(events[1]["code"], "degraded_response")

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

    def test_stream_log_terminal_success(self):
        llm = _FakeLLM("Bonjour monde")
        with patch("daemon.cognitive.log") as log:
            events = self._collect(ask_stream("Salut", llm))
        self.assertTrue(events[-1]["done"])
        log.info.assert_called_once()
        message = log.info.call_args[0][0]
        self.assertIn("request_kind=ask_stream", message)
        self.assertIn("status=success", message)

    def test_stream_log_terminal_degraded(self):
        class PartialThenErrorLLM:
            @property
            def default(self):
                return self

            def get_model(self):
                return "partial/model"

            def stream_messages(self, messages, max_tokens=600):
                yield "Réponse "
                raise RuntimeError("Ollama unavailable")

        with patch("daemon.cognitive.log") as log:
            events = self._collect(ask_stream("Test", PartialThenErrorLLM()))
        self.assertEqual(events[-1]["state"], "degraded")
        log.warning.assert_called_once()
        message = log.warning.call_args[0][0]
        self.assertIn("request_kind=ask_stream", message)
        self.assertIn("status=degraded", message)
        self.assertIn("reason=stream_interrupted", message)


class _FakeToolLLM:
    def __init__(self, responses, model="fake/tools", raise_exc=None):
        self._responses = list(responses)
        self._model = model
        self._raise_exc = raise_exc
        self.stream_messages_called = False

    @property
    def default(self):
        return self

    def get_model(self):
        return self._model

    def chat_with_tools(self, messages, tools, max_tokens=600):
        self.last_messages = messages
        self.last_tools = tools
        if self._raise_exc:
            raise self._raise_exc
        if not self._responses:
            return {"message": {"content": "", "tool_calls": []}}
        return self._responses.pop(0)

    def stream_messages(self, messages, max_tokens=600):
        self.stream_messages_called = True
        yield "ne doit pas être appelé"


class TestAskStreamWithTools(unittest.TestCase):

    def _collect(self, gen) -> list[dict]:
        events = []
        for line in gen:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def _tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "echo_tool",
                    "description": "Retourne le texte fourni.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                        },
                    },
                },
            }
        ]

    def _tool_map(self):
        return {
            "echo_tool": lambda text="": f"echo:{text}",
        }

    def test_sans_outil_reponse_directe_est_reponse_finale_canonique(self):
        llm = _FakeToolLLM([
            {"message": {"content": "Réponse directe", "tool_calls": []}},
        ])

        events = self._collect(
            ask_stream_with_tools(
                "Salut",
                llm,
                tools=self._tools(),
                tool_map=self._tool_map(),
            )
        )

        self.assertEqual(events[0]["status"], "thinking")
        self.assertEqual(events[1]["token"], "Réponse directe")
        self.assertFalse(events[1]["done"])
        self.assertTrue(events[2]["done"])
        self.assertFalse(llm.stream_messages_called)

    def test_tool_call_puis_reponse_finale_unique(self):
        llm = _FakeToolLLM([
            {
                "message": {
                    "content": "Analyse intermédiaire",
                    "tool_calls": [
                        {"function": {"name": "echo_tool", "arguments": {"text": "abc"}}}
                    ],
                }
            },
            {"message": {"content": "Réponse finale", "tool_calls": []}},
        ])

        events = self._collect(
            ask_stream_with_tools(
                "Salut",
                llm,
                tools=self._tools(),
                tool_map=self._tool_map(),
            )
        )

        self.assertEqual(events[0]["status"], "thinking")
        self.assertEqual(events[1]["tool_call"], "echo_tool")
        self.assertEqual(events[1]["status"], "running")
        self.assertEqual(events[2]["token"], "Réponse finale")
        self.assertFalse(events[2]["done"])
        self.assertTrue(events[3]["done"])
        self.assertFalse(llm.stream_messages_called)
        reconstructed = "".join(e.get("token", "") for e in events if "token" in e)
        self.assertNotIn("Analyse intermédiaire", reconstructed)

    def test_tool_call_sans_reponse_finale_termine_en_invalid(self):
        llm = _FakeToolLLM([
            {
                "message": {
                    "content": "Analyse intermédiaire",
                    "tool_calls": [
                        {"function": {"name": "echo_tool", "arguments": {"text": "abc"}}}
                    ],
                }
            },
            {"message": {"content": "", "tool_calls": []}},
        ])

        events = self._collect(
            ask_stream_with_tools(
                "Salut",
                llm,
                tools=self._tools(),
                tool_map=self._tool_map(),
            )
        )

        self.assertEqual(events[0]["status"], "thinking")
        self.assertEqual(events[1]["tool_call"], "echo_tool")
        self.assertEqual(events[2]["state"], "invalid")
        self.assertEqual(events[2]["code"], "invalid_response")
        self.assertFalse(llm.stream_messages_called)

    def test_contenu_intermediaire_avant_outil_reste_interne(self):
        llm = _FakeToolLLM([
            {
                "message": {
                    "content": "Brouillon avant outil",
                    "tool_calls": [
                        {"function": {"name": "echo_tool", "arguments": {"text": "abc"}}}
                    ],
                }
            },
            {"message": {"content": "Réponse canonique", "tool_calls": []}},
        ])

        events = self._collect(
            ask_stream_with_tools(
                "Salut",
                llm,
                tools=self._tools(),
                tool_map=self._tool_map(),
            )
        )

        token_events = [e for e in events if "token" in e and not e.get("done")]
        self.assertEqual(len(token_events), 1)
        self.assertEqual(token_events[0]["token"], "Réponse canonique")

    def test_tools_log_terminal_success(self):
        llm = _FakeToolLLM([
            {
                "message": {
                    "content": "Analyse intermédiaire",
                    "tool_calls": [
                        {"function": {"name": "echo_tool", "arguments": {"text": "abc"}}}
                    ],
                }
            },
            {"message": {"content": "Réponse finale", "tool_calls": []}},
        ])

        with patch("daemon.cognitive.log") as log:
            events = self._collect(
                ask_stream_with_tools(
                    "Salut",
                    llm,
                    tools=self._tools(),
                    tool_map=self._tool_map(),
                )
            )

        self.assertTrue(events[-1]["done"])
        log.info.assert_called_once()
        message = log.info.call_args[0][0]
        self.assertIn("request_kind=ask_stream_with_tools", message)
        self.assertIn("status=success", message)

    def test_tools_log_terminal_invalid(self):
        llm = _FakeToolLLM([
            {
                "message": {
                    "content": "Analyse intermédiaire",
                    "tool_calls": [
                        {"function": {"name": "echo_tool", "arguments": {"text": "abc"}}}
                    ],
                }
            },
            {"message": {"content": "", "tool_calls": []}},
        ])

        with patch("daemon.cognitive.log") as log:
            events = self._collect(
                ask_stream_with_tools(
                    "Salut",
                    llm,
                    tools=self._tools(),
                    tool_map=self._tool_map(),
                )
            )

        self.assertEqual(events[-1]["state"], "invalid")
        log.warning.assert_called_once()
        message = log.warning.call_args[0][0]
        self.assertIn("request_kind=ask_stream_with_tools", message)
        self.assertIn("status=invalid", message)
        self.assertIn("reason=invalid_final_response", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
