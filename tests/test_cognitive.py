"""
test_cognitive.py — Tests de cognitive.py.

Couvre :
  - _memory_guidance_block() : parsing du profil FactEngine, hints générés
  - build_system_prompt() : intégration des guidance blocks
"""

import unittest

from daemon.cognitive import (
    _memory_guidance_block,
    build_system_prompt,
)


FROZEN_WITH_PROFILE = """══ Mémoire Pulse [17 avr 2026 09:32] ══

[Session — 42% — 634/1500 car.]
§ Projet Pulse actif : daemon Python + UI Swift  [il y a 2h]

── Profil utilisateur ──
• [workflow] Travaille principalement le soir en mode développement  (conf 0.82)
• [cognitif] Sessions longues avec focus profond le matin  (conf 0.71)
• [workflow] Utilise fréquemment Cursor et Terminal ensemble  (conf 0.65)
• [cognitif] Friction élevée récurrente sur le projet Pulse  (conf 0.58)
• [cognitif] Travail souvent dispersé l'après-midi  (conf 0.51)"""

FROZEN_WITHOUT_PROFILE = """══ Mémoire Pulse [17 avr 2026 09:32] ══

[Session — 42% — 634/1500 car.]
§ Projet Pulse actif : daemon Python + UI Swift  [il y a 2h]"""


class TestMemoryGuidanceBlock(unittest.TestCase):

    def test_retourne_vide_si_frozen_memory_vide(self):
        self.assertEqual(_memory_guidance_block(""), "")

    def test_retourne_vide_si_pas_de_profil(self):
        self.assertEqual(_memory_guidance_block(FROZEN_WITHOUT_PROFILE), "")

    def test_retourne_vide_si_none(self):
        # frozen_memory peut être vide string mais pas None en prod
        self.assertEqual(_memory_guidance_block(""), "")

    def test_contient_header_de_guidage(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        self.assertIn("Profil utilisateur", result)
        self.assertIn("personnaliser", result)

    def test_extrait_les_descriptions_sans_label_categorie(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        # Les labels [workflow] [cognitif] ne doivent pas apparaître
        self.assertNotIn("[workflow]", result)
        self.assertNotIn("[cognitif]", result)

    def test_extrait_les_descriptions_sans_confiance(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        # "(conf 0.82)" ne doit pas apparaître
        self.assertNotIn("(conf", result)
        self.assertNotIn("0.82", result)

    def test_contient_les_descriptions_nettoyees(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        self.assertIn("Travaille principalement le soir en mode développement", result)
        self.assertIn("Sessions longues avec focus profond le matin", result)

    def test_limite_a_quatre_faits(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        # Le profil contient 5 faits — on doit en avoir au plus 4
        lines = [l for l in result.splitlines() if l.startswith("- ")]
        self.assertLessEqual(len(lines), 4)

    def test_le_cinquieme_fait_est_exclu(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        # "Travail souvent dispersé l'après-midi" est le 5e — doit être absent
        self.assertNotIn("dispersé", result)

    def test_format_liste_tirets(self):
        result = _memory_guidance_block(FROZEN_WITH_PROFILE)
        lines = [l for l in result.splitlines() if l.strip()]
        # Toutes les lignes de faits commencent par "- "
        fact_lines = lines[1:]  # skip le header
        self.assertTrue(all(l.startswith("- ") for l in fact_lines))

    def test_profil_avec_un_seul_fait(self):
        frozen = "── Profil utilisateur ──\n• [workflow] Coding le soir  (conf 0.70)\n"
        result = _memory_guidance_block(frozen)
        self.assertIn("Coding le soir", result)
        self.assertNotIn("[workflow]", result)
        self.assertNotIn("conf", result)

    def test_profil_vide_pas_de_bullet_retourne_vide(self):
        frozen = "── Profil utilisateur ──\n"
        result = _memory_guidance_block(frozen)
        self.assertEqual(result, "")


class TestBuildSystemPrompt(unittest.TestCase):

    def test_ne_plante_pas_sans_memoire(self):
        """build_system_prompt ne doit pas lever de NameError — le bug corrigé."""
        try:
            result = build_system_prompt("# Contexte\n- Projet : Pulse")
        except NameError as e:
            self.fail(f"NameError dans build_system_prompt : {e}")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_integre_le_profil_utilisateur_dans_le_prompt(self):
        result = build_system_prompt(
            context_snapshot="# Contexte\n- Projet : Pulse",
            frozen_memory=FROZEN_WITH_PROFILE,
        )
        self.assertIn("Profil utilisateur", result)
        self.assertIn("Travaille principalement le soir", result)

    def test_prompt_sans_profil_ne_contient_pas_de_block_profil(self):
        result = build_system_prompt(
            context_snapshot="# Contexte\n- Projet : Pulse",
            frozen_memory=FROZEN_WITHOUT_PROFILE,
        )
        self.assertNotIn("Profil utilisateur à prendre en compte", result)

    def test_prompt_vide_ne_plante_pas(self):
        result = build_system_prompt("", "", "")
        self.assertIsInstance(result, str)

    def test_guidance_context_et_memoire_coexistent(self):
        """Les deux blocs de guidance (context + memory) doivent apparaître ensemble."""
        context = (
            "# Contexte session\n"
            "- Projet : Pulse\n"
            "- Fichier actif : /tmp/main.py\n"
            "- Tâche probable : coding\n"
        )
        result = build_system_prompt(
            context_snapshot=context,
            frozen_memory=FROZEN_WITH_PROFILE,
        )
        self.assertIn("Profil utilisateur", result)
        self.assertIn("Repères de contexte", result)


if __name__ == "__main__":
    unittest.main()
